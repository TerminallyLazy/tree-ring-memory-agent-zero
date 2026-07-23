from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.helpers.values import parse_bool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class ExportMemory(Tool):
    async def execute(
        self,
        output_path: str = "",
        include_sensitive: bool = False,
        include_superseded: bool = False,
        **kwargs,
    ):
        if kwargs.get("format") not in (None, "", "jsonl"):
            return tool_error("tree-ring 0.13 exports canonical JSONL only.")
        if kwargs.get("memory_ids"):
            return tool_error("tree-ring 0.13 does not expose selected-memory export.")
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            data = bridge.export_to_file(
                output_path=output_path or None,
                include_sensitive=parse_bool(include_sensitive, False),
                include_superseded=parse_bool(include_superseded, False),
            )
            return tool_success(data, "Memory export completed through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
