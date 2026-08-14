from __future__ import annotations

import json
from pathlib import Path

import pytest

from usr.plugins.tree_ring_memory.helpers.activation import load_activation_binding
from usr.plugins.tree_ring_memory.helpers.config import load_config
from usr.plugins.tree_ring_memory.helpers import paths


FINGERPRINT = "a" * 64


def write_protocol_one_project(
    project: Path,
    *,
    schema_version: int = 1,
    protocol_version: int = 1,
    store_id: str = "store-fixture",
    agent_zero_binding: dict[str, object] | None = None,
) -> Path:
    memory_root = project / ".tree-ring"
    (memory_root / "activation").mkdir(parents=True)
    (memory_root / "activation.json").write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "protocol_version": protocol_version,
                "store_id": store_id,
                "project_root_fingerprint": FINGERPRINT,
                "cli_version": "0.14.0",
                "harnesses": {},
            }
        ),
        encoding="utf-8",
    )
    binding = agent_zero_binding
    if binding is None:
        binding = {
            "protocol_version": protocol_version,
            "store_id": store_id,
            "project_root_fingerprint": FINGERPRINT,
            "memory_root": ".tree-ring",
            "command_protocol": {
                "command": "tree-ring",
                "arguments": [
                    "--root",
                    ".tree-ring",
                    "integrations",
                    "preflight",
                    "--harness",
                    "agent-zero",
                    "--input-json-stdin",
                    "--context-format",
                    "json",
                ],
                "stdin": "json",
                "stdout": "json",
            },
        }
    (memory_root / "activation" / "agent-zero.json").write_text(
        json.dumps(binding), encoding="utf-8"
    )
    return project


def activation_config(project: Path, memory_root: Path | None = None) -> dict[str, object]:
    return load_config(
        {
            "storage": {"root": str(memory_root or project / ".tree-ring")},
            "activation": {"project_root": str(project)},
        }
    )


def test_binding_requires_an_explicit_project_mount(tmp_path):
    config = load_config({"storage": {"root": str(tmp_path / "memory")}})

    status = load_activation_binding(config)

    assert status.state == "needs-project-mount"
    assert status.binding is None


def test_binding_classifies_a_different_plugin_store_as_active_isolated(tmp_path):
    project = write_protocol_one_project(tmp_path / "project")
    config = activation_config(project, tmp_path / "isolated")

    status = load_activation_binding(config)

    assert status.state == "active-isolated"
    assert status.store_id == "store-fixture"
    assert status.binding is not None
    assert status.binding.memory_root == (project / ".tree-ring").resolve()
    assert not (tmp_path / "isolated").exists()


def test_binding_accepts_the_mounted_project_store(tmp_path):
    project = write_protocol_one_project(tmp_path / "project")

    status = load_activation_binding(activation_config(project))

    assert status.state == "configured-awaiting-proof"
    assert status.error is None
    assert status.binding is not None
    assert status.binding.project_root == project.resolve()
    assert status.binding.manifest_path == (project / ".tree-ring/activation.json").resolve()


@pytest.mark.parametrize(
    ("manifest", "error_fragment"),
    [
        ("not json", "valid JSON"),
        ("[]", "JSON object"),
    ],
)
def test_binding_rejects_a_malformed_manifest(tmp_path, manifest, error_fragment):
    project = write_protocol_one_project(tmp_path / "project")
    (project / ".tree-ring/activation.json").write_text(manifest, encoding="utf-8")

    status = load_activation_binding(activation_config(project))

    assert status.state == "failed"
    assert status.binding is None
    assert error_fragment in (status.error or "")


@pytest.mark.parametrize(
    ("schema_version", "protocol_version", "error_fragment"),
    [
        (2, 1, "schema version"),
        (1, 2, "protocol version"),
    ],
)
def test_binding_rejects_unsupported_manifest_versions(
    tmp_path, schema_version, protocol_version, error_fragment
):
    project = write_protocol_one_project(
        tmp_path / "project",
        schema_version=schema_version,
        protocol_version=protocol_version,
    )

    status = load_activation_binding(activation_config(project))

    assert status.state == "failed"
    assert status.binding is None
    assert error_fragment in (status.error or "")


