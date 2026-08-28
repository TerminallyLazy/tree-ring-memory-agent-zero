from __future__ import annotations

from typing import Any

from agent import LoopData
from helpers.extension import Extension
from usr.plugins.tree_ring_memory.runtime.lifecycle import inject_lifecycle_context


class InjectTreeRingMemoryContext(Extension):
    """Delegate bounded recall and the capture checkpoint to the runtime adapter."""

    async def execute(self, loop_data: LoopData, **kwargs: Any) -> None:
        del kwargs
        if not self.agent:
            return

        try:
            await inject_lifecycle_context(agent=self.agent, loop_data=loop_data)
        except Exception:
            # Lifecycle recall is advisory. Never leave stale context attached or
            # prevent Agent Zero from continuing when the local bridge is unavailable.
            extras = getattr(loop_data, "extras_persistent", None)
            if isinstance(extras, dict):
                extras.pop("tree_ring_memory", None)
