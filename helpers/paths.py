from __future__ import annotations

import os
from pathlib import Path
from typing import Any


PLUGIN_NAME = "tree_ring_memory"
PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[2]
DEFAULT_MEMORY_ROOT = Path("/a0/usr/memory/tree_ring_memory")


def plugin_path(*parts: str) -> Path:
    return PLUGIN_DIR.joinpath(*parts)


def memory_root(config: dict[str, Any] | None = None) -> Path:
    storage = (config or {}).get("storage") or {}
    configured = storage.get("root") or storage.get("data_dir")
    env_root = os.environ.get("TREE_RING_MEMORY_ROOT") or os.environ.get("TREE_RING_MEMORY_DATA_DIR")
    return Path(str(env_root or configured or DEFAULT_MEMORY_ROOT)).expanduser()


def canonical_sqlite_path(config: dict[str, Any] | None = None) -> Path:
    return memory_root(config) / "memory.sqlite"


def legacy_sqlite_path(config: dict[str, Any] | None = None) -> Path:
    configured = ((config or {}).get("storage") or {}).get("legacy_sqlite_path")
    return Path(str(configured)).expanduser() if configured else memory_root(config) / "indexes" / "memory.sqlite"


def migration_marker_path(config: dict[str, Any] | None = None) -> Path:
    return memory_root(config) / "migrations" / "legacy-python-v1.json"


def ensure_memory_dirs(config: dict[str, Any] | None = None) -> Path:
    root = memory_root(config)
    root.mkdir(parents=True, exist_ok=True)
    for relative in ("exports", "imports", "migrations"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def assert_under(base: Path, target: Path) -> Path:
    base_resolved = base.expanduser().resolve()
    target_resolved = target.expanduser().resolve()
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"Unsafe path outside {base_resolved}: {target}") from exc
    return target_resolved


def safe_output_path(config: dict[str, Any], requested: str | None, default_name: str) -> Path:
    export_root = ensure_memory_dirs(config) / "exports"
    target = Path(requested).expanduser() if requested else export_root / default_name
    if not target.is_absolute():
        target = export_root / target
    target = assert_under(export_root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def safe_import_path(config: dict[str, Any], requested: str) -> Path:
    if not requested:
        raise ValueError("Import path is required")
    root = ensure_memory_dirs(config)
    target = Path(requested).expanduser()
    if not target.is_absolute():
        target = root / "imports" / target
    allowed_roots = [root / "imports", root / "exports", allowed_project_root(config)]
    for allowed in allowed_roots:
        try:
            resolved = assert_under(allowed, target)
            if not resolved.is_file():
                raise ValueError(f"Import file does not exist: {resolved}")
            return resolved
        except ValueError:
            continue
    raise ValueError("Import path must be inside Tree Ring Memory imports/exports or the Agent Zero project root")


def allowed_project_root(config: dict[str, Any] | None = None) -> Path:
    configured = ((config or {}).get("scope") or {}).get("allowed_project_root")
    return Path(str(configured)).expanduser().resolve() if configured else REPO_ROOT.resolve()


def safe_project_root(config: dict[str, Any], requested: str | None) -> Path:
    allowed = allowed_project_root(config)
    target = Path(requested).expanduser() if requested else allowed
    if not target.is_absolute():
        target = allowed / target
    resolved = assert_under(allowed, target)
    if not resolved.exists():
        raise ValueError(f"Project source root does not exist: {resolved}")
    return resolved


def trusted_migration_path(config: dict[str, Any], target: Path) -> Path:
    return assert_under(ensure_memory_dirs(config) / "migrations", target)
