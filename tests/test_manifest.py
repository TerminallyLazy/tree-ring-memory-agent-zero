from __future__ import annotations

import hashlib
import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_declares_rust_bridge_generation():
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    defaults = yaml.safe_load((ROOT / "default_config.yaml").read_text(encoding="utf-8"))

    assert manifest["name"] == "tree_ring_memory"
    assert manifest["version"] == "2.1.0"
    assert defaults["cli"]["required_version"] == "0.12.0"
    assert defaults["storage"]["root"].endswith("/tree_ring_memory")
    assert defaults["storage"]["legacy_sqlite_path"].endswith("/indexes/memory.sqlite")


def test_plugin_uses_hooks_without_manual_execute_script():
    assert (ROOT / "hooks.py").is_file()
    assert not (ROOT / "execute.py").exists()


def test_bundled_linux_binaries_match_declared_checksums():
    checksum_lines = (ROOT / "bin" / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksums = {path: digest for digest, path in (line.split(maxsplit=1) for line in checksum_lines)}

    for target in ("linux-aarch64", "linux-x86_64"):
        relative = f"bin/{target}/tree-ring"
        binary = ROOT / relative
        assert binary.is_file()
        assert os.access(binary, os.X_OK)
        with binary.open("rb") as handle:
            assert hashlib.file_digest(handle, "sha256").hexdigest() == checksums[relative]
