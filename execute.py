from __future__ import annotations

import argparse
import json
import shutil
import sys
from typing import Any

from usr.plugins.tree_ring_memory.helpers import paths
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli, TreeRingCliError
from usr.plugins.tree_ring_memory.helpers.config import load_config
from usr.plugins.tree_ring_memory.helpers.legacy import LegacyMigrationError, LegacyMigrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tree Ring Memory v0.12 Agent Zero bridge maintenance")
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=[
            "status",
            "init",
            "migrate",
            "audit",
            "maintain",
            "repair-fts",
            "export",
            "import-preview",
            "integrations",
            "purge",
        ],
    )
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--path", default="")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--audit-type", default="all")
    parser.add_argument("--project", default="")
    parser.add_argument("--include-sensitive", action="store_true")
    parser.add_argument("--include-superseded", action="store_true")
    parser.add_argument("--apply-expired", action="store_true")
    parser.add_argument("--apply-secret-redactions", action="store_true")
    args = parser.parse_args(argv)

    config = load_config()
    bridge = TreeRingCli(config)
    try:
        if args.command == "status":
            result = bridge.status()
            _print(result)
            return 0 if result.get("ok") else 1
        if args.command == "init":
            result = bridge.init()
        elif args.command == "migrate":
            result = LegacyMigrator(config, cli=bridge).migrate(confirm=args.confirm, force=args.force)
        elif args.command == "audit":
            result = bridge.audit(args.audit_type)
        elif args.command == "maintain":
            result = bridge.maintain(
                project=args.project or None,
                include_superseded=args.include_superseded,
                apply_expired=args.apply_expired,
                apply_secret_redactions=args.apply_secret_redactions,
            )
        elif args.command == "repair-fts":
            result = bridge.maintain(repair_fts=True)
        elif args.command == "export":
            result = bridge.export_to_file(
                output_path=args.path or None,
                include_sensitive=args.include_sensitive,
                include_superseded=args.include_superseded,
            )
        elif args.command == "import-preview":
            if not args.path:
                raise ValueError("--path is required for import-preview")
            result = bridge.import_file(args.path, dry_run=True)
        elif args.command == "integrations":
            result = bridge.integrations_scan(source_root=args.source_root or None)
        elif args.command == "purge":
            result = _purge(config, confirm=args.confirm)
        else:
            raise ValueError(f"Unsupported command: {args.command}")
    except (TreeRingCliError, LegacyMigrationError, ValueError, OSError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2
    _print({"ok": True, "data": result})
    return 0


def _purge(config: dict[str, Any], *, confirm: bool) -> dict[str, Any]:
    root = paths.memory_root(config).resolve()
    if not confirm:
        raise ValueError("Refusing to purge without --confirm.")
    if root in {root.parent, paths.REPO_ROOT.resolve()} or len(root.parts) < 4:
        raise ValueError(f"Refusing to purge unsafe memory root: {root}")
    if root.exists():
        shutil.rmtree(root)
    return {"purged": str(root)}


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
