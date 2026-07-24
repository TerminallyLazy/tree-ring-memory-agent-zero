from __future__ import annotations

import hashlib
import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CORE_RELEASE_COMMIT = "167bc655e001112ff5593d7af0984b3e8689ea1a"
BOOKWORM_IMAGE = (
    "rust:1.95-bookworm"
    "@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1"
)


def _read_provenance(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", maxsplit=1)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def test_manifest_declares_rust_bridge_generation():
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    defaults = yaml.safe_load((ROOT / "default_config.yaml").read_text(encoding="utf-8"))

    assert manifest["name"] == "tree_ring_memory"
    assert manifest["version"] == "3.0.1"
    assert defaults["cli"]["required_version"] == "0.13.0"
    assert defaults["coordination"]["coordinator_profiles"] == []
    assert defaults["storage"]["root"].endswith("/tree_ring_memory")
    assert defaults["storage"]["legacy_sqlite_path"].endswith("/indexes/memory.sqlite")


def test_plugin_uses_hooks_without_manual_execute_script():
    assert (ROOT / "hooks.py").is_file()
    assert not (ROOT / "execute.py").exists()


def test_bundled_linux_binaries_match_declared_checksums():
    checksum_lines = (ROOT / "bin" / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksums = {path: digest for digest, path in (line.split(maxsplit=1) for line in checksum_lines)}
    assert set(checksums) == {
        "bin/linux-aarch64/tree-ring",
        "bin/linux-x86_64/tree-ring",
    }

    for target in ("linux-aarch64", "linux-x86_64"):
        relative = f"bin/{target}/tree-ring"
        binary = ROOT / relative
        assert binary.is_file()
        assert os.access(binary, os.X_OK)
        with binary.open("rb") as handle:
            assert hashlib.file_digest(handle, "sha256").hexdigest() == checksums[relative]


def test_bundled_linux_binaries_have_v013_native_build_provenance():
    expected = {
        "linux-aarch64": ("ubuntu-24.04-arm", "aarch64"),
        "linux-x86_64": ("ubuntu-24.04", "x86_64"),
    }

    for target, (runner, machine) in expected.items():
        provenance = _read_provenance(ROOT / "bin" / target / "PROVENANCE.txt")
        assert provenance["source_repository"] == (
            "https://github.com/TerminallyLazy/Tree-Ring-Memory"
        )
        assert provenance["source_tag"] == "v0.13.0"
        assert provenance["source_commit"] == CORE_RELEASE_COMMIT
        assert provenance["build_image"] == BOOKWORM_IMAGE
        assert provenance["runner"] == runner
        assert provenance["machine"] == machine
        assert provenance["binary_version"] == "tree-ring 0.13.0"
        required_glibc = tuple(
            int(component)
            for component in provenance["maximum_required_glibc"]
            .removeprefix("GLIBC_")
            .split(".")
        )
        assert required_glibc <= (2, 36)
