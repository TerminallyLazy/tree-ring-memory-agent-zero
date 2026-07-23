from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from usr.plugins.tree_ring_memory.helpers import cli as cli_module
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli, TreeRingCliError
from usr.plugins.tree_ring_memory.helpers.context import InvocationContext


def config(root: Path, binary: Path | str) -> dict:
    return {
        "cli": {"binary": str(binary), "required_version": "0.13.0", "timeout_seconds": 10},
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

    with pytest.raises(TreeRingCliError, match="requires 0.13.0 through 0.13.x"):
        _ = bridge.version


def test_recall_preserves_rust_ranking_before_host_filters(tmp_path):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    first = _memory("mem_first", "2026-07-01T00:00:00Z", ring="scar")
    second = _memory("mem_second", "2026-07-15T00:00:00Z", ring="outer")

    def runner(command, **kwargs):
        del kwargs
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        assert "recall" in command
        payload = [
            {"memory": first, "score": 0.91, "ranking": {}},
            {"memory": second, "score": 0.72, "ranking": {}},
        ]
        return completed(command, json.dumps(payload))

    bridge = TreeRingCli(config(root, binary), runner=runner)

    result = bridge.recall("avoid regression", limit=2)

    assert [item["id"] for item in result["results"]] == ["mem_first", "mem_second"]


def test_include_all_agents_suppresses_context_defaults_but_keeps_explicit_filters(
    tmp_path,
):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    first = {
        **_memory("mem_first", "2026-07-01T00:00:00Z", ring="outer"),
        "agent_profile": "worker-a",
        "workflow_id": "fanout-1",
        "session_id": "session-a",
    }
    second = {
        **_memory("mem_second", "2026-07-01T00:00:01Z", ring="outer"),
        "agent_profile": "worker-b",
        "workflow_id": "fanout-1",
        "session_id": "session-b",
    }
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        calls.append(command)
        return completed(
            command,
            json.dumps(
                [
                    {"memory": first, "score": 0.91, "ranking": {}},
                    {"memory": second, "score": 0.72, "ranking": {}},
                ]
            ),
        )

    bridge = TreeRingCli(
        config(root, binary),
        context=InvocationContext(
            agent_profile="coordinator",
            workflow_id="fanout-1",
            session_id="coordinator-session",
        ),
        runner=runner,
    )

    result = bridge.recall(
        "worker result",
        include_all_agents=True,
        agent_profile="worker-a",
        session_id="session-a",
        limit=8,
    )

    assert calls[-1][calls[-1].index("recall") :] == [
        "recall",
        "worker result",
        "--limit",
        "100",
        "--agent-profile",
        "worker-a",
        "--workflow-id",
        "fanout-1",
        "--session-id",
        "session-a",
    ]
    assert [item["id"] for item in result["results"]] == ["mem_first"]


def test_identity_is_explicit_and_ambient_identity_is_removed(tmp_path, monkeypatch):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    calls: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setenv("TREE_RING_AGENT_PROFILE", "spoofed")
    monkeypatch.setenv("TREE_RING_WORKFLOW_ID", "spoofed-workflow")
    monkeypatch.setenv("TREE_RING_SESSION_ID", "spoofed-session")
    monkeypatch.setenv(
        "TREE_RING_COORDINATOR_TOKEN", "trcap_v1_" + ("a" * 64)
    )

    def runner(command, **kwargs):
        calls.append((command, kwargs["env"]))
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        return completed(command, json.dumps({"id": "mem_context"}))

    bridge = TreeRingCli(
        config(root, binary),
        context=InvocationContext(
            agent_profile="reviewer",
            project="tree-ring",
            workflow_id="fanout-7",
            session_id="worker-2",
        ),
        runner=runner,
    )

    bridge.remember(
        "Reviewed the worker output.",
        event_type="lesson",
        operation_id="review-17",
        source_ref="task://worker-2",
    )

    command, environment = calls[-1]
    assert command[command.index("remember") :] == [
        "remember",
        "Reviewed the worker output.",
        "--event-type",
        "lesson",
        "--ring",
        "cambium",
        "--scope",
        "agent",
        "--project",
        "tree-ring",
        "--agent-profile",
        "reviewer",
        "--workflow-id",
        "fanout-7",
        "--session-id",
        "worker-2",
        "--operation-id",
        "review-17",
        "--source-ref",
        "task://worker-2",
    ]
    for name in cli_module.IDENTITY_ENV_VARS:
        assert name not in environment


def test_capability_is_reinserted_only_for_authorized_protected_mutation(
    tmp_path, monkeypatch
):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    token = "trcap_v1_" + ("b" * 64)
    monkeypatch.setenv("TREE_RING_COORDINATOR_TOKEN", token)
    calls: list[tuple[list[str], dict[str, str]]] = []
    configured = config(root, binary)
    configured["coordination"] = {"coordinator_profiles": ["coordinator"]}

    def runner(command, **kwargs):
        calls.append((command, kwargs["env"]))
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        return completed(command, json.dumps({"id": "mem_protected"}))

    unprivileged = TreeRingCli(
        configured,
        context=InvocationContext(agent_profile="worker"),
        runner=runner,
    )
    unprivileged.forget("mem_old", mode="delete", reason="superseded")
    assert "TREE_RING_COORDINATOR_TOKEN" not in calls[-1][1]

    coordinator = TreeRingCli(
        configured,
        context=InvocationContext(agent_profile="coordinator"),
        runner=runner,
    )
    coordinator.evidence(
        "Fan-in review passed.",
        evidence_ref="eval://fan-in/7",
        operation_id="promote-7",
    )
    assert calls[-1][1]["TREE_RING_COORDINATOR_TOKEN"] == token

    coordinator.remember(
        "Coordinator kept an agent-local note.",
        event_type="lesson",
        scope="agent",
    )
    assert "TREE_RING_COORDINATOR_TOKEN" not in calls[-1][1]


def test_cli_error_never_renders_coordinator_capability(tmp_path, monkeypatch):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    token = "trcap_v1_" + ("c" * 64)
    monkeypatch.setenv("TREE_RING_COORDINATOR_TOKEN", token)
    configured = config(root, binary)
    configured["coordination"] = {"coordinator_profiles": ["coordinator"]}

    def runner(command, **kwargs):
        del kwargs
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        return completed(command, "", returncode=2, stderr=f"denied {token}")

    bridge = TreeRingCli(
        configured,
        context=InvocationContext(agent_profile="coordinator"),
        runner=runner,
    )

    with pytest.raises(TreeRingCliError) as raised:
        bridge.forget("mem_old", mode="delete", reason="superseded")
    assert token not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)


