from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.helpers.values import parse_bool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class Consolidate(Tool):
    async def execute(
        self,
        period_type: str = "daily",
        period_key: str = "",
        project: str = "",
        dry_run: bool = False,
        force: bool = False,
        **kwargs,
    ):
        del kwargs
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            data = bridge.consolidate(
                period_type=period_type,
                period_key=period_key or None,
                project=project or None,
                dry_run=parse_bool(dry_run, False),
                force=parse_bool(force, False),
            )
            return tool_success(data, "Memory consolidation completed through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
