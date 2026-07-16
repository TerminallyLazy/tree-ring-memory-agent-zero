from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from usr.plugins.tree_ring_memory.helpers.config import load_config
from usr.plugins.tree_ring_memory.helpers.legacy import LegacyMigrator


class StubCli:
    required_version = "0.12.0"
    version = "0.12.0"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def import_trusted_migration_file(self, path: Path, *, dry_run: bool, replace_existing: bool = False):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.calls.append(
            {
                "dry_run": dry_run,
                "replace_existing": replace_existing,
                "records": records,
            }
        )
        count = len(records) - 1
        return {
            "ok": True,
            "valid_count": count,
            "inserted_count": 0 if dry_run else count,
            "dry_run": dry_run,
        }


def test_migration_preview_normalizes_v1_without_mutating_source(tmp_path):
    legacy = tmp_path / "memory" / "indexes" / "memory.sqlite"
    create_legacy_store(legacy)
    original = legacy.read_bytes()
    stub = StubCli()
    migrator = LegacyMigrator(config(tmp_path, legacy), cli=stub)  # type: ignore[arg-type]

    report = migrator.migrate(confirm=False)

    memory = stub.calls[0]["records"][1]["memory"]
    assert report["dry_run"] is True
    assert len(stub.calls) == 1
    assert memory["scope"] == "session"
    assert memory["details"] == ""
    assert memory["source"]["quote"] == ""
    assert legacy.read_bytes() == original
    assert not migrator.marker.exists()
    assert not list(migrator.marker.parent.glob("legacy-python-v1-*.jsonl"))


def test_confirmed_migration_marks_completion_and_preserves_legacy(tmp_path):
    legacy = tmp_path / "memory" / "indexes" / "memory.sqlite"
    create_legacy_store(legacy)
    original = legacy.read_bytes()
    stub = StubCli()
    migrator = LegacyMigrator(config(tmp_path, legacy), cli=stub)  # type: ignore[arg-type]

    report = migrator.migrate(confirm=True)

    assert report["dry_run"] is False
    assert [call["dry_run"] for call in stub.calls] == [True, False]
    assert migrator.marker.is_file()
    assert legacy.read_bytes() == original
    assert migrator.migrate(confirm=True)["message"] == "Legacy migration already completed."


def test_legacy_read_only_uri_handles_reserved_path_characters(tmp_path):
    legacy = tmp_path / "memory?archive" / "indexes" / "memory.sqlite"
    create_legacy_store(legacy)

    inspection = LegacyMigrator(config(tmp_path, legacy), cli=StubCli()).inspect()  # type: ignore[arg-type]

    assert inspection["memory_count"] == 1


def config(tmp_path: Path, legacy: Path) -> dict:
    return load_config(
        {
            "storage": {"root": str(tmp_path / "memory"), "legacy_sqlite_path": str(legacy)},
            "scope": {"allowed_project_root": str(tmp_path)},
        }
    )


def create_legacy_store(path: Path) -> None:
    path.parent.mkdir(parents=True)
    event = {
        "schema_version": "1.0",
        "id": "mem_legacy",
        "created_at": "2026-07-04T00:00:00+00:00",
        "updated_at": "2026-07-04T00:00:00+00:00",
        "project": "agent-zero",
        "agent_profile": None,
        "scope": "chat",
        "ring": "outer",
        "event_type": "lesson",
        "summary": "Preserve legacy memory.",
        "details": None,
        "source": {"type": "manual", "ref": None, "quote": None},
        "tags": ["migration"],
        "salience": 0.7,
        "confidence": 0.8,
        "sensitivity": "normal",
        "retention": "normal",
        "expires_at": None,
        "supersedes": [],
        "superseded_by": None,
        "links": [],
        "review": {},
    }
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, created_at TEXT, raw_json TEXT)")
        connection.execute(
            "INSERT INTO memories (id, created_at, raw_json) VALUES (?, ?, ?)",
            (event["id"], event["created_at"], json.dumps(event)),
        )
        connection.commit()
    finally:
        connection.close()
