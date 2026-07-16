from __future__ import annotations

import asyncio

from usr.plugins.tree_ring_memory.api import memory_api


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def status(self):
        return {"ok": False, "required_version": "0.12.0", "error": "missing cli"}

    def recall(self, query, **kwargs):
        self.calls.append(("recall", {"query": query, **kwargs}))
        return {"query": query, "count": 0, "results": []}

    def remember(self, summary, **kwargs):
        self.calls.append(("remember", {"summary": summary, **kwargs}))
        return {"id": "mem_new", "summary": summary}

    def sync_dox(self, **kwargs):
        self.calls.append(("sync_dox", kwargs))
        return {"ok": True, "dry_run": kwargs["dry_run"], "report": {}}


def handler_with_fake(monkeypatch):
    fake = FakeBridge()
    monkeypatch.setattr(memory_api, "TreeRingCli", lambda config: fake)
    return memory_api.MemoryApi.__new__(memory_api.MemoryApi), fake


def test_status_preserves_readiness_details_when_cli_is_missing(monkeypatch):
    handler, _ = handler_with_fake(monkeypatch)

    result = asyncio.run(handler.process({"action": "status"}, None))

    assert result["ok"] is False
    assert result["data"]["required_version"] == "0.12.0"
    assert result["error"] == "missing cli"


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
