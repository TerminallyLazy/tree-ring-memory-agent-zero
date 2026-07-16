from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class Remember(Tool):
    async def execute(
        self,
        summary: str = "",
        event_type: str = "lesson",
        ring: str = "cambium",
        scope: str = "global",
        project: str = "",
        tags: list[str] | None = None,
        **kwargs,
    ):
        unsupported = [key for key, value in kwargs.items() if value not in (None, "", [], {})]
        if unsupported:
            return tool_error(
                "tree-ring 0.12 remember does not accept: "
                + ", ".join(sorted(unsupported))
                + ". Use the evidence tool for evaluated details."
            )
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            event = bridge.remember(
                summary,
                event_type=event_type or "lesson",
                ring=ring or "cambium",
                scope=scope or ("project" if project else "global"),
                project=project or None,
                tags=tags or [],
            )
            return tool_success(event, "Memory stored through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
