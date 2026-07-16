from __future__ import annotations

from pathlib import Path

import pytest

from usr.plugins.tree_ring_memory import hooks


def config(root: Path) -> dict:
    return {
        "cli": {"binary": "tree-ring", "required_version": "0.12.0", "timeout_seconds": 10},
        "storage": {"root": str(root), "legacy_sqlite_path": str(root / "indexes" / "memory.sqlite")},
    }


def test_bootstrap_initializes_migrates_and_audits(tmp_path, monkeypatch):
    events: list[str] = []
    statuses = [
        {"ok": True, "initialized": False, "legacy_migration_pending": True},
        {"ok": True, "initialized": True, "legacy_migration_pending": False},
    ]

    class Bridge:
        def __init__(self, resolved):
            assert resolved["storage"]["root"] == str(tmp_path)

        def status(self):
            events.append("status")
            return statuses.pop(0)

        def init(self):
            events.append("init")
            return {"ok": True}

        def audit(self, audit_type):
            events.append(f"audit:{audit_type}")
            return {"memory_count": 3, "finding_count": 0}

    class Migrator:
        def __init__(self, resolved, *, cli):
            assert resolved["storage"]["root"] == str(tmp_path)
            assert isinstance(cli, Bridge)

        def migrate(self, *, confirm):
            events.append(f"migrate:{confirm}")
            return {"ok": True, "legacy_preserved": True}

    monkeypatch.setattr(hooks.paths, "ensure_memory_dirs", lambda resolved: events.append("directories"))
    monkeypatch.setattr(hooks, "TreeRingCli", Bridge)
    monkeypatch.setattr(hooks, "LegacyMigrator", Migrator)

    report = hooks.bootstrap_runtime(config(tmp_path))

    assert events == ["directories", "status", "init", "migrate:True", "audit:all", "status"]
    assert report["ok"] is True
    assert report["initialized_now"] is True
    assert report["migration"]["legacy_preserved"] is True
    assert report["audit"]["finding_count"] == 0


def test_config_hook_bootstraps_once_per_memory_root(tmp_path, monkeypatch):
    calls: list[str] = []
    hooks._BOOTSTRAPPED_ROOTS.clear()
    monkeypatch.setattr(hooks, "bootstrap_runtime", lambda resolved: calls.append(resolved["storage"]["root"]) or {})

    first = hooks.get_plugin_config(config(tmp_path))
    second = hooks.get_plugin_config(config(tmp_path))

    assert first == second
    assert calls == [str(tmp_path)]


def test_bootstrap_fails_closed_when_cli_is_unavailable(tmp_path, monkeypatch):
    class Bridge:
        def __init__(self, resolved):
            del resolved

        def status(self):
            return {"ok": False, "initialized": False, "error": "unsupported runtime"}

    monkeypatch.setattr(hooks.paths, "ensure_memory_dirs", lambda resolved: None)
    monkeypatch.setattr(hooks, "TreeRingCli", Bridge)

    with pytest.raises(RuntimeError, match="automatic setup failed: unsupported runtime"):
        hooks.bootstrap_runtime(config(tmp_path))
