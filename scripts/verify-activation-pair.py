#!/usr/bin/env python3
"""Verify this checkout's actual plugin contract against one candidate CLI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    plugin_root = Path(__file__).resolve().parents[1]
    descriptor = plugin_root / "activation-capability.json"
    capability = json.loads(descriptor.read_text(encoding="utf-8"))
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("TREE_RING_")
    }
    version = subprocess.run(
        [str(binary), "--version"], check=True, text=True, capture_output=True,
        env=environment,
    ).stdout.strip()
    match = re.fullmatch(r"tree-ring (\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise RuntimeError(f"Expected a release CLI version, got {version!r}")
    actual = tuple(map(int, match.groups()))
    minimum = tuple(map(int, capability["tree_ring_version"]["min"].split(".")))
    minor = tuple(map(int, capability["tree_ring_version"]["minor"].split(".")))
    if actual < minimum or actual[:2] != minor:
        raise RuntimeError("Candidate CLI does not satisfy this plugin's runtime boundary")

    environment["TREE_RING_AGENT_ZERO_PLUGIN_MANIFEST"] = str(descriptor)
    with tempfile.TemporaryDirectory(prefix="tree-ring-activation-pair-") as temporary:
        project = Path(temporary) / "project"
        project.mkdir()
        root = project / ".tree-ring"

        def run(*command: str, payload: dict | None = None) -> dict:
            result = subprocess.run(
                [str(binary), "--root", str(root), "--json", *command],
                check=True, text=True, capture_output=True, cwd=project,
                env=environment,
                input=None if payload is None else json.dumps(payload),
            )
            return json.loads(result.stdout)

        initialized = run("init")
        if initialized.get("ok") is not True:
            raise RuntimeError("Project initialization failed")
        manifest = json.loads((root / "activation.json").read_text(encoding="utf-8"))
        before = run("integrations", "status", "--source-root", str(project))
        binding = next(item for item in before["integrations"] if item["id"] == "agent-zero")
        if binding["state"] != "configured-awaiting-proof":
            raise RuntimeError(f"Current plugin contract was not accepted: {binding['state']}")
        proof = run(
            "integrations", "preflight", "--harness", "agent-zero",
            "--input-json-stdin", "--context-format", "json",
            payload={"agent_profile": "agent-zero-package-smoke",
                     "workflow_id": "release-verification", "session_id": "activation-pair"},
        )
        receipt = proof.get("receipt", {})
        if (
            proof.get("state") != "active"
            or receipt.get("harness_id") != "agent-zero"
            or receipt.get("store_id") != manifest["store_id"]
            or receipt.get("project_root_fingerprint") != manifest["project_root_fingerprint"]
        ):
            raise RuntimeError("Preflight did not produce a matching active receipt")
        after = run("integrations", "status", "--source-root", str(project))
        binding = next(item for item in after["integrations"] if item["id"] == "agent-zero")
        if binding["state"] != "active":
            raise RuntimeError("Persisted receipt did not establish active status")
    print(f"Agent Zero {capability['plugin_version']} + {version}: activation receipt verified")


if __name__ == "__main__":
    main()
