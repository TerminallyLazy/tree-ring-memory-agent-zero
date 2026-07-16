from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class Evidence(Tool):
    async def execute(
        self,
        summary: str = "",
        evidence_ref: str = "",
        outcome: str = "observed",
        project: str = "",
        details: str = "",
        score: float | None = None,
        tags: list[str] | None = None,
        **kwargs,
    ):
        del kwargs
        bridge, _ = bridge_and_config(getattr(self, "agent", None))
        try:
            event = bridge.evidence(
                summary,
                evidence_ref=evidence_ref,
                outcome=outcome,
                project=project or None,
                details=details or None,
                score=score,
                tags=tags or [],
            )
            return tool_success(event, "Evidence-backed memory stored through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
