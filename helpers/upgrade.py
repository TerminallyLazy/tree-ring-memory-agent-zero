from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from usr.plugins.tree_ring_memory.helpers import paths


TARGET_SCHEMA_VERSION = 3
UPGRADE_MARKER_NAME = "schema-v3-upgrade.json"


class SchemaUpgradeError(RuntimeError):
    pass


def inspect_store(config: dict[str, Any]) -> dict[str, Any]:
    database = paths.canonical_sqlite_path(config)
    if not database.is_file():
        return {
            "present": False,
            "path": str(database),
            "schema_version": None,
            "target_schema_version": TARGET_SCHEMA_VERSION,
            "upgrade_required": False,
            "upgrade_prepared": False,
        }
    try:
        connection = _open_read_only(database)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise SchemaUpgradeError(f"Unable to inspect the Tree Ring SQLite schema: {exc}") from exc

    marker = _read_marker(config)
    prepared = bool(marker and _marker_matches_source(marker, database, check_hash=False))
    return {
        "present": True,
        "path": str(database),
        "schema_version": version,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "upgrade_required": 0 < version < TARGET_SCHEMA_VERSION,
        "upgrade_prepared": prepared,
        "unsupported_schema": version > TARGET_SCHEMA_VERSION,
    }


def prepare_schema_upgrade(
    config: dict[str, Any], *, confirm_offline: bool
) -> dict[str, Any]:
    if not confirm_offline:
        raise SchemaUpgradeError(
            "Stop every Tree Ring CLI, plugin, TUI, and worker using this root, "
            "then confirm the store is offline before creating the schema-v3 backup."
        )

    database = paths.canonical_sqlite_path(config)
    inspection = inspect_store(config)
    version = inspection.get("schema_version")
    if not inspection.get("present"):
        raise SchemaUpgradeError("The Tree Ring store is not initialized; no schema upgrade is needed.")
    if version == TARGET_SCHEMA_VERSION:
        return {
            "ok": True,
            **inspection,
            "message": "The Tree Ring store already uses schema v3.",
        }
    if not isinstance(version, int) or version <= 0 or version > TARGET_SCHEMA_VERSION:
        raise SchemaUpgradeError(
            f"Schema version {version!r} cannot be prepared for the v0.13 schema-v3 upgrade."
        )

    migration_root = paths.ensure_memory_dirs(config) / "migrations"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = migration_root / f"pre-v0.13-schema-v{version}-{stamp}.sqlite"

    connection = None
    temporary: Path | None = None
    try:
        connection = sqlite3.connect(database, timeout=0.1, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=100")
        checkpoint = tuple(
            int(value)
            for value in connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        )
        if len(checkpoint) != 3 or checkpoint[0] != 0 or checkpoint[1] != checkpoint[2]:
            raise SchemaUpgradeError(
                "SQLite WAL checkpoint was busy; stop every process using this Tree Ring root and retry."
            )

        connection.execute("PRAGMA locking_mode=EXCLUSIVE")
        connection.execute("BEGIN EXCLUSIVE")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity.lower() != "ok":
            raise SchemaUpgradeError("Tree Ring SQLite integrity check failed; upgrade backup was not created.")

        fd, raw_path = tempfile.mkstemp(
            prefix=f".{backup.name}.", suffix=".tmp", dir=migration_root
        )
        temporary = Path(raw_path)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as destination, database.open("rb") as source:
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())

        source_sha = _sha256(database)
        backup_sha = _sha256(temporary)
        if source_sha != backup_sha:
            raise SchemaUpgradeError("The schema-upgrade backup did not match the checkpointed source.")

        connection.execute("COMMIT")
        connection.close()
        connection = None

        backup_inspection = _verified_backup(temporary)
        if backup_inspection["schema_version"] != version:
            raise SchemaUpgradeError("The schema-upgrade backup has an unexpected schema version.")
        os.replace(temporary, backup)
        temporary = None
        os.chmod(backup, 0o600)

        marker = {
            "upgrade": "tree-ring-v0.13-schema-v3",
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_path": str(database),
            "source_schema_version": version,
            "target_schema_version": TARGET_SCHEMA_VERSION,
            "source_sha256": source_sha,
            "source_size": database.stat().st_size,
            "backup_path": str(backup),
            "backup_sha256": backup_sha,
            "backup_size": backup.stat().st_size,
            "memory_count": backup_inspection["memory_count"],
            "offline_confirmed": True,
            "completed_at": None,
        }
        _write_marker(config, marker)
        return {
            "ok": True,
            "schema_version": version,
            "target_schema_version": TARGET_SCHEMA_VERSION,
            "backup_path": str(backup),
            "backup_sha256": backup_sha,
            "backup_size": backup.stat().st_size,
            "memory_count": backup_inspection["memory_count"],
            "upgrade_prepared": True,
            "message": "Verified mode-0600 pre-v0.13 backup created; the store has not been migrated.",
        }
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise SchemaUpgradeError(
                "The Tree Ring store is in use; stop every process using this root and retry."
            ) from exc
        raise SchemaUpgradeError(f"Unable to prepare the schema-v3 upgrade: {exc}") from exc
    except OSError as exc:
        raise SchemaUpgradeError(f"Unable to prepare the schema-v3 upgrade: {exc}") from exc
    finally:
        if connection is not None:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            connection.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify_prepared_upgrade(config: dict[str, Any]) -> dict[str, Any]:
    marker = _read_marker(config)
    if not marker:
        raise SchemaUpgradeError(
            "A verified pre-v0.13 backup is required before this plugin will migrate the store to schema v3."
        )
    database = paths.canonical_sqlite_path(config)
    _checkpoint_source_for_verification(database)
    if not _marker_matches_source(marker, database, check_hash=True):
        raise SchemaUpgradeError(
            "The Tree Ring store changed after its upgrade backup; stop all users and prepare a fresh backup."
        )

    backup = _trusted_backup_path(config, marker.get("backup_path"))
    expected_sha = str(marker.get("backup_sha256") or "")
    if not backup.is_file() or not expected_sha or _sha256(backup) != expected_sha:
        raise SchemaUpgradeError("The recorded pre-v0.13 backup is missing or failed checksum verification.")
    if stat.S_IMODE(backup.stat().st_mode) != 0o600:
        raise SchemaUpgradeError("The pre-v0.13 backup must retain mode 0600.")
    backup_inspection = _verified_backup(backup)
    if backup_inspection["schema_version"] != marker.get("source_schema_version"):
        raise SchemaUpgradeError("The recorded pre-v0.13 backup schema does not match its marker.")
    return marker


