from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.helpers.values import parse_bool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class MaintainMemory(Tool):
    async def execute(
        self,
        project: str = "",
        include_superseded: bool = False,
        apply_expired: bool = False,
        apply_secret_redactions: bool = False,
        repair_fts: bool = False,
        **kwargs,
    ):
        del kwargs
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            data = bridge.maintain(
                project=project or None,
                include_superseded=parse_bool(include_superseded, False),
                apply_expired=parse_bool(apply_expired, False),
                apply_secret_redactions=parse_bool(apply_secret_redactions, False),
                repair_fts=parse_bool(repair_fts, False),
            )
            return tool_success(data, "Memory maintenance completed through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
