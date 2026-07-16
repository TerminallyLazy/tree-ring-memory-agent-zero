from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from usr.plugins.tree_ring_memory.helpers import paths
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli, TreeRingCliError
from usr.plugins.tree_ring_memory.helpers.config import load_config


SCOPE_MAP = {"chat": "session"}


class LegacyMigrationError(RuntimeError):
    pass


class LegacyMigrator:
    """Import the Python-v1 store through the Rust CLI without mutating it."""

    def __init__(self, config: dict[str, Any] | None = None, *, cli: TreeRingCli | None = None) -> None:
        self.config = load_config(config)
        self.cli = cli or TreeRingCli(self.config)
        self.source = paths.legacy_sqlite_path(self.config)
        self.marker = paths.migration_marker_path(self.config)

    def inspect(self) -> dict[str, Any]:
        if not self.source.is_file():
            return {"present": False, "path": str(self.source), "memory_count": 0}
        connection = self._open_read_only()
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            memory_count = int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        except sqlite3.Error as exc:
            raise LegacyMigrationError(f"Unable to inspect the legacy store: {exc}") from exc
        finally:
            connection.close()
        if integrity.lower() != "ok":
            raise LegacyMigrationError("Legacy SQLite integrity check failed; migration was not attempted.")
        return {
            "present": True,
            "path": str(self.source),
            "memory_count": memory_count,
            "already_migrated": self.marker.is_file(),
        }

    def migrate(self, *, confirm: bool = False, force: bool = False) -> dict[str, Any]:
        inspection = self.inspect()
        if not inspection["present"]:
            return {"ok": True, **inspection, "dry_run": not confirm, "message": "No legacy store found."}
        if inspection.get("already_migrated") and not force:
            return {"ok": True, **inspection, "dry_run": False, "message": "Legacy migration already completed."}

        events = self._read_normalized_events()
        migration_dir = paths.ensure_memory_dirs(self.config) / "migrations"
        fd, raw_path = tempfile.mkstemp(prefix="legacy-python-v1-", suffix=".jsonl", dir=migration_dir)
        temp_path = Path(raw_path)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                self._write_jsonl(handle, events)
            preview = self.cli.import_trusted_migration_file(temp_path, dry_run=True)
            report: dict[str, Any] = {
                "ok": True,
                "source_path": str(self.source),
                "source_memory_count": len(events),
                "dry_run": not confirm,
                "preview": preview,
                "legacy_preserved": True,
            }
            if not confirm:
                report["message"] = "Migration validated. Re-run with explicit confirmation to import."
                return report

            imported = self.cli.import_trusted_migration_file(temp_path, dry_run=False)
            report["import"] = imported
            report["dry_run"] = False
            report["message"] = "Legacy memories imported through the Rust CLI; the source database was preserved."
            self._write_marker(report)
            return report
        except (OSError, sqlite3.Error, TreeRingCliError) as exc:
            raise LegacyMigrationError(str(exc)) from exc
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_normalized_events(self) -> list[dict[str, Any]]:
        connection = self._open_read_only()
        try:
            rows = connection.execute(
                "SELECT raw_json FROM memories ORDER BY created_at ASC, id ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            raise LegacyMigrationError(f"Unable to read the legacy store: {exc}") from exc
        finally:
            connection.close()
        events = []
        for index, row in enumerate(rows, start=1):
            try:
                value = json.loads(row[0])
            except (TypeError, json.JSONDecodeError) as exc:
                raise LegacyMigrationError(f"Legacy memory row {index} contains invalid JSON.") from exc
            events.append(_normalize_event(value, index=index))
        return events

    def _open_read_only(self) -> sqlite3.Connection:
        try:
            # ``as_uri`` percent-encodes path characters such as ``?`` and
            # ``#`` so they cannot be misread as SQLite URI parameters.
            return sqlite3.connect(f"{self.source.resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise LegacyMigrationError(f"Unable to open the legacy store read-only: {exc}") from exc

    def _write_jsonl(self, handle: Any, events: list[dict[str, Any]]) -> None:
        header = {
            "type": "tree_ring_memory_export",
            "schema_version": 1,
            "plugin_version": self.cli.required_version,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "memory_count": len(events),
            "sensitive_included": any(event.get("sensitivity") != "normal" for event in events),
        }
        handle.write(json.dumps(header, sort_keys=True) + "\n")
        for event in events:
            handle.write(json.dumps({"type": "memory_event", "memory": event}, sort_keys=True) + "\n")

    def _write_marker(self, report: dict[str, Any]) -> None:
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        marker = {
            "migration": "legacy-python-v1",
            "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_path": str(self.source),
            "source_memory_count": report["source_memory_count"],
            "tree_ring_version": self.cli.version,
            "legacy_preserved": True,
        }
        temporary = self.marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.marker)


def _normalize_event(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LegacyMigrationError(f"Legacy memory row {index} is not an object.")
    event = dict(value)
    event.pop("schema_version", None)
    for field in ("id", "created_at", "updated_at", "event_type", "summary"):
        if not str(event.get(field) or "").strip():
            raise LegacyMigrationError(f"Legacy memory row {index} is missing {field}.")
        event[field] = str(event[field])
    event["scope"] = SCOPE_MAP.get(str(event.get("scope") or "global"), str(event.get("scope") or "global"))
    event["ring"] = str(event.get("ring") or "cambium")
    event["details"] = str(event.get("details") or "")
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    event["source"] = {
        "type": str(source.get("type") or "manual"),
        "ref": str(source.get("ref") or ""),
        "quote": str(source.get("quote") or ""),
    }
    event["tags"] = _string_list(event.get("tags"))
    event["supersedes"] = _string_list(event.get("supersedes"))
    event["links"] = [
        {"type": str(item.get("type") or "memory"), "target": str(item.get("target") or "")}
        for item in (event.get("links") or [])
        if isinstance(item, dict) and str(item.get("target") or "")
    ]
    event["salience"] = float(event.get("salience", 0.5))
    event["confidence"] = float(event.get("confidence", 0.5))
    event["sensitivity"] = str(event.get("sensitivity") or "normal")
    event["retention"] = str(event.get("retention") or "normal")
    review = event.get("review") if isinstance(event.get("review"), dict) else {}
    event["review"] = {
        "needs_review": bool(review.get("needs_review", False)),
        "review_reason": review.get("review_reason"),
        "reviewed_at": review.get("reviewed_at"),
        "reviewed_by": review.get("reviewed_by"),
    }
    return event


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []
