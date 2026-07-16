from __future__ import annotations

from datetime import UTC, datetime

from usr.plugins.tree_ring_memory.helpers import paths
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli
from usr.plugins.tree_ring_memory.helpers.config import DEFAULT_CONFIG, load_config


def install() -> bool:
    """Create only plugin-owned directories.

    Binary installation and legacy import stay explicit because they download
    or copy executable code and write durable user memory respectively.
    """

    paths.ensure_memory_dirs(load_config())
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
    return load_config(default if isinstance(default, dict) else None)
