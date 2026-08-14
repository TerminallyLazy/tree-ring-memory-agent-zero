from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths


ACTIVATION_PROTOCOL_VERSION = 1
_ACTIVATION_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_AGENT_ZERO_ARGUMENTS = [
    "--root",
    ".tree-ring",
    "integrations",
    "preflight",
    "--harness",
    "agent-zero",
    "--input-json-stdin",
    "--context-format",
    "json",
]


@dataclass(frozen=True)
class ActivationBinding:
    project_root: Path
    memory_root: Path
    manifest_path: Path
    store_id: str
    project_root_fingerprint: str
    protocol_version: int


@dataclass(frozen=True)
class ActivationBindingStatus:
    state: str
    binding: ActivationBinding | None
    next_step: str
    error: str | None = None

    @property
    def store_id(self) -> str | None:
        return self.binding.store_id if self.binding else None


def load_activation_binding(config: dict[str, Any]) -> ActivationBindingStatus:
    """Read and validate the project-local Agent Zero activation binding."""

    project_root = paths.activation_project_root(config)
    if project_root is None:
        return _needs_project_mount("No activation project mount is configured.")

    activation = config.get("activation") or {}
    if activation.get("enabled") is False:
        return ActivationBindingStatus(
            state="needs-user-review",
            binding=None,
            next_step="Enable activation for the selected project or remove the project binding.",
            error="Activation is disabled while a project mount is selected.",
        )
    configured_protocol = activation.get("protocol_version", ACTIVATION_PROTOCOL_VERSION)
    if not _is_version(configured_protocol) or configured_protocol != ACTIVATION_PROTOCOL_VERSION:
        return ActivationBindingStatus(
            state="needs-user-review",
            binding=None,
            next_step="Set activation.protocol_version to 1 after reviewing plugin compatibility.",
            error="The configured activation protocol is unsupported.",
        )

    if not project_root.is_dir():
        return _needs_project_mount("The configured project root is not reachable.")
    memory_root = (project_root / ".tree-ring").resolve()
    if not memory_root.is_dir():
        return _needs_project_mount("The mounted project .tree-ring root is not reachable.")

    manifest_path = paths.activation_manifest_path(config)
    if manifest_path is None or not _is_direct_child(memory_root, manifest_path, "activation.json"):
        return _failed("The activation manifest path escapes the mounted .tree-ring root.")
    if not manifest_path.is_file():
        return _needs_project_mount("The mounted project activation manifest is not reachable.")

    try:
        manifest = _read_json_object(manifest_path, "activation manifest")
        _validate_manifest(manifest)
        binding = ActivationBinding(
            project_root=project_root,
            memory_root=memory_root,
            manifest_path=manifest_path,
            store_id=manifest["store_id"],
            project_root_fingerprint=manifest["project_root_fingerprint"],
            protocol_version=manifest["protocol_version"],
        )
        _validate_agent_zero_binding(binding)
    except _BindingError as error:
        return _failed(str(error))

    configured_memory_root = paths.memory_root(config).resolve()
    if configured_memory_root != memory_root:
        return ActivationBindingStatus(
            state="active-isolated",
            binding=binding,
            next_step="Point storage.root at the mounted project .tree-ring root to share memory.",
        )
    return ActivationBindingStatus(
        state="configured-awaiting-proof",
        binding=binding,
        next_step="Run Tree Ring preflight in a new Agent Zero session.",
    )


class _BindingError(ValueError):
    pass


def _needs_project_mount(error: str) -> ActivationBindingStatus:
    return ActivationBindingStatus(
        state="needs-project-mount",
        binding=None,
        next_step="Configure activation.project_root to the mounted project root.",
        error=error,
    )


def _failed(error: str) -> ActivationBindingStatus:
    next_step = "Repair the project activation files, then run tree-ring init again."
    return ActivationBindingStatus(state="failed", binding=None, next_step=next_step, error=error)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise _BindingError(f"The {label} is not valid JSON.") from error
    except OSError as error:
        raise _BindingError(f"The {label} cannot be read.") from error
    if not isinstance(value, dict):
        raise _BindingError(f"The {label} must be a JSON object.")
    return value


def _validate_manifest(manifest: dict[str, Any]) -> None:
    _require_version(manifest, "schema_version", _ACTIVATION_SCHEMA_VERSION, "schema")
    _require_version(manifest, "protocol_version", ACTIVATION_PROTOCOL_VERSION, "protocol")
    _require_identifier(manifest, "store_id", "store_id")
    _require_fingerprint(manifest, "project_root_fingerprint")
    _require_identifier(manifest, "cli_version", "CLI version")
    if not isinstance(manifest.get("harnesses"), dict):
        raise _BindingError("The activation manifest harnesses field must be an object.")


def _validate_agent_zero_binding(binding: ActivationBinding) -> None:
    path = (binding.memory_root / "activation" / "agent-zero.json").resolve()
    if not _is_under(binding.memory_root, path) or path.name != "agent-zero.json":
        raise _BindingError("The Agent Zero binding path escapes the mounted .tree-ring root.")
    if not path.is_file():
        raise _BindingError("The core Agent Zero binding is missing; run tree-ring init.")

    value = _read_json_object(path, "Agent Zero binding")
    _require_version(value, "protocol_version", ACTIVATION_PROTOCOL_VERSION, "protocol")
    store_id = _require_identifier(value, "store_id", "store_id")
    fingerprint = _require_fingerprint(value, "project_root_fingerprint")
    if store_id != binding.store_id:
        raise _BindingError("The Agent Zero binding store_id does not match the activation manifest.")
    if fingerprint != binding.project_root_fingerprint:
        raise _BindingError(
            "The Agent Zero binding project fingerprint does not match the activation manifest."
        )
    if value.get("memory_root") != ".tree-ring":
        raise _BindingError("The Agent Zero binding memory root must be the relative .tree-ring path.")
    _validate_command_protocol(value.get("command_protocol"))


def _validate_command_protocol(value: Any) -> None:
    if not isinstance(value, dict):
        raise _BindingError("The Agent Zero command protocol must be an object.")
    if value.get("command") != "tree-ring":
        raise _BindingError("The Agent Zero command protocol has an unsupported command.")
    if value.get("arguments") != _AGENT_ZERO_ARGUMENTS:
        raise _BindingError("The Agent Zero command protocol has unsupported arguments.")
    if value.get("stdin") != "json" or value.get("stdout") != "json":
        raise _BindingError("The Agent Zero command protocol must use JSON input and output.")


def _require_version(
    value: dict[str, Any], field: str, expected: int, label: str
) -> int:
    version = value.get(field)
    if not _is_version(version) or version != expected:
        raise _BindingError(f"The activation {label} version is unsupported.")
    return version


def _require_identifier(value: dict[str, Any], field: str, label: str) -> str:
    identifier = value.get(field)
    if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 200:
        raise _BindingError(f"The activation {label} is invalid.")
    return identifier


def _require_fingerprint(value: dict[str, Any], field: str) -> str:
    fingerprint = value.get(field)
    if not isinstance(fingerprint, str) or _SHA256.fullmatch(fingerprint) is None:
        raise _BindingError("The project root fingerprint must be a SHA-256 hex digest.")
    return fingerprint


def _is_version(value: Any) -> bool:
    return type(value) is int


def _is_under(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def _is_direct_child(root: Path, target: Path, name: str) -> bool:
    return target.name == name and target.parent == root
