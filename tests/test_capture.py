from __future__ import annotations

import asyncio
import importlib
import sys
from types import ModuleType
from types import SimpleNamespace


def import_capture_module(monkeypatch):
    tool_module = ModuleType("helpers.tool")

    class Tool:
        agent = None

    class Response:
        def __init__(self, *, message, break_loop, additional):
            self.message = message
            self.break_loop = break_loop
            self.additional = additional

    tool_module.Tool = Tool
    tool_module.Response = Response
    plugins_module = ModuleType("helpers.plugins")
    plugins_module.get_plugin_config = lambda *args, **kwargs: {}
    monkeypatch.setitem(sys.modules, "helpers.tool", tool_module)
    monkeypatch.setitem(sys.modules, "helpers.plugins", plugins_module)
    monkeypatch.delitem(
        sys.modules, "usr.plugins.tree_ring_memory.tools.capture", raising=False
    )
    monkeypatch.delitem(
        sys.modules, "usr.plugins.tree_ring_memory.tools._common", raising=False
    )
    return importlib.import_module("usr.plugins.tree_ring_memory.tools.capture")


def test_capture_tool_uses_only_active_checkpoint_and_server_bound_bridge(monkeypatch):
    capture_module = import_capture_module(monkeypatch)
    calls = []
    agent = object()

    class Bridge:
        def capture(self, summary, **kwargs):
            calls.append((summary, kwargs))
            return {"id": "mem-captured", "sensitivity": "normal"}

    bridge = Bridge()
    monkeypatch.setattr(
        capture_module,
        "validate_capture_checkpoint",
        lambda **kwargs: calls.append(("validate", kwargs)) or "trcp_v1_fixture",
    )
    monkeypatch.setattr(
        capture_module,
        "bridge_and_config",
        lambda received: (bridge, {}) if received is agent else None,
    )
    tool = capture_module.Capture()
    tool.agent = agent

    response = asyncio.run(
        tool.execute(
            summary="Preserve strict capture.",
            event_type="decision",
            ring="cambium",
            operation_id="auto-trcp_v1_fixture-1",
            source_ref="agent-checkpoint:trcp_v1_fixture",
            tags=["lifecycle"],
        )
    )

    assert calls == [
        (
            "validate",
            {
                "agent": agent,
                "operation_id": "auto-trcp_v1_fixture-1",
                "source_ref": "agent-checkpoint:trcp_v1_fixture",
            },
        ),
        (
            "Preserve strict capture.",
            {
                "event_type": "decision",
                "ring": "cambium",
                "operation_id": "auto-trcp_v1_fixture-1",
                "source_ref": "agent-checkpoint:trcp_v1_fixture",
                "tags": ["lifecycle"],
            },
        ),
    ]
    assert response.additional["tree_ring_memory"]["data"] == {
        "id": "mem-captured",
        "sensitivity": "normal",
    }


def test_capture_tool_rejects_caller_identity_before_bridge_dispatch(monkeypatch):
    capture_module = import_capture_module(monkeypatch)
    monkeypatch.setattr(
        capture_module,
        "bridge_and_config",
        lambda agent: (_ for _ in ()).throw(
            AssertionError("caller identity must fail before bridge dispatch")
        ),
    )
    tool = capture_module.Capture()
    tool.agent = SimpleNamespace()

    response = asyncio.run(
        tool.execute(
            summary="Candidate",
            event_type="lesson",
            ring="cambium",
            operation_id="auto-trcp_v1_fixture-1",
            source_ref="agent-checkpoint:trcp_v1_fixture",
            project="spoofed-project",
            session_id="spoofed-session",
        )
    )

    payload = response.additional["tree_ring_memory"]
    assert payload["ok"] is False
    assert "server-derived" in payload["error"]
    assert "project" in payload["error"]
    assert "session_id" in payload["error"]
