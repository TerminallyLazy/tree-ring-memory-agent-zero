from __future__ import annotations

import json
from typing import Any

from helpers.tool import Response
from helpers import plugins as framework_plugins
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli, TreeRingCliError
from usr.plugins.tree_ring_memory.helpers.config import load_config
from usr.plugins.tree_ring_memory.helpers.legacy import LegacyMigrationError


def bridge_and_config(agent: Any = None) -> tuple[TreeRingCli, dict[str, Any]]:
    configured = framework_plugins.get_plugin_config("tree_ring_memory", agent=agent) or {}
    config = load_config(configured if isinstance(configured, dict) else {})
    return TreeRingCli(config), config


def tool_response(payload: dict[str, Any]) -> Response:
    return Response(
        message=json.dumps(payload, indent=2, sort_keys=True),
        break_loop=False,
        additional={"tree_ring_memory": payload},
    )


def tool_success(data: Any, message: str) -> Response:
    return tool_response({"ok": True, "message": message, "data": data, "warnings": [], "error": None})


def tool_error(error: Exception | str) -> Response:
    return tool_response({"ok": False, "data": {}, "warnings": [], "error": str(error)})


BRIDGE_ERRORS = (TreeRingCliError, LegacyMigrationError, ValueError, OSError)
