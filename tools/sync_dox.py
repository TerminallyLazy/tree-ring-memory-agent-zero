from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.helpers.values import parse_bool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class SyncDox(Tool):
    async def execute(
        self,
        source_root: str = "",
        project: str = "",
        dry_run: bool = True,
        **kwargs,
    ):
        del kwargs
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            data = bridge.sync_dox(
                source_root=source_root or None,
                project=project or None,
                dry_run=parse_bool(dry_run, True),
            )
            return tool_success(data, "DOX sync completed through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