def _checkpoint_source_for_verification(database: Path) -> None:
    connection = None
    try:
        connection = sqlite3.connect(database, timeout=0.1, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=100")
        checkpoint = tuple(
            int(value)
            for value in connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        )
        if len(checkpoint) != 3 or checkpoint[0] != 0 or checkpoint[1] != checkpoint[2]:
            raise SchemaUpgradeError(
                "SQLite WAL checkpoint was busy; keep every Tree Ring process stopped and retry."
            )
        connection.execute("PRAGMA locking_mode=EXCLUSIVE")
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("COMMIT")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise SchemaUpgradeError(
                "The Tree Ring store is in use; stop every process using this root and retry."
            ) from exc
        raise SchemaUpgradeError(
            f"Unable to reverify the checkpointed Tree Ring store: {exc}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def mark_upgrade_completed(config: dict[str, Any], *, cli_version: str) -> None:
    marker = _read_marker(config)
    if not marker:
        return
    marker["completed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    marker["tree_ring_version"] = cli_version
    _write_marker(config, marker)


def _verified_backup(database: Path) -> dict[str, int]:
    try:
        connection = _open_read_only(database)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity.lower() != "ok":
                raise SchemaUpgradeError("The pre-v0.13 backup failed SQLite integrity verification.")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            has_memories = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
            count = (
                int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
                if has_memories
                else 0
            )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise SchemaUpgradeError(f"Unable to verify the pre-v0.13 backup: {exc}") from exc
    return {"schema_version": version, "memory_count": count}


def _marker_matches_source(marker: dict[str, Any], database: Path, *, check_hash: bool) -> bool:
    try:
        if Path(str(marker.get("source_path") or "")).resolve() != database.resolve():
            return False
        if int(marker.get("target_schema_version")) != TARGET_SCHEMA_VERSION:
            return False
        if int(marker.get("source_size")) != database.stat().st_size:
            return False
        if check_hash and str(marker.get("source_sha256") or "") != _sha256(database):
            return False
        return bool(marker.get("offline_confirmed"))
    except (OSError, TypeError, ValueError):
        return False


def _open_read_only(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _marker_path(config: dict[str, Any]) -> Path:
    return paths.memory_root(config) / "migrations" / UPGRADE_MARKER_NAME


def _read_marker(config: dict[str, Any]) -> dict[str, Any] | None:
    marker_path = _marker_path(config)
    try:
        value = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_marker(config: dict[str, Any], marker: dict[str, Any]) -> None:
    marker_path = _marker_path(config)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, marker_path)


def _trusted_backup_path(config: dict[str, Any], value: Any) -> Path:
    if not value:
        raise SchemaUpgradeError("The schema-upgrade marker does not name a backup.")
    try:
        return paths.assert_under(paths.ensure_memory_dirs(config) / "migrations", Path(str(value)))
    except ValueError as exc:
        raise SchemaUpgradeError("The schema-upgrade backup path is outside the migration directory.") from exc
