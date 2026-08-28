from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.runtime.lifecycle import (
    validate_capture_checkpoint,
)
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class Capture(Tool):
    """Strict, lifecycle-bound automatic memory capture surface."""

    async def execute(
        self,
        summary: str = "",
        event_type: str = "",
        ring: str = "",
        operation_id: str = "",
        source_ref: str = "",
        tags: list[str] | None = None,
        **kwargs,
    ):
        unsupported = [
            key for key, value in kwargs.items() if value not in (None, "", [], {})
        ]
        if unsupported:
            return tool_error(
                "Automatic capture identity is server-derived; unsupported fields: "
                + ", ".join(sorted(unsupported))
            )

        agent = getattr(self, "agent", None)
        try:
            validate_capture_checkpoint(
                agent=agent,
                operation_id=operation_id,
                source_ref=source_ref,
            )
            bridge, _ = bridge_and_config(agent)
            event = bridge.capture(
                summary,
                event_type=event_type,
                ring=ring,
                operation_id=operation_id,
                source_ref=source_ref,
                tags=tags or [],
            )
            return tool_success(
                event, "Memory captured through strict tree-ring capture."
            )
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
