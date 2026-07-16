from __future__ import annotations

from pathlib import Path

import pytest

from usr.plugins.tree_ring_memory.helpers import paths
from usr.plugins.tree_ring_memory.helpers import config as config_module
from usr.plugins.tree_ring_memory.helpers.config import load_config


def test_load_config_reads_plugin_local_runtime_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("TREE_RING_MEMORY_CLI", raising=False)
    monkeypatch.delenv("TREE_RING_MEMORY_ROOT", raising=False)
    monkeypatch.delenv("TREE_RING_MEMORY_DATA_DIR", raising=False)
    local_config = tmp_path / "config.json"
    local_config.write_text(
        '{"cli":{"binary":"/opt/tree-ring"},"storage":{"root":"/tmp/tree-ring-root"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "LOCAL_CONFIG_PATH", local_config)

    config = load_config()

    assert config["cli"]["binary"] == "/opt/tree-ring"
    assert config["storage"]["root"] == "/tmp/tree-ring-root"
    assert config["cli"]["required_version"] == "0.12.0"


def test_legacy_storage_keys_map_to_rust_root(tmp_path):
    old_sqlite = tmp_path / "indexes" / "memory.sqlite"

    config = load_config(
        {"storage": {"data_dir": str(tmp_path), "sqlite_path": str(old_sqlite)}}
    )

    assert config["storage"]["root"] == str(tmp_path)
    assert config["storage"]["legacy_sqlite_path"] == str(old_sqlite)
    assert paths.canonical_sqlite_path(config) == tmp_path / "memory.sqlite"


def test_data_dir_environment_remains_certification_compatible(tmp_path, monkeypatch):
    monkeypatch.setenv("TREE_RING_MEMORY_DATA_DIR", str(tmp_path))

    config = load_config()

    assert config["storage"]["root"] == str(tmp_path)
    assert config["storage"]["legacy_sqlite_path"] == str(tmp_path / "indexes" / "memory.sqlite")


def test_output_and_project_paths_fail_closed(tmp_path):
    root = tmp_path / "memory"
    project = tmp_path / "project"
    project.mkdir()
    config = load_config(
        {"storage": {"root": str(root)}, "scope": {"allowed_project_root": str(project)}}
    )

    with pytest.raises(ValueError, match="Unsafe path"):
        paths.safe_output_path(config, str(tmp_path / "outside.jsonl"), "unused.jsonl")
    with pytest.raises(ValueError, match="Unsafe path"):
        paths.safe_project_root(config, str(tmp_path / "outside"))
