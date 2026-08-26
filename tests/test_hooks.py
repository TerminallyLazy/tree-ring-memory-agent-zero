from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from usr.plugins.tree_ring_memory import hooks


def config(root: Path) -> dict:
    return {
        "cli": {"binary": "tree-ring", "required_version": "0.15.3", "timeout_seconds": 10},
        "storage": {"root": str(root), "legacy_sqlite_path": str(root / "indexes" / "memory.sqlite")},
        "activation": {"enabled": False},
    }


def project_binding_config(project_root: Path) -> dict:
    return {
        **config(project_root.parent / "default-memory"),
        "activation": {"project_root": str(project_root)},
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

        def policy_status(self):
            events.append("policy_status")
            return {"mode": "open"}

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

    assert events == [
        "directories",
        "status",
        "init",
        "policy_status",
        "migrate:True",
        "audit:all",
        "status",
    ]
    assert report["ok"] is True
    assert report["initialized_now"] is True
    assert report["migration"]["legacy_preserved"] is True
    assert report["audit"]["finding_count"] == 0


def test_bootstrap_waits_for_project_selection_without_initializing_default_store(
    tmp_path, monkeypatch
):
    calls: list[str] = []
    unresolved = config(tmp_path / "default-memory")
    unresolved["activation"] = {"enabled": True}

    class Bridge:
        def __init__(self, resolved):
            assert resolved["storage"]["root"] == str(tmp_path / "default-memory")

        def status(self):
            calls.append("status")
            return {"ok": True, "initialized": False}

        def init(self):
            calls.append("init")
            raise AssertionError("install must wait for an Agent Zero project selection")

    monkeypatch.setattr(
        hooks.paths,
        "ensure_memory_dirs",
        lambda resolved: (_ for _ in ()).throw(
            AssertionError("install must not create the legacy global memory root")
        ),
    )
    monkeypatch.setattr(hooks, "TreeRingCli", Bridge)

    report = hooks.bootstrap_runtime(unresolved)

    assert report["ok"] is True
    assert report["ready"] is False
    assert report["activation"]["state"] == "needs-project-mount"
    assert report["message"] == "Choose an Agent Zero project to activate Tree Ring Memory."
    assert calls == ["status"]
    assert not (tmp_path / "default-memory").exists()


def test_config_hook_bootstraps_once_per_memory_root(tmp_path, monkeypatch):
    calls: list[str] = []
    hooks._BOOTSTRAPPED_ROOTS.clear()
    monkeypatch.setattr(hooks, "bootstrap_runtime", lambda resolved: calls.append(resolved["storage"]["root"]) or {})

    first = hooks.get_plugin_config(config(tmp_path))
    second = hooks.get_plugin_config(config(tmp_path))

    assert first == second
    assert calls == [str(tmp_path)]


def test_save_config_bootstraps_the_selected_project_store(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    supplied = project_binding_config(project)
    supplied["storage"]["root"] = str(project / ".tree-ring")
    calls: list[str] = []
    hooks._BOOTSTRAPPED_ROOTS.clear()
    monkeypatch.setattr(
        hooks,
        "bootstrap_runtime",
        lambda resolved: calls.append(resolved["storage"]["root"])
        or {"ok": True, "ready": True},
    )

    saved = hooks.save_plugin_config(settings=supplied)

    assert saved["activation"]["project_root"] == str(project)
    assert saved["storage"]["root"] == str(project / ".tree-ring")
    assert saved["scope"]["allowed_project_root"] == str(project)
    assert calls == [str(project / ".tree-ring")]


def test_auto_bootstrap_retries_when_project_binding_becomes_available(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    resolved = project_binding_config(project)
    calls: list[str] = []
    binding = SimpleNamespace(store_id="store-fixture")
    activation_statuses = [
        SimpleNamespace(
            state="needs-project-mount",
            binding=None,
            store_id=None,
            next_step="Configure activation.project_root to the mounted project root.",
            error="The configured project root is not reachable.",
        ),
        SimpleNamespace(
            state="configured-awaiting-proof",
            binding=binding,
            store_id="store-fixture",
            next_step="Run Tree Ring preflight in a new Agent Zero session.",
            error=None,
        ),
    ]
    statuses = [
        {"ok": True, "initialized": False},
        {"ok": True, "initialized": False},
        {"ok": True, "initialized": True},
    ]

    class Bridge:
        def __init__(self, config):
            del config

        def status(self):
            calls.append("status")
            return statuses.pop(0)

        def init(self):
            calls.append("init")
            return {"ok": True}

        def audit(self, audit_type):
            calls.append(f"audit:{audit_type}")
            return {"finding_count": 0}

        def activation_status(self, binding):
            calls.append(f"activation_status:{binding.store_id}")
            return {
                "state": "active",
                "next_step": "Continue with the current project task.",
            }

    hooks._BOOTSTRAPPED_ROOTS.clear()
    monkeypatch.setattr(hooks, "TreeRingCli", Bridge)
    monkeypatch.setattr(
        hooks, "load_activation_binding", lambda config: activation_statuses.pop(0)
    )
    monkeypatch.setattr(
        hooks.paths,
        "ensure_memory_dirs",
        lambda config: calls.append("directories"),
    )

    unavailable = hooks._ensure_auto_bootstrap(resolved)

    assert unavailable is not None
    assert unavailable["ready"] is False
    assert unavailable["activation"]["state"] == "needs-project-mount"
    assert calls == ["status"]
    assert not (tmp_path / "default-memory").exists()
    assert (tmp_path / "default-memory").resolve() not in hooks._BOOTSTRAPPED_ROOTS

    available = hooks._ensure_auto_bootstrap(resolved)

    assert available is not None
    assert available["ready"] is True
    assert available["activation"]["state"] == "active"
    assert calls == [
        "status",
        "directories",
        "status",
        "init",
        "audit:all",
        "status",
        "activation_status:store-fixture",
    ]
    assert hooks._ensure_auto_bootstrap(resolved) is None


def test_auto_bootstrap_caches_an_offline_upgrade_gate(tmp_path, monkeypatch):
    calls: list[dict] = []
    hooks._BOOTSTRAPPED_ROOTS.clear()
    monkeypatch.setattr(
        hooks,
        "bootstrap_runtime",
        lambda config: calls.append(config)
        or {
            "ready": False,
            "upgrade_required": True,
            "activation": {"state": "configured-awaiting-proof"},
        },
    )

    assert hooks._ensure_auto_bootstrap(config(tmp_path)) is not None
    assert hooks._ensure_auto_bootstrap(config(tmp_path)) is None
    assert len(calls) == 1


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


def test_bootstrap_reports_v2_upgrade_without_opening_store(tmp_path, monkeypatch):
    calls: list[str] = []

    class Bridge:
        def __init__(self, resolved):
            del resolved

        def status(self):
            calls.append("status")
            return {
                "ok": False,
                "runtime_ok": True,
                "initialized": True,
                "schema_version": 2,
                "upgrade_required": True,
            }

        def init(self):
            calls.append("init")
            raise AssertionError("schema-v2 store must not be opened")

    monkeypatch.setattr(hooks.paths, "ensure_memory_dirs", lambda resolved: None)
    monkeypatch.setattr(hooks, "TreeRingCli", Bridge)

    report = hooks.bootstrap_runtime(config(tmp_path))

    assert report["ok"] is True
    assert report["ready"] is False
    assert report["upgrade_required"] is True
    assert calls == ["status"]


def test_explicit_missing_project_binding_does_not_bootstrap_default_store(
    tmp_path, monkeypatch
):
    class Bridge:
        def __init__(self):
            self.calls: list[str] = []

        def status(self):
            self.calls.append("status")
            return {"ok": True, "initialized": False}

        def init(self):
            self.calls.append("init")
            raise AssertionError("an explicit broken binding must not initialize a store")

    bridge = Bridge()
    monkeypatch.setattr(
        hooks.paths,
        "ensure_memory_dirs",
        lambda resolved: (_ for _ in ()).throw(
            AssertionError("an explicit broken binding must not create directories")
        ),
    )
    monkeypatch.setattr(hooks, "TreeRingCli", lambda resolved: bridge)

    report = hooks.bootstrap_runtime(project_binding_config(tmp_path / "missing"))

    assert report["ok"] is True
    assert report["ready"] is False
    assert report["activation"] == {
        "state": "needs-project-mount",
        "receipt_age_seconds": None,
        "next_step": "Configure activation.project_root to the mounted project root.",
    }
    assert bridge.calls == ["status"]
    assert not (tmp_path / "default-memory").exists()
