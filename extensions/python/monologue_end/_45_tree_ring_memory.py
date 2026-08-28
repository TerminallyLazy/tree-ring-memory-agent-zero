from __future__ import annotations

from typing import Any

from agent import LoopData
from helpers.extension import Extension
from usr.plugins.tree_ring_memory.runtime.lifecycle import cleanup_lifecycle_context


class CleanupTreeRingMemoryContext(Extension):
    """Remove only ephemeral Tree Ring lifecycle state after a monologue."""

    def execute(self, loop_data: LoopData | None = None, **kwargs: Any) -> None:
        del kwargs
        if not self.agent:
            return

        try:
            cleanup_lifecycle_context(agent=self.agent, loop_data=loop_data)
        except Exception:
            extras = getattr(loop_data, "extras_persistent", None)
            if isinstance(extras, dict):
                extras.pop("tree_ring_memory", None)
