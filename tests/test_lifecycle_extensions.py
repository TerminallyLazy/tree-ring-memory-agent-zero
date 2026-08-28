from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROMPT_EXTENSION = (
    ROOT / "extensions/python/message_loop_prompts_after/_45_tree_ring_memory.py"
)
END_EXTENSION = ROOT / "extensions/python/monologue_end/_45_tree_ring_memory.py"


def _load_extension(
    monkeypatch,
    *,
    path: Path,
    inject: Any,
    cleanup: Any,
) -> ModuleType:
    agent_module = ModuleType("agent")
    agent_module.LoopData = SimpleNamespace
    extension_module = ModuleType("helpers.extension")

    class Extension:
        def __init__(self, agent=None, **kwargs):
            del kwargs
            self.agent = agent

    extension_module.Extension = Extension
    lifecycle_module = ModuleType(
        "usr.plugins.tree_ring_memory.runtime.lifecycle"
    )
    lifecycle_module.inject_lifecycle_context = inject
    lifecycle_module.cleanup_lifecycle_context = cleanup

    monkeypatch.setitem(sys.modules, "agent", agent_module)
    monkeypatch.setitem(sys.modules, "helpers.extension", extension_module)
    monkeypatch.setitem(
        sys.modules,
        "usr.plugins.tree_ring_memory.runtime.lifecycle",
        lifecycle_module,
    )

    module_name = f"_tree_ring_extension_{path.parent.name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_message_loop_extension_delegates_only_server_owned_context(monkeypatch):
    calls: list[dict[str, Any]] = []

    async def inject(**kwargs):
        calls.append(kwargs)

    module = _load_extension(
        monkeypatch,
        path=PROMPT_EXTENSION,
        inject=inject,
        cleanup=lambda **kwargs: None,
    )
    agent = object()
    loop_data = SimpleNamespace(extras_persistent={})

    asyncio.run(module.InjectTreeRingMemoryContext(agent=agent).execute(loop_data))

    assert calls == [{"agent": agent, "loop_data": loop_data}]


def test_message_loop_extension_fails_open_without_stale_prompt_context(monkeypatch):
    async def inject(**kwargs):
        del kwargs
        raise RuntimeError("local bridge unavailable")

    module = _load_extension(
        monkeypatch,
        path=PROMPT_EXTENSION,
        inject=inject,
        cleanup=lambda **kwargs: None,
    )
    loop_data = SimpleNamespace(
        extras_persistent={"tree_ring_memory": "stale", "unrelated": "keep"}
    )

    asyncio.run(module.InjectTreeRingMemoryContext(agent=object()).execute(loop_data))

    assert loop_data.extras_persistent == {"unrelated": "keep"}


def test_message_loop_extension_failure_tolerates_missing_prompt_extras(monkeypatch):
    async def inject(**kwargs):
        del kwargs
        raise RuntimeError("local bridge unavailable")

    module = _load_extension(
        monkeypatch,
        path=PROMPT_EXTENSION,
        inject=inject,
        cleanup=lambda **kwargs: None,
    )

    asyncio.run(
        module.InjectTreeRingMemoryContext(agent=object()).execute(SimpleNamespace())
    )


def test_monologue_end_extension_delegates_ephemeral_cleanup(monkeypatch):
    calls: list[dict[str, Any]] = []

    def cleanup(**kwargs):
        calls.append(kwargs)

    module = _load_extension(
        monkeypatch,
        path=END_EXTENSION,
        inject=lambda **kwargs: None,
        cleanup=cleanup,
    )
    agent = object()
    loop_data = SimpleNamespace(extras_persistent={})

    module.CleanupTreeRingMemoryContext(agent=agent).execute(loop_data)

    assert calls == [{"agent": agent, "loop_data": loop_data}]


def test_monologue_end_extension_never_blocks_agent_cleanup(monkeypatch):
    def cleanup(**kwargs):
        del kwargs
        raise RuntimeError("cleanup failed")

    module = _load_extension(
        monkeypatch,
        path=END_EXTENSION,
        inject=lambda **kwargs: None,
        cleanup=cleanup,
    )
    loop_data = SimpleNamespace(
        extras_persistent={"tree_ring_memory": "ephemeral", "unrelated": "keep"}
    )

    module.CleanupTreeRingMemoryContext(agent=object()).execute(loop_data)

    assert loop_data.extras_persistent == {"unrelated": "keep"}


def test_extensions_do_not_scrape_or_persist_conversation_content():
    prompt_source = PROMPT_EXTENSION.read_text(encoding="utf-8")
    end_source = END_EXTENSION.read_text(encoding="utf-8")

    for source in (prompt_source, end_source):
        assert "user_message" not in source
        assert ".history" not in source
        assert "remember(" not in source
        assert "evidence(" not in source

    assert "cleanup_lifecycle_context" in end_source
