from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CORE_RELEASE_COMMIT = "33e42915585fba4e434ac0c35ea1dbb62d96c9b9"
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
    capability = json.loads((ROOT / "activation-capability.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "tree_ring_memory"
    assert manifest["version"] == "3.3.0"
    assert defaults["cli"]["required_version"] == "0.15.3"
    assert defaults["coordination"]["coordinator_profiles"] == []
    assert defaults["storage"]["root"].endswith("/tree_ring_memory")
    assert defaults["storage"]["legacy_sqlite_path"].endswith("/indexes/memory.sqlite")
    assert capability == {
        "schema_version": 1,
        "kind": "tree-ring-agent-zero-plugin-capability",
        "plugin_id": "tree_ring_memory",
        "plugin_version": "3.3.0",
        "activation_protocol_version": 1,
        "tree_ring_version": {"min": "0.15.3", "minor": "0.15"},
        "enabled": True,
    }


def test_plugin_uses_hooks_without_manual_execute_script():
    assert (ROOT / "hooks.py").is_file()
    assert not (ROOT / "execute.py").exists()


def test_release_docs_match_v0153_bundle():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    bundled = (ROOT / "bin" / "README.md").read_text(encoding="utf-8")

    assert "Plugin `3.3.0` targets the released Tree Ring `0.15`" in readme
    assert "supports `tree-ring` `0.15.3` through `0.15.x`" in readme
    assert "Activate this project" in readme
    assert "session-specific identity" in readme
    assert "does not initialize the legacy global memory root" in readme
    assert "Plugin `3.3.0` requires Tree Ring `0.15.3` through `0.15.x`" in bundled
    assert "immutable Tree Ring Memory tag `v0.15.3`" in bundled


def test_v0153_bundle_workflow_is_manual_and_resolves_the_release_tag_at_runtime():
    workflow = (ROOT / ".github" / "workflows" / "build-bundled-binaries.yml").read_text(
        encoding="utf-8"
    )
    stager = (ROOT / "scripts" / "stage-v0153-bundled-binaries.sh").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "TREE_RING_RELEASE_TAG: v0.15.3" in workflow
    assert "TREE_RING_RELEASE_VERSION: 0.15.3" in workflow
    assert 'ref: ${{ env.TREE_RING_RELEASE_TAG }}' in workflow
    assert 'tag_commit="$(git rev-list -n 1 "$TREE_RING_RELEASE_TAG")"' in workflow
    assert 'echo "source_commit=$(git rev-parse HEAD)"' in workflow
    assert "--test harness_activation_acceptance" in workflow
    assert "tree-ring-v0.15.3-${{ matrix.target }}" in workflow
    assert "v0.13.0" not in workflow
    assert "EXPECTED_TAG=v0.15.3" in stager
    assert "EXPECTED_VERSION='tree-ring 0.15.3'" in stager
    assert "artifacts were built from different Tree Ring commits" in stager


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


def test_bundled_linux_binaries_have_v0153_native_build_provenance():
    expected = {
        "linux-aarch64": ("ubuntu-24.04-arm", "aarch64"),
        "linux-x86_64": ("ubuntu-24.04", "x86_64"),
    }

    for target, (runner, machine) in expected.items():
        provenance = _read_provenance(ROOT / "bin" / target / "PROVENANCE.txt")
        assert provenance["source_repository"] == (
            "https://github.com/TerminallyLazy/Tree-Ring-Memory"
        )
        assert provenance["source_tag"] == "v0.15.3"
        assert provenance["source_commit"] == CORE_RELEASE_COMMIT
        assert provenance["build_image"] == BOOKWORM_IMAGE
        assert provenance["runner"] == runner
        assert provenance["machine"] == machine
        assert provenance["binary_version"] == "tree-ring 0.15.3"
        required_glibc = tuple(
            int(component)
            for component in provenance["maximum_required_glibc"]
            .removeprefix("GLIBC_")
            .split(".")
        )
        assert required_glibc <= (2, 36)