def test_binding_rejects_relative_traversal_in_agent_zero_memory_root(tmp_path):
    project = write_protocol_one_project(
        tmp_path / "project",
        agent_zero_binding={
            "protocol_version": 1,
            "store_id": "store-fixture",
            "project_root_fingerprint": FINGERPRINT,
            "memory_root": "../other-store",
            "command_protocol": {},
        },
    )

    status = load_activation_binding(activation_config(project))

    assert status.state == "failed"
    assert status.binding is None
    assert "memory root" in (status.error or "")


def test_binding_rejects_a_different_agent_zero_store_id(tmp_path):
    project = write_protocol_one_project(
        tmp_path / "project",
        agent_zero_binding={
            "protocol_version": 1,
            "store_id": "other-store",
            "project_root_fingerprint": FINGERPRINT,
            "memory_root": ".tree-ring",
            "command_protocol": {},
        },
    )

    status = load_activation_binding(activation_config(project))

    assert status.state == "failed"
    assert status.binding is None
    assert "store_id" in (status.error or "")


def test_binding_requires_the_core_agent_zero_binding(tmp_path):
    project = write_protocol_one_project(tmp_path / "project")
    (project / ".tree-ring/activation/agent-zero.json").unlink()

    status = load_activation_binding(activation_config(project))

    assert status.state == "failed"
    assert status.binding is None
    assert "tree-ring init" in status.next_step


def test_binding_requires_user_review_when_selected_activation_is_disabled(tmp_path):
    project = write_protocol_one_project(tmp_path / "project")
    config = load_config(
        {
            "storage": {"root": str(project / ".tree-ring")},
            "activation": {"enabled": False, "project_root": str(project)},
        }
    )

    status = load_activation_binding(config)

    assert status.state == "needs-user-review"
    assert status.binding is None


def test_binding_requires_user_review_for_conflicting_activation_and_scope_roots(tmp_path):
    project = tmp_path / "project"
    other_project = tmp_path / "other-project"
    config = load_config(
        {
            "activation": {"project_root": str(project)},
            "scope": {"allowed_project_root": str(other_project)},
        }
    )

    status = load_activation_binding(config)

    assert status.state == "needs-user-review"
    assert status.binding is None
    with pytest.raises(ValueError, match="conflicts"):
        paths.safe_project_root(config, None)


def test_binding_requires_user_review_for_conflicting_environment_and_scope_roots(
    tmp_path, monkeypatch
):
    environment_project = tmp_path / "environment-project"
    scope_project = tmp_path / "scope-project"
    monkeypatch.setenv("TREE_RING_MEMORY_PROJECT_ROOT", str(environment_project))
    config = load_config({"scope": {"allowed_project_root": str(scope_project)}})

    status = load_activation_binding(config)

    assert config["activation"]["project_root"] == str(environment_project)
    assert config["scope"]["allowed_project_root"] == str(scope_project)
    assert status.state == "needs-user-review"
    assert status.binding is None
    with pytest.raises(ValueError, match="conflicts"):
        paths.allowed_project_root(config)


def test_binding_rejects_a_tree_ring_symlink_outside_the_selected_project(tmp_path):
    project = tmp_path / "project"
    outside_project = write_protocol_one_project(tmp_path / "outside-project")
    project.mkdir()
    (project / ".tree-ring").symlink_to(
        outside_project / ".tree-ring", target_is_directory=True
    )

    status = load_activation_binding(activation_config(project))

    assert status.state == "needs-project-mount"
    assert status.binding is None
    assert "escapes" in (status.error or "")


@pytest.mark.parametrize("missing", ["project", "memory-root", "manifest"])
def test_binding_reports_an_unreachable_mount(tmp_path, missing):
    project = tmp_path / "project"
    if missing != "project":
        project.mkdir()
    if missing == "manifest":
        (project / ".tree-ring").mkdir()

    status = load_activation_binding(activation_config(project))

    assert status.state == "needs-project-mount"
    assert status.binding is None
    if missing == "project":
        assert not project.exists()
    elif missing == "memory-root":
        assert not (project / ".tree-ring").exists()
    else:
        assert not (project / ".tree-ring/activation.json").exists()
