from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class PolicyStatus(Tool):
    async def execute(self, **kwargs):
        del kwargs
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            return tool_success(
                bridge.policy_status(),
                "Tree Ring coordinated-policy status read without changing the store.",
            )
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
