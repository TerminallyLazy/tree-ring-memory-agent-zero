from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from usr.plugins.tree_ring_memory.helpers import paths
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli
from usr.plugins.tree_ring_memory.helpers.config import DEFAULT_CONFIG, load_config
from usr.plugins.tree_ring_memory.helpers.legacy import LegacyMigrator


_BOOTSTRAP_LOCK = Lock()
_BOOTSTRAPPED_ROOTS: set[Path] = set()


def bootstrap_runtime(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prepare a compatible store without crossing the offline upgrade gate."""

    resolved = load_config(config)
    paths.ensure_memory_dirs(resolved)
    bridge = TreeRingCli(resolved)
    initial_status = bridge.status()
    if initial_status.get("upgrade_required"):
        return {
            "ok": True,
            "ready": False,
            "upgrade_required": True,
            "status": initial_status,
            "message": (
                "The existing Tree Ring store was not opened. Stop every Tree Ring process, "
                "create the verified pre-v0.13 backup, and explicitly apply schema v3."
            ),
        }
    if not initial_status.get("ok"):
        detail = str(initial_status.get("error") or "tree-ring runtime is unavailable")
        raise RuntimeError(f"Tree Ring Memory automatic setup failed: {detail}")

    initialized_now = not bool(initial_status.get("initialized"))
    init_result = bridge.init() if initialized_now else None
    migration = None
    if initial_status.get("legacy_migration_pending"):
        policy = bridge.policy_status()
        migration = LegacyMigrator(resolved, cli=bridge).migrate(
            confirm=str(policy.get("mode") or "").lower() == "open"
        )

    audit = bridge.audit("all")
    final_status = bridge.status()
    if not final_status.get("ok") or not final_status.get("initialized"):
        detail = str(final_status.get("error") or "the Rust-owned store did not initialize")
        raise RuntimeError(f"Tree Ring Memory automatic setup failed: {detail}")

    return {
        "ok": True,
        "ready": True,
        "initialized_now": initialized_now,
        "init": init_result,
        "migration": migration,
        "audit": audit,
        "status": final_status,
    }


def _ensure_auto_bootstrap(config: dict[str, Any]) -> dict[str, Any] | None:
    root = paths.memory_root(config).expanduser().resolve()
    if root in _BOOTSTRAPPED_ROOTS:
        return None
    with _BOOTSTRAP_LOCK:
        if root in _BOOTSTRAPPED_ROOTS:
            return None
        report = bootstrap_runtime(config)
        _BOOTSTRAPPED_ROOTS.add(root)
        return report


def install(**kwargs: Any) -> bool:
    """Automatically prepare the runtime after install and update.

    The packaged binary is selected locally; legacy migration is copy-only and
    preserves the Python-v1 database as read-only recovery input.
    """

    del kwargs
    _ensure_auto_bootstrap(load_config())
    return True


def pre_update() -> bool:
    config = load_config()
    bridge = TreeRingCli(config)
    status = bridge.status()
    if status.get("ok") and status.get("initialized"):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        bridge.export_to_file(output_path=f"pre-update-{stamp}.jsonl")
    return True


def uninstall() -> bool:
    root = paths.ensure_memory_dirs(load_config())
    note = root / "UNINSTALL_NOTE.md"
    note.write_text(
        "# Tree Ring Memory Preserved Data\n\n"
        "The Agent Zero bridge was removed or disabled, but the Rust-owned and legacy memory stores were preserved.\n"
        "Use the explicit purge command only when you intend to delete both stores.\n",
        encoding="utf-8",
    )
    return True


def get_default_plugin_config(default=None, **kwargs):
    del kwargs
    return load_config(default if isinstance(default, dict) else DEFAULT_CONFIG)


def get_plugin_config(default=None, **kwargs):
    del kwargs
    config = load_config(default if isinstance(default, dict) else None)
    _ensure_auto_bootstrap(config)
    return config
