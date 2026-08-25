from __future__ import annotations

import asyncio
from types import SimpleNamespace

from usr.plugins.tree_ring_memory.api import memory_api


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def status(self):
        return {"ok": False, "required_version": "0.15.3", "error": "missing cli"}

    def recall(self, query, **kwargs):
        self.calls.append(("recall", {"query": query, **kwargs}))
        return {"query": query, "count": 0, "results": []}

    def remember(self, summary, **kwargs):
        self.calls.append(("remember", {"summary": summary, **kwargs}))
        return {"id": "mem_new", "summary": summary}

    def sync_dox(self, **kwargs):
        self.calls.append(("sync_dox", kwargs))
        return {"ok": True, "dry_run": kwargs["dry_run"], "report": {}}

    def activation_status(self, binding):
        del binding
        self.calls.append(("activation_status", {}))
        return {
            "state": "needs-project-mount",
            "receipt_age_seconds": 9,
            "next_step": "Mount the canonical project store.",
            "receipt": {"content": "must-not-leak"},
            "coordinator_capability": "must-not-leak",
        }

    def preflight_activation(self, binding):
        self.calls.append(("preflight_activation", {"binding": binding}))
        return {"state": "active", "result_count": 0}


def handler_with_fake(monkeypatch):
    fake = FakeBridge()
    handler = memory_api.MemoryApi.__new__(memory_api.MemoryApi)
    handler._bridge = lambda input, require_context: (  # type: ignore[method-assign]
        fake,
        {"recall": {"max_results_default": 8}},
    )
    return handler, fake


def test_status_preserves_readiness_details_when_cli_is_missing(monkeypatch):
    handler, _ = handler_with_fake(monkeypatch)

    result = asyncio.run(handler.process({"action": "status"}, None))

    assert result["ok"] is False
    assert result["data"]["required_version"] == "0.15.3"
    assert result["error"] == "missing cli"


def test_status_adds_only_redacted_server_activation_fields(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)
    binding = object()
    monkeypatch.setattr(
        memory_api,
        "load_activation_binding",
        lambda config: SimpleNamespace(
            state="configured-awaiting-proof",
            binding=binding,
            store_id="store-fixture",
            next_step="Run Tree Ring preflight in a new Agent Zero session.",
            error=None,
        ),
    )
    fake.activation_status = lambda received: {
        "state": "active",
        "store_id": "untrusted-core-store",
        "receipt_age_seconds": 7,
        "next_step": "Continue with the current project task.",
        "receipt": {"recalled_summaries": ["must stay server-side"]},
        "coordinator_capability": "must-not-leak",
    }

    result = asyncio.run(handler.process({"action": "status"}, None))

    assert result["data"]["activation"] == {
        "state": "active",
        "store_id": "store-fixture",
        "receipt_age_seconds": 7,
        "next_step": "Continue with the current project task.",
    }


def test_remember_rejects_python_only_fields(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)

    result = asyncio.run(
        handler.process(
            {"action": "remember", "memory": {"summary": "x", "event_type": "lesson", "details": "legacy"}},
            None,
        )
    )

    assert result["ok"] is False
    assert "does not accept: details" in result["error"]
    assert fake.calls == []


def test_dox_sync_defaults_to_safe_dry_run(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)

    result = asyncio.run(handler.process({"action": "sync_dox"}, None))

    assert result["ok"] is True
    assert fake.calls == [("sync_dox", {"source_root": None, "project": None, "dry_run": True})]


def test_envelope_does_not_replace_empty_lists_with_objects():
    assert memory_api.envelope([])["data"] == []


def test_api_rejects_coordinator_capability_fields_before_dispatch(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)

    result = asyncio.run(
        handler.process(
            {
                "action": "remember",
                "context_id": "chat-1",
                "coordinator_token": "must-not-be-accepted",
            },
            None,
        )
    )

    assert result["ok"] is False
    assert "never accepted" in result["error"]
    assert fake.calls == []


def test_api_rejects_nested_capability_field_before_dispatch(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)

    result = asyncio.run(
        handler.process(
            {
                "action": "remember",
                "context_id": "chat-1",
                "memory": {
                    "summary": "must not dispatch",
                    "metadata": {
                        "coordinator-capability": "must-not-be-accepted"
                    },
                },
            },
            None,
        )
    )

    assert result["ok"] is False
    assert "never accepted" in result["error"]
    assert fake.calls == []


def test_preflight_requires_an_existing_agent_zero_context(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)

    def require_context(input, *, require_context):
        if require_context and not (input.get("context_id") or input.get("ctxid")):
            raise ValueError(
                "context_id is required for Tree Ring mutations so Agent Zero can derive the writer identity."
            )
        return fake, {"recall": {"max_results_default": 8}}

    handler._bridge = require_context  # type: ignore[method-assign]

    result = asyncio.run(handler.process({"action": "preflight"}, None))

    assert result["ok"] is False
    assert "context_id is required" in result["error"]
    assert fake.calls == []


def test_activation_status_is_read_only_and_returns_one_next_step(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)
    binding = object()
    monkeypatch.setattr(
        memory_api,
        "load_activation_binding",
        lambda config: SimpleNamespace(
            state="configured-awaiting-proof",
            binding=binding,
            store_id="store-fixture",
            next_step="Run Tree Ring preflight in a new Agent Zero session.",
            error=None,
        ),
        raising=False,
    )

    result = asyncio.run(handler.process({"action": "activation_status"}, None))

    assert result["data"]["state"] == "needs-project-mount"
    assert result["data"]["next_step"]
    assert list(result["data"]).count("next_step") == 1
    assert result["data"]["receipt_age_seconds"] == 9
    assert "receipt" not in result["data"]
    assert "coordinator_capability" not in result["data"]
    assert fake.calls == [("activation_status", {})]


def test_preflight_rejects_caller_identity_and_task_text_before_dispatch(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)

    result = asyncio.run(
        handler.process(
            {
                "action": "preflight",
                "context_id": "chat-1",
                "agent_profile": "impersonated-worker",
                "task_hint": "caller-controlled prompt",
            },
            None,
        )
    )

    assert result["ok"] is False
    assert "server-derived" in result["error"]
    assert fake.calls == []


def test_preflight_dispatches_only_the_validated_binding(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)
    binding = object()
    monkeypatch.setattr(
        memory_api,
        "load_activation_binding",
        lambda config: SimpleNamespace(
            state="configured-awaiting-proof",
            binding=binding,
            store_id="store-fixture",
            next_step="Run Tree Ring preflight in a new Agent Zero session.",
            error=None,
        ),
    )

    result = asyncio.run(
        handler.process({"action": "preflight", "context_id": "chat-1"}, None)
    )

    assert result["data"] == {"state": "active", "result_count": 0}
    assert fake.calls == [("preflight_activation", {"binding": binding})]


def test_unshared_preflight_returns_exact_state_without_cli_dispatch(monkeypatch):
    handler, fake = handler_with_fake(monkeypatch)
    monkeypatch.setattr(
        memory_api,
        "load_activation_binding",
        lambda config: SimpleNamespace(
            state="active-isolated",
            binding=object(),
            store_id="store-fixture",
            next_step="Point storage.root at the mounted project .tree-ring root to share memory.",
            error=None,
        ),
    )

    result = asyncio.run(
        handler.process({"action": "preflight", "context_id": "chat-1"}, None)
    )

    assert result["data"] == {
        "state": "active-isolated",
        "store_id": "store-fixture",
        "next_step": "Point storage.root at the mounted project .tree-ring root to share memory.",
    }
    assert fake.calls == []
