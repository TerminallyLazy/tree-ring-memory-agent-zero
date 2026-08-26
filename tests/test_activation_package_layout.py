from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_in_agent_zero_package_layout(tmp_path: Path, script: str) -> dict[str, object]:
    """Run a focused probe from Agent Zero's installed package layout."""

    runtime_root = tmp_path / "runtime"
    plugin_parent = runtime_root / "usr" / "plugins"
    plugin_parent.mkdir(parents=True)
    (plugin_parent / "tree_ring_memory").symlink_to(ROOT, target_is_directory=True)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(runtime_root), environment.get("PYTHONPATH")) if part
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["TMPDIR_FOR_TREE_RING_TEST"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=True,
        text=True,
        env=environment,
    )
    return json.loads(result.stdout)


def test_installed_package_uses_only_its_fixed_descriptor_for_activation_commands(tmp_path):
    result = _run_in_agent_zero_package_layout(
        tmp_path,
        r'''
import json
import os
import subprocess
from pathlib import Path

from usr.plugins.tree_ring_memory.helpers.activation import ActivationBinding
from usr.plugins.tree_ring_memory.helpers.cli import (
    ACTIVATION_DESCRIPTOR_ENV,
    TreeRingCli,
)
from usr.plugins.tree_ring_memory.helpers.context import InvocationContext
from usr.plugins.tree_ring_memory.helpers import paths

tmp = Path(os.environ["TMPDIR_FOR_TREE_RING_TEST"])
project = tmp / "project"
memory_root = project / ".tree-ring"
memory_root.mkdir(parents=True)
binary = tmp / "tree-ring"
binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
binary.chmod(0o755)
calls = []

def completed(command, payload):
    return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

def runner(command, **kwargs):
    calls.append({
        "command": command,
        "cwd": kwargs.get("cwd"),
        "env": kwargs["env"],
        "input": kwargs.get("input"),
    })
    if "--version" in command:
        return subprocess.CompletedProcess(command, 0, "tree-ring 0.15.4\n", "")
    if command[-1] == "init":
        return completed(command, {"ok": True})
    if "preflight" in command:
        return completed(command, {"state": "active"})
    if "status" in command:
        return completed(command, {"state": "configured-awaiting-proof"})
    return completed(command, {"ok": True})

os.environ[ACTIVATION_DESCRIPTOR_ENV] = "/tmp/caller-selected-descriptor.json"
bridge = TreeRingCli(
    {
        "cli": {"binary": str(binary)},
        "storage": {"root": str(memory_root)},
        "activation": {"project_root": str(project)},
    },
    context=InvocationContext(
        agent_profile="reviewer",
        project="must-not-reach-core-stdin",
        workflow_id="fanout-7",
        session_id="session-9",
    ),
    runner=runner,
)
binding = ActivationBinding(
    project_root=project.resolve(),
    memory_root=memory_root.resolve(),
    manifest_path=(memory_root / "activation.json").resolve(),
    store_id="store-fixture",
    project_root_fingerprint="a" * 64,
    protocol_version=1,
)
init = bridge.initialize_project_activation(project)
status = bridge.activation_status(binding)
preflight = bridge.preflight_activation(binding)
bridge.integrations_scan(source_root=str(project))
descriptor = str(paths.activation_capability_path())
print(json.dumps({
    "descriptor": descriptor,
    "init": init,
    "status": status,
    "preflight": preflight,
    "calls": calls,
    "env_name": ACTIVATION_DESCRIPTOR_ENV,
}))
''',
    )

    descriptor = str(ROOT / "activation-capability.json")
    assert result["descriptor"] == descriptor
    assert result["init"] == {"ok": True}
    assert result["status"] == {"state": "configured-awaiting-proof"}
    assert result["preflight"] == {"state": "active"}

    calls = result["calls"]
    assert isinstance(calls, list)
    command_calls = [call for call in calls if "--version" not in call["command"]]
    init_call, status_call, preflight_call, scan_call = command_calls
    assert init_call["command"][-4:] == ["--root", ".tree-ring", "--json", "init"]
    assert init_call["cwd"].endswith("/project")

    for call in (init_call, status_call, preflight_call):
        assert call["env"][result["env_name"]] == descriptor
        assert descriptor not in call["command"]
        assert descriptor not in str(call["input"])
    assert json.loads(preflight_call["input"]) == {
        "agent_profile": "reviewer",
        "workflow_id": "fanout-7",
        "session_id": "session-9",
    }
    assert result["env_name"] not in scan_call["env"]
    assert result["env_name"] not in calls[0]["env"]


def test_bootstrap_accepts_a_core_generated_passive_binding_without_rewriting_it(tmp_path):
    result = _run_in_agent_zero_package_layout(
        tmp_path,
        r'''
import json
import os
from pathlib import Path

from usr.plugins.tree_ring_memory import hooks

tmp = Path(os.environ["TMPDIR_FOR_TREE_RING_TEST"])
project = tmp / "project"
project.mkdir()
memory_root = project / ".tree-ring"
calls = []

def publish_core_binding(root):
    activation = root / ".tree-ring" / "activation"
    activation.mkdir(parents=True)
    (root / ".tree-ring" / "activation.json").write_text(json.dumps({
        "schema_version": 1,
        "protocol_version": 1,
        "store_id": "store-fixture",
        "project_root_fingerprint": "a" * 64,
        "cli_version": "0.15.4",
        "harnesses": {"agent-zero": {"state": "needs-plugin"}},
    }), encoding="utf-8")
    (activation / "agent-zero.json").write_text(json.dumps({
        "protocol_version": 1,
        "store_id": "store-fixture",
        "project_root_fingerprint": "a" * 64,
        "memory_root": ".tree-ring",
        "command_protocol": {
            "command": "tree-ring",
            "arguments": [
                "--root", ".tree-ring", "integrations", "preflight",
                "--harness", "agent-zero", "--input-json-stdin",
                "--context-format", "json",
            ],
            "stdin": "json",
            "stdout": "json",
        },
    }), encoding="utf-8")

class CoreBridge:
    def __init__(self, config):
        self.config = config

    def initialize_project_activation(self, root):
        calls.append(["init", str(root)])
        publish_core_binding(root)
        return {"ok": True}

    def status(self):
        calls.append(["status"])
        return {"ok": True, "initialized": True, "legacy_migration_pending": False}

    def audit(self, audit_type):
        calls.append(["audit", audit_type])
        return {"finding_count": 0}

    def activation_status(self, binding):
        calls.append(["activation_status", binding.store_id])
        return {"state": "configured-awaiting-proof", "next_step": "Run preflight."}

    def init(self):
        raise AssertionError("plugin must not replace the core-generated binding")

hooks.TreeRingCli = CoreBridge
report = hooks.bootstrap_runtime({
    "storage": {"root": str(memory_root)},
    "activation": {"project_root": str(project)},
})
manifest = json.loads((memory_root / "activation.json").read_text(encoding="utf-8"))
print(json.dumps({"report": report, "calls": calls, "manifest": manifest}))
''',
    )

    assert result["report"]["ready"] is True
    assert result["report"]["activation"]["state"] == "configured-awaiting-proof"
    assert result["calls"][0][0] == "init"
    assert ["activation_status", "store-fixture"] in result["calls"]
    assert result["manifest"]["harnesses"]["agent-zero"]["state"] == "needs-plugin"
