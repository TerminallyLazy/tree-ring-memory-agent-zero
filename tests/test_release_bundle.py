from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGER = ROOT / "scripts" / "stage-v014-bundled-binaries.sh"
BOOKWORM_IMAGE = (
    "rust:1.95-bookworm"
    "@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1"
)


def _artifact(
    root: Path,
    *,
    runner: str,
    machine: str,
    source_commit: str,
) -> Path:
    root.mkdir()
    binary = root / "tree-ring"
    binary.write_text("#!/bin/sh\necho 'tree-ring 0.14.0'\n", encoding="utf-8")
    binary.chmod(0o755)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    (root / "SHA256SUM").write_text(f"{digest}  tree-ring\n", encoding="utf-8")
    (root / "PROVENANCE.txt").write_text(
        "\n".join(
            (
                "source_repository=https://github.com/TerminallyLazy/Tree-Ring-Memory",
                "source_tag=v0.14.0",
                f"source_commit={source_commit}",
                f"build_image={BOOKWORM_IMAGE}",
                f"runner={runner}",
                f"machine={machine}",
                "rustc=rustc fixture",
                "cargo=cargo fixture",
                "glibc=ldd fixture",
                "maximum_required_glibc=GLIBC_2.36",
                "binary_version=tree-ring 0.14.0",
                "",
            )
        ),
        encoding="utf-8",
    )
    return root


def _plugin_copy(tmp_path: Path) -> Path:
    plugin = tmp_path / "plugin"
    script_dir = plugin / "scripts"
    script_dir.mkdir(parents=True)
    shutil.copy2(STAGER, script_dir / STAGER.name)
    (plugin / "bin" / "linux-x86_64").mkdir(parents=True)
    (plugin / "bin" / "linux-aarch64").mkdir(parents=True)
    (plugin / "bin" / "linux-x86_64" / "tree-ring").write_bytes(b"old-x86")
    (plugin / "bin" / "linux-aarch64" / "tree-ring").write_bytes(b"old-arm")
    return plugin


def test_release_stager_requires_matched_verified_v014_artifacts(tmp_path):
    plugin = _plugin_copy(tmp_path)
    source_commit = "a" * 40
    x86 = _artifact(
        tmp_path / "x86",
        runner="ubuntu-24.04",
        machine="x86_64",
        source_commit=source_commit,
    )
    arm = _artifact(
        tmp_path / "arm",
        runner="ubuntu-24.04-arm",
        machine="aarch64",
        source_commit=source_commit,
    )

    result = subprocess.run(
        ["sh", str(plugin / "scripts" / STAGER.name), str(x86), str(arm)],
        capture_output=True,
        check=True,
        text=True,
    )

    assert source_commit in result.stdout
    assert (plugin / "bin" / "linux-x86_64" / "tree-ring").read_bytes() == (
        x86 / "tree-ring"
    ).read_bytes()
    assert (plugin / "bin" / "linux-aarch64" / "tree-ring").read_bytes() == (
        arm / "tree-ring"
    ).read_bytes()
    expected_checksums = {
        f"bin/linux-aarch64/tree-ring": hashlib.sha256((arm / "tree-ring").read_bytes()).hexdigest(),
        f"bin/linux-x86_64/tree-ring": hashlib.sha256((x86 / "tree-ring").read_bytes()).hexdigest(),
    }
    checksums = {
        path: digest
        for digest, path in (
            line.split(maxsplit=1)
            for line in (plugin / "bin" / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        )
    }
    assert checksums == expected_checksums


def test_release_stager_refuses_artifacts_from_different_core_commits(tmp_path):
    plugin = _plugin_copy(tmp_path)
    x86 = _artifact(
        tmp_path / "x86",
        runner="ubuntu-24.04",
        machine="x86_64",
        source_commit="a" * 40,
    )
    arm = _artifact(
        tmp_path / "arm",
        runner="ubuntu-24.04-arm",
        machine="aarch64",
        source_commit="b" * 40,
    )

    result = subprocess.run(
        ["sh", str(plugin / "scripts" / STAGER.name), str(x86), str(arm)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "different Tree Ring commits" in result.stderr
    assert (plugin / "bin" / "linux-x86_64" / "tree-ring").read_bytes() == b"old-x86"
    assert (plugin / "bin" / "linux-aarch64" / "tree-ring").read_bytes() == b"old-arm"
