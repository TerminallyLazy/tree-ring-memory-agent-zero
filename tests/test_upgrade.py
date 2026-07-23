from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

from usr.plugins.tree_ring_memory.helpers import upgrade
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli
from usr.plugins.tree_ring_memory.helpers.config import load_config


def configured(root: Path, binary: Path) -> dict:
    return load_config(
        {
            "cli": {
                "binary": str(binary),
                "required_version": "0.13.0",
                "timeout_seconds": 10,
            },
            "storage": {"root": str(root)},
            "scope": {"allowed_project_root": str(root.parent)},
        }
    )


def executable(tmp_path: Path) -> Path:
    binary = tmp_path / "tree-ring"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def create_v2_store(root: Path) -> Path:
    root.mkdir(parents=True)
    database = root / "memory.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE memories (id TEXT PRIMARY KEY, summary TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO memories (id, summary) VALUES ('mem_legacy', 'keep me')"
        )
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    finally:
        connection.close()
    return database


def completed(command: list[str], stdout: str):
    return subprocess.CompletedProcess(command, 0, stdout, "")


def test_status_preflights_v2_without_opening_or_migrating_store(tmp_path):
    root = tmp_path / "memory"
    database = create_v2_store(root)
    original = database.read_bytes()
    binary = executable(tmp_path)
    commands: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        commands.append(command)
        return completed(command, "tree-ring 0.13.0\n")

    status = TreeRingCli(configured(root, binary), runner=runner).status()

    assert status["ok"] is False
    assert status["runtime_ok"] is True
    assert status["upgrade_required"] is True
    assert status["schema_version"] == 2
    assert len(commands) == 1
    assert commands[0][-1] == "--version"
    assert database.read_bytes() == original
    assert not (root / "migrations").exists()


def test_upgrade_backup_is_exact_private_and_integrity_verified(tmp_path):
    root = tmp_path / "memory"
    database = create_v2_store(root)
    binary = executable(tmp_path)

    def runner(command, **kwargs):
        del kwargs
        return completed(command, "tree-ring 0.13.0\n")

    bridge = TreeRingCli(configured(root, binary), runner=runner)
    with pytest.raises(upgrade.SchemaUpgradeError, match="Stop every Tree Ring"):
        bridge.prepare_schema_upgrade(confirm_offline=False)

    report = bridge.prepare_schema_upgrade(confirm_offline=True)
    backup = Path(report["backup_path"])

    assert report["upgrade_prepared"] is True
    assert report["schema_version"] == 2
    assert report["memory_count"] == 1
    assert backup.read_bytes() == database.read_bytes()
    assert report["backup_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    marker = root / "migrations" / "schema-v3-upgrade.json"
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    assert marker_data["offline_confirmed"] is True
    assert marker_data["completed_at"] is None


def test_apply_upgrade_requires_unchanged_verified_backup(tmp_path):
    root = tmp_path / "memory"
    database = create_v2_store(root)
    binary = executable(tmp_path)
    config = configured(root, binary)

    def runner(command, **kwargs):
        del kwargs
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        if "init" in command:
            connection = sqlite3.connect(database)
            try:
                connection.execute("PRAGMA user_version=3")
                connection.commit()
            finally:
                connection.close()
            return completed(command, '{"ok":true}')
        if "audit" in command:
            return completed(command, '{"memory_count":1,"finding_count":0}')
        raise AssertionError(command)

    bridge = TreeRingCli(config, runner=runner)
    bridge.prepare_schema_upgrade(confirm_offline=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO memories (id, summary) VALUES ('mem_changed', 'changed')"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(upgrade.SchemaUpgradeError, match="changed after"):
        bridge.apply_schema_upgrade(confirm_offline=True)


def test_apply_upgrade_marks_verified_backup_complete(tmp_path):
    root = tmp_path / "memory"
    database = create_v2_store(root)
    binary = executable(tmp_path)
    config = configured(root, binary)

    def runner(command, **kwargs):
        environment = kwargs["env"]
        assert "TREE_RING_COORDINATOR_TOKEN" not in environment
        if "--version" in command:
            return completed(command, "tree-ring 0.13.0\n")
        if "init" in command:
            connection = sqlite3.connect(database)
            try:
                connection.execute("PRAGMA user_version=3")
                connection.commit()
            finally:
                connection.close()
            return completed(command, '{"ok":true}')
        if "audit" in command:
            return completed(command, '{"memory_count":1,"finding_count":0}')
        raise AssertionError(command)

    bridge = TreeRingCli(config, runner=runner)
    prepared = bridge.prepare_schema_upgrade(confirm_offline=True)
    result = bridge.apply_schema_upgrade(confirm_offline=True)

    assert result["ok"] is True
    assert result["status"]["schema_version"] == 3
    assert Path(prepared["backup_path"]).is_file()
    marker = json.loads(
        (root / "migrations" / "schema-v3-upgrade.json").read_text(
            encoding="utf-8"
        )
    )
    assert marker["completed_at"]
    assert marker["tree_ring_version"] == "0.13.0"
