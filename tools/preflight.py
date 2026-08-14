from __future__ import annotations

from helpers.tool import Tool
from usr.plugins.tree_ring_memory.helpers.activation import load_activation_binding
from usr.plugins.tree_ring_memory.tools._common import (
    BRIDGE_ERRORS,
    activation_state_payload,
    bridge_and_config,
    tool_error,
    tool_response,
    tool_success,
)


class Preflight(Tool):
    async def execute(self):
        try:
            bridge, config = bridge_and_config(getattr(self, "agent", None))
            status = load_activation_binding(config)
            if status.binding is None or status.state != "configured-awaiting-proof":
                response = activation_state_payload(status)
                return tool_response(
                    {
                        "ok": False,
                        "message": "Tree Ring preflight is not ready.",
                        "data": response,
                        "warnings": [],
                        "error": response.get("error")
                        or (
                            "Tree Ring preflight is blocked while activation state is "
                            f"{status.state}."
                        ),
                    }
                )
            response = bridge.preflight_activation(status.binding)
            return tool_success(response, "Tree Ring preflight complete.")
        except BRIDGE_ERRORS as exc:
            return tool_error(exc)
