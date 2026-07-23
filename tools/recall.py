from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.helpers.values import parse_bool
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    bridge_and_config,
    tool_error,
    tool_success,
)


class Recall(Tool):
    async def execute(self, query: str = "", **kwargs):
        bridge, config = bridge_and_config(getattr(self, "agent", None))
        try:
            data = bridge.recall(
                query,
                project=kwargs.get("project") or None,
                agent_profile=kwargs.get("agent_profile") or None,
                workflow_id=kwargs.get("workflow_id") or None,
                session_id=kwargs.get("session_id") or None,
                include_all_agents=parse_bool(
                    kwargs.get("include_all_agents"), False
                ),
                scope=kwargs.get("scope") or None,
                rings=kwargs.get("rings") or None,
                event_types=kwargs.get("event_types") or None,
                include_sensitive=parse_bool(kwargs.get("include_sensitive"), False),
                include_superseded=parse_bool(kwargs.get("include_superseded"), False),
                limit=int(kwargs.get("limit") or (config.get("recall") or {}).get("max_results_default", 8)),
                explain_ranking=parse_bool(kwargs.get("explain_ranking"), False),
            )
            return tool_success(data, "Memory recalled through tree-ring.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
