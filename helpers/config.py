from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


SUPPORTED_TREE_RING_VERSION = "0.13.0"
DEFAULT_MEMORY_ROOT = "/a0/usr/memory/tree_ring_memory"
LOCAL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "cli": {
        "binary": "tree-ring",
        "required_version": SUPPORTED_TREE_RING_VERSION,
        "timeout_seconds": 30,
    },
    "storage": {
        "root": DEFAULT_MEMORY_ROOT,
        "legacy_sqlite_path": f"{DEFAULT_MEMORY_ROOT}/indexes/memory.sqlite",
    },
    "scope": {
        "default_project_scope": "current_project",
        "allow_global": True,
        "allow_cross_project_recall": False,
    },
    "coordination": {
        "coordinator_profiles": [],
    },
    "recall": {
        "max_results_default": 8,
        "bridge_scan_limit": 100,
    },
    "privacy": {
        "include_sensitive_in_recall_by_default": False,
        "export_requires_confirmation": True,
    },
    "developer": {
        "show_ranking_scores": False,
    },
}


def merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load bridge config while accepting the Python-v1 storage keys.

    ``TREE_RING_MEMORY_DATA_DIR`` remains supported because the upstream
    certification harness already uses it. New deployments should prefer
    ``TREE_RING_MEMORY_ROOT`` and ``TREE_RING_MEMORY_CLI``.
    """

    supplied = copy.deepcopy(_read_local_config() if config is None else config)
    loaded = merge(DEFAULT_CONFIG, supplied)
    supplied_storage = supplied.get("storage") if isinstance(supplied.get("storage"), dict) else {}
    storage = loaded.setdefault("storage", {})

    env_root = os.environ.get("TREE_RING_MEMORY_ROOT") or os.environ.get("TREE_RING_MEMORY_DATA_DIR")
    if env_root:
        root = env_root
    elif supplied_storage.get("root"):
        root = supplied_storage["root"]
    elif supplied_storage.get("data_dir"):
        root = supplied_storage["data_dir"]
    else:
        root = storage.get("root") or DEFAULT_MEMORY_ROOT
    root_path = Path(str(root)).expanduser()
    storage["root"] = str(root_path)

    # A root supplied by the certification/runtime environment is authoritative
    # for both the Rust store and the colocated Python-v1 migration source.
    # Otherwise a user-supplied legacy path remains valid for nonstandard
    # installations.
    explicit_legacy = None if env_root else (
        supplied_storage.get("legacy_sqlite_path") or supplied_storage.get("sqlite_path")
    )
    storage["legacy_sqlite_path"] = str(
        Path(str(explicit_legacy)).expanduser()
        if explicit_legacy
        else root_path / "indexes" / "memory.sqlite"
    )

    cli = loaded.setdefault("cli", {})
    if os.environ.get("TREE_RING_MEMORY_CLI"):
        cli["binary"] = os.environ["TREE_RING_MEMORY_CLI"]
    cli["required_version"] = SUPPORTED_TREE_RING_VERSION
    cli["timeout_seconds"] = _bounded_int(cli.get("timeout_seconds"), default=30, minimum=1, maximum=300)

    recall = loaded.setdefault("recall", {})
    recall["max_results_default"] = _bounded_int(
        recall.get("max_results_default"), default=8, minimum=1, maximum=100
    )
    recall["bridge_scan_limit"] = _bounded_int(
        recall.get("bridge_scan_limit"), default=100, minimum=8, maximum=1000
    )

    coordination = loaded.setdefault("coordination", {})
    profiles = coordination.get("coordinator_profiles")
    if isinstance(profiles, str):
        profiles = [profiles]
    coordination["coordinator_profiles"] = [
        str(profile).strip()
        for profile in (profiles if isinstance(profiles, list) else [])
        if str(profile).strip()
    ]

    if os.environ.get("TREE_RING_MEMORY_PROJECT_ROOT"):
        loaded.setdefault("scope", {})["allowed_project_root"] = os.environ[
            "TREE_RING_MEMORY_PROJECT_ROOT"
        ]
    return loaded


def _read_local_config() -> dict[str, Any]:
    try:
        value = json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
