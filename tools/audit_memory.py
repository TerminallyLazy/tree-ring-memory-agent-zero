from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class AuditMemory(Tool):
    async def execute(self, audit_type: str = "all", **kwargs):
        del kwargs
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            return tool_success(bridge.audit(audit_type), "Memory audit completed through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