@pytest.mark.parametrize(
    "summary_template",
    [
        "{token}",
        "wrapped-before::{token}::wrapped-after",
    ],
)
def test_capability_in_write_field_is_rejected_before_any_subprocess(
    tmp_path, monkeypatch, summary_template
):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    token = "trcap_v1_" + ("d" * 64)
    monkeypatch.setenv("TREE_RING_COORDINATOR_TOKEN", token)
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        calls.append(command)
        return completed(command, "tree-ring 0.13.0\n")

    bridge = TreeRingCli(config(root, binary), runner=runner)

    with pytest.raises(
        TreeRingCliError,
        match="capability material is not accepted",
    ) as raised:
        bridge.remember(
            summary_template.format(token=token),
            event_type="lesson",
        )

    assert token not in str(raised.value)
    assert calls == []


def test_capability_is_redacted_recursively_from_successful_json_output(
    tmp_path, monkeypatch
):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    host_token = "trcap_v1_" + ("e" * 64)
    other_token = "trcap_v1_" + ("f" * 64)
    monkeypatch.setenv("TREE_RING_COORDINATOR_TOKEN", host_token)

    def runner(command, **kwargs):
        del kwargs
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        return completed(
            command,
            json.dumps(
                {
                    "ok": True,
                    "nested": {
                        "message": f"wrapped::{other_token}",
                        "coordinator_token": host_token,
                    },
                }
            ),
        )

    bridge = TreeRingCli(config(root, binary), runner=runner)
    result = bridge.policy_status()

    rendered = json.dumps(result)
    assert host_token not in rendered
    assert other_token not in rendered
    assert result["nested"]["message"] == "wrapped::[REDACTED]"
    assert "coordinator_token" not in result["nested"]


