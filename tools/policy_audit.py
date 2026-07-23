from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class PolicyAudit(Tool):
    async def execute(self, limit: int = 100, **kwargs):
        del kwargs
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            return tool_success(
                bridge.policy_audit(limit=limit),
                "Tree Ring protected-write authorization audit read without changing the store.",
            )
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
