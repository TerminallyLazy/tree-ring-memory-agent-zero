from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class Forget(Tool):
    async def execute(
        self,
        memory_id: str = "",
        mode: str = "delete",
        reason: str = "",
        **kwargs,
    ):
        if kwargs.get("query"):
            return tool_error("tree-ring 0.12 requires an explicit memory_id for forget.")
        if not memory_id:
            return tool_error("memory_id is required")
        if not reason.strip():
            return tool_error("reason is required")
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            data = bridge.forget(memory_id, mode=mode, reason=reason)
            return tool_success(data, f"Memory {mode} completed through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
