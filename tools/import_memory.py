from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.helpers.values import parse_bool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class ImportMemory(Tool):
    async def execute(
        self,
        path: str = "",
        dry_run: bool = True,
        replace_existing: bool = False,
        **kwargs,
    ):
        del kwargs
        if not path:
            return tool_error("path is required")
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            data = bridge.import_file(
                path,
                dry_run=parse_bool(dry_run, True),
                replace_existing=parse_bool(replace_existing, False),
            )
            return tool_success(data, "Memory import completed through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