@pytest.mark.parametrize("method_name", ["policy_status", "policy_audit", "audit"])
def test_read_only_audit_wrappers_do_not_create_missing_store(
    tmp_path, method_name
):
    binary = executable(tmp_path)
    root = tmp_path / "missing-memory"
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        calls.append(command)
        return completed(command, "tree-ring 0.13.0\n")

    bridge = TreeRingCli(config(root, binary), runner=runner)

    with pytest.raises(TreeRingCliError, match="will not create it"):
        getattr(bridge, method_name)()

    assert not root.exists()
    assert calls == []


@pytest.mark.parametrize("method_name", ["policy_status", "policy_audit", "audit"])
def test_read_only_audit_wrappers_do_not_mutate_schema_v2_store(
    tmp_path, method_name
):
    binary = executable(tmp_path)
    root = tmp_path / "schema-v2-memory"
    root.mkdir(parents=True)
    database = root / "memory.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE memories (id TEXT PRIMARY KEY)")
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    finally:
        connection.close()
    original = database.read_bytes()
    original_entries = sorted(path.name for path in root.iterdir())
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        calls.append(command)
        return completed(command, "tree-ring 0.13.0\n")

    bridge = TreeRingCli(config(root, binary), runner=runner)

    with pytest.raises(TreeRingCliError, match="Schema-v3 upgrade required"):
        getattr(bridge, method_name)()

    assert database.read_bytes() == original
    assert sorted(path.name for path in root.iterdir()) == original_entries
    assert not (root / "memory.sqlite-wal").exists()
    assert not (root / "memory.sqlite-shm").exists()
    assert calls == []


@pytest.mark.parametrize("limit", [0, 1001])
def test_policy_audit_rejects_out_of_range_limit_before_dispatch(
    tmp_path, limit
):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        calls.append(command)
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        return completed(command, "[]")

    bridge = TreeRingCli(config(root, binary), runner=runner)

    with pytest.raises(TreeRingCliError, match="between 1 and 1000"):
        bridge.policy_audit(limit=limit)

    assert all("policy" not in command for command in calls)


def test_write_project_cannot_escape_active_agent_zero_project(tmp_path):
    binary = executable(tmp_path)
    root = tmp_path / "memory"
    create_schema_v3_store(root)
    bridge = TreeRingCli(
        config(root, binary),
        context=InvocationContext(
            agent_profile="worker", project="active-project"
        ),
        runner=lambda command, **kwargs: completed(
            command, "tree-ring 0.13.0\n"
        ),
    )

    with pytest.raises(TreeRingCliError, match="must match the active"):
        bridge.remember(
            "Do not cross project boundaries.",
            event_type="lesson",
            project="other-project",
        )


def test_real_v013_cli_round_trip_when_available(tmp_path):
    binary = os.environ.get("TREE_RING_MEMORY_CLI") or shutil.which("tree-ring")
    if not binary:
        pytest.skip("tree-ring CLI is not available in this runtime")
    root = tmp_path / "memory"
    bridge = TreeRingCli(config(root, binary))
    try:
        _ = bridge.version
    except TreeRingCliError:
        if os.environ.get("TREE_RING_MEMORY_CLI"):
            raise
        pytest.skip("the tree-ring CLI on PATH is not a compatible v0.13.x build")

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
    assert bridge.status()["version"] == "0.13.0"


