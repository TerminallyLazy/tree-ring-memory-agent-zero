from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from usr.plugins.tree_ring_memory.helpers import cli as cli_module
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli, TreeRingCliError


def config(root: Path, binary: Path | str) -> dict:
    return {
        "cli": {"binary": str(binary), "required_version": "0.12.0", "timeout_seconds": 10},
        "storage": {"root": str(root)},
        "scope": {"allowed_project_root": str(root.parent)},
    }


def executable(tmp_path: Path) -> Path:
    path = tmp_path / "tree-ring"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def completed(command: list[str], stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_status_reports_missing_cli_without_initializing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("TREE_RING_MEMORY_CLI", raising=False)
    monkeypatch.setattr(cli_module.paths, "plugin_path", lambda *parts: tmp_path / "missing-plugin-binary")
    bridge = TreeRingCli(config(tmp_path / "memory", tmp_path / "missing-tree-ring"))

    status = bridge.status()

    assert status["ok"] is False
    assert status["initialized"] is False
    assert "not installed" in status["error"]
    assert not (tmp_path / "memory").exists()


@pytest.mark.parametrize(
    ("machine", "target"),
    [("arm64", "linux-aarch64"), ("amd64", "linux-x86_64")],
)
def test_resolves_bundled_binary_for_linux_architecture(tmp_path, monkeypatch, machine, target):
    plugin_root = tmp_path / "plugin"
    binary = executable(plugin_root / "bin" / target)
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("TREE_RING_MEMORY_CLI", raising=False)
    monkeypatch.setattr(cli_module.paths, "plugin_path", lambda *parts: plugin_root.joinpath(*parts))
    monkeypatch.setattr(cli_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli_module.platform, "machine", lambda: machine)

    bridge = TreeRingCli(config(tmp_path / "memory", "tree-ring"))

    assert bridge.binary == binary.resolve()


def test_rejects_incompatible_cli_minor_version(tmp_path):
    binary = executable(tmp_path)

    def runner(command, **kwargs):
        del kwargs
        return completed(command, "tree-ring 0.11.0\n")

    bridge = TreeRingCli(config(tmp_path / "memory", binary), runner=runner)

    with pytest.raises(TreeRingCliError, match="requires 0.12.0 through 0.12.x"):
        _ = bridge.version


def test_recall_preserves_rust_ranking_before_host_filters(tmp_path):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    root.mkdir()
    (root / "memory.sqlite").touch()
    first = _memory("mem_first", "2026-07-01T00:00:00Z", ring="scar")
    second = _memory("mem_second", "2026-07-15T00:00:00Z", ring="outer")

    def runner(command, **kwargs):
        del kwargs
        if "--version" in command:
            return completed(command, "tree-ring 0.12.0\n")
        assert "recall" in command
        payload = [
            {"memory": first, "score": 0.91, "ranking": {}},
            {"memory": second, "score": 0.72, "ranking": {}},
        ]
        return completed(command, json.dumps(payload))

    bridge = TreeRingCli(config(root, binary), runner=runner)

    result = bridge.recall("avoid regression", limit=2)

    assert [item["id"] for item in result["results"]] == ["mem_first", "mem_second"]


def test_real_v012_cli_round_trip_when_available(tmp_path):
    binary = os.environ.get("TREE_RING_MEMORY_CLI") or shutil.which("tree-ring")
    if not binary:
        pytest.skip("tree-ring CLI is not available in this runtime")
    root = tmp_path / "memory"
    bridge = TreeRingCli(config(root, binary))

    initialized = bridge.init()
    remembered = bridge.remember(
        "Use the Rust-owned Agent Zero bridge.",
        event_type="decision",
        ring="outer",
        scope="project",
        project="bridge-test",
        tags=["agent-zero", "bridge"],
    )
    evidence = bridge.evidence(
        "The bridge round trip passed.",
        evidence_ref="tests/tree-ring-bridge",
        outcome="observed",
        project="bridge-test",
        score=0.9,
    )
    recalled = bridge.recall("Rust-owned bridge", project="bridge-test")
    audit = bridge.audit("all")
    export = bridge.export_to_file()

    assert initialized["ok"] is True
    assert remembered["id"].startswith("mem_")
    assert evidence["event_type"] == "evaluation_result"
    assert recalled["results"][0]["id"] == remembered["id"]
    assert audit["memory_count"] == 2
    assert Path(export["path"]).is_file()
    assert bridge.status()["version"] == "0.12.0"


def _memory(memory_id: str, updated_at: str, *, ring: str) -> dict:
    return {
        "id": memory_id,
        "created_at": updated_at,
        "updated_at": updated_at,
        "project": None,
        "agent_profile": None,
        "scope": "global",
        "ring": ring,
        "event_type": "lesson",
        "summary": memory_id,
        "details": "",
        "source": {"type": "manual", "ref": "", "quote": ""},
        "tags": [],
        "salience": 0.5,
        "confidence": 0.5,
        "sensitivity": "normal",
        "retention": "normal",
        "expires_at": None,
        "supersedes": [],
        "superseded_by": None,
        "links": [],
        "review": {"needs_review": False, "review_reason": None, "reviewed_at": None, "reviewed_by": None},
    }