def test_real_v013_coordinated_bridge_flow_when_available(
    tmp_path, monkeypatch
):
    binary = os.environ.get("TREE_RING_MEMORY_CLI") or shutil.which("tree-ring")
    if not binary:
        pytest.skip("tree-ring CLI is not available in this runtime")
    root = tmp_path / "coordinated-memory"
    configured = config(root, binary)
    configured["coordination"] = {"coordinator_profiles": ["coordinator"]}
    probe = TreeRingCli(configured)
    try:
        _ = probe.version
    except TreeRingCliError:
        if os.environ.get("TREE_RING_MEMORY_CLI"):
            raise
        pytest.skip("the tree-ring CLI on PATH is not a compatible v0.13.x build")
    probe.init()

    grant_result = subprocess.run(
        [
            str(probe.binary),
            "--root",
            str(root),
            "--json",
            "policy",
            "enable",
            "--coordinator",
            "agent-zero-test",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    grant = json.loads(grant_result.stdout)
    capability = grant.pop("capability")
    monkeypatch.setenv("TREE_RING_COORDINATOR_TOKEN", capability)

    blocked_calls: list[list[str]] = []

    def blocked_runner(command, **kwargs):
        del kwargs
        blocked_calls.append(command)
        return completed(command, "tree-ring 0.13.0\n")

    blocked = TreeRingCli(
        configured,
        context=InvocationContext(agent_profile="worker"),
        runner=blocked_runner,
    )
    for summary in (capability, f"wrapped::{capability}::value"):
        with pytest.raises(
            TreeRingCliError,
            match="capability material is not accepted",
        ) as rejected:
            blocked.remember(summary, event_type="lesson")
        assert capability not in str(rejected.value)
    assert blocked_calls == []

    worker = TreeRingCli(
        configured,
        context=InvocationContext(
            agent_profile="worker",
            project="tree-ring",
            workflow_id="fanout-real",
            session_id="worker-real",
        ),
    )
    first = worker.remember(
        "Worker completed the isolated shard.",
        event_type="lesson",
        operation_id="worker-shard-1",
        source_ref="task://fanout-real/worker-real",
    )
    retried = worker.remember(
        "Worker completed the isolated shard.",
        event_type="lesson",
        operation_id="worker-shard-1",
        source_ref="task://fanout-real/worker-real",
    )
    assert retried["id"] == first["id"]

    with pytest.raises(TreeRingCliError) as denied:
        worker.remember(
            "Worker attempted shared publication.",
            event_type="lesson",
            scope="workflow",
            operation_id="worker-publish-1",
        )
    assert capability not in str(denied.value)

    coordinator = TreeRingCli(
        configured,
        context=InvocationContext(
            agent_profile="coordinator",
            project="tree-ring",
            workflow_id="fanout-real",
            session_id="coordinator-real",
        ),
    )
    published = coordinator.remember(
        "Coordinator completed swarm publication.",
        event_type="summary",
        ring="inner",
        scope="workflow",
        operation_id="coordinator-publish-1",
        source_ref="task://fanout-real/fan-in",
    )
    recalled = coordinator.recall(
        "swarm publication", include_all_agents=True, limit=10
    )
    audit = coordinator.policy_audit(limit=20)

    assert published["workflow_id"] == "fanout-real"
    assert recalled["results"][0]["id"] == published["id"]
    rendered = json.dumps({"grant": grant, "audit": audit})
    assert capability not in rendered
    assert any(event.get("decision") == "denied" for event in audit)
    assert any(event.get("decision") == "allowed" for event in audit)


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


def create_schema_v3_store(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / "memory.sqlite")
    try:
        connection.execute("PRAGMA user_version=3")
        connection.commit()
    finally:
        connection.close()
