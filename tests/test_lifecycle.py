from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from usr.plugins.tree_ring_memory.runtime import lifecycle


class Context:
    def __init__(self, context_id: str, data: dict | None = None):
        self.id = context_id
        self.data = data or {}
        self.output_data = {}
        self.log = SimpleNamespace(log=lambda **kwargs: None)

    def get_data(self, key):
        return self.data.get(key)


class Agent:
    def __init__(self, context_id="session-1", *, number=0, data=None):
        self.context = Context(context_id, data)
        self.number = number
        self.agent_name = f"A{number}"
        self.config = SimpleNamespace(profile="developer")


class LoopData:
    def __init__(self):
        self.extras_persistent = {}
        self.extras_temporary = {}
        self.user_message = SimpleNamespace(content="must never be read")


def binding_status():
    binding = SimpleNamespace(
        store_id="store-fixture",
        project_root_fingerprint="a" * 64,
        protocol_version=1,
    )
    return SimpleNamespace(
        state="configured-awaiting-proof",
        binding=binding,
        store_id=binding.store_id,
        error=None,
    )


def active_response(context="bounded safe context", *, result_count=2):
    return {
        "state": "active",
        "context": context,
        "receipt": {
            "harness_id": "agent-zero",
            "protocol_version": 1,
            "store_id": "store-fixture",
            "project_root_fingerprint": "a" * 64,
            "status": "success",
            "result_count": result_count,
        },
    }


def reset_runtime_state():
    with lifecycle._STATE_LOCK:
        lifecycle._TURN_CONTEXTS.clear()
        lifecycle._LATEST_BY_STORE.clear()


def test_session_start_runs_server_derived_preflight_and_injects_context(monkeypatch):
    reset_runtime_state()
    agent = Agent()
    loop_data = LoopData()
    calls = []

    class Bridge:
        def __init__(self, config, *, context):
            calls.append((config, context))

        def preflight_activation(self, binding):
            calls.append(binding)
            return active_response()

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {"scope": "server"})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)

    result = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=loop_data)
    )

    assert result.event == "session_start"
    assert result.state == "active"
    assert result.injected is True
    assert result.result_count == 2
    assert result.error is None
    injected = loop_data.extras_persistent[lifecycle.PROMPT_CONTEXT_KEY]
    assert injected.startswith("bounded safe context\n\n")
    assert result.context_chars == len(injected)
    assert result.checkpoint_id is not None
    assert result.checkpoint_id.startswith(lifecycle.CHECKPOINT_PREFIX)
    assert len(result.checkpoint_id) == len(lifecycle.CHECKPOINT_PREFIX) + 32
    assert all(
        character in "0123456789abcdef"
        for character in result.checkpoint_id[len(lifecycle.CHECKPOINT_PREFIX) :]
    )
    assert f"Checkpoint ID: `{result.checkpoint_id}`" in injected
    assert "correlation metadata, not an authorization capability" in injected
    assert "Select 0-3 concise normal-sensitivity candidates" in injected
    assert "Tree Ring `capture`" in injected
    assert "Do not use `remember` or `evidence`" in injected
    assert "preference or decision with cambium" in injected
    assert "warning with scar; or seed with seed" in injected
    operation_ids = {
        lifecycle._checkpoint_operation_id(result.checkpoint_id, index)
        for index in range(1, 4)
    }
    assert operation_ids == {
        f"auto-{result.checkpoint_id}-1",
        f"auto-{result.checkpoint_id}-2",
        f"auto-{result.checkpoint_id}-3",
    }
    assert all(operation_id in injected for operation_id in operation_ids)
    assert "A retry of the same candidate must reuse its indexed operation_id" in injected
    assert "Never use one slot for different writes" in injected
    assert f"`agent-checkpoint:{result.checkpoint_id}`" in injected
    assert "If nothing is durable, do not call `capture`" in injected
    assert "Never store raw prompts, transcripts, tool logs" in injected
    assert "Do not start a background task or recorder" in injected
    assert "Never pass or override agent_profile" in injected
    assert "must never be read" not in injected
    invocation = calls[0][1]
    assert invocation.agent_profile == "developer"
    assert invocation.workflow_id == "session-1"
    assert invocation.session_id == "session-1"
    assert "must never be read" not in repr(calls)


def test_subagent_gets_distinct_server_owned_identity(monkeypatch):
    reset_runtime_state()
    agent = Agent("worker-9", number=3)
    agent.context.output_data["parent_context_id"] = "parent-1"
    received = []

    class Bridge:
        def __init__(self, config, *, context):
            del config
            received.append(context)

        def preflight_activation(self, binding):
            del binding
            return active_response(result_count=0)

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)

    loop_data = LoopData()
    result = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=loop_data)
    )

    assert result.event == "subagent_start"
    assert received[0].agent_profile == "developer"
    assert received[0].workflow_id == "parent-1"
    assert received[0].session_id == "worker-9"
    assert result.checkpoint_id is not None
    assert result.checkpoint_id in loop_data.extras_persistent[
        lifecycle.PROMPT_CONTEXT_KEY
    ]


def test_resume_uses_agent_zero_persisted_chat_marker(monkeypatch):
    reset_runtime_state()
    agent = Agent(data={"_persist_chat_saved": True})

    class Bridge:
        def __init__(self, config, *, context):
            del config, context

        def preflight_activation(self, binding):
            del binding
            return active_response(result_count=0)

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)

    result = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=LoopData())
    )

    assert result.event == "session_resume"


def test_sibling_subagents_never_share_a_checkpoint(monkeypatch):
    reset_runtime_state()
    calls = 0

    class Bridge:
        def __init__(self, config, *, context):
            del config, context

        def preflight_activation(self, binding):
            nonlocal calls
            del binding
            calls += 1
            return active_response(result_count=0)

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)
    first = asyncio.run(
        lifecycle.inject_lifecycle_context(
            agent=Agent("shared-context", number=1), loop_data=LoopData()
        )
    )
    second = asyncio.run(
        lifecycle.inject_lifecycle_context(
            agent=Agent("shared-context", number=2), loop_data=LoopData()
        )
    )

    assert calls == 2
    assert first.checkpoint_id is not None
    assert second.checkpoint_id is not None
    assert first.checkpoint_id != second.checkpoint_id


def test_prompt_rebuild_reattaches_cached_context_without_second_preflight(monkeypatch):
    reset_runtime_state()
    agent = Agent()
    calls = 0

    class Bridge:
        def __init__(self, config, *, context):
            del config, context

        def preflight_activation(self, binding):
            nonlocal calls
            del binding
            calls += 1
            return active_response()

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)
    first_loop = LoopData()
    first = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=first_loop)
    )
    rebuilt_loop = LoopData()

    result = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=rebuilt_loop)
    )

    assert calls == 1
    assert result.event == "compaction_rehydrate"
    assert result.checkpoint_id == first.checkpoint_id
    assert rebuilt_loop.extras_persistent[lifecycle.PROMPT_CONTEXT_KEY] == (
        first_loop.extras_persistent[lifecycle.PROMPT_CONTEXT_KEY]
    )
    for index in range(1, 4):
        assert (
            f"auto-{first.checkpoint_id}-{index}"
            in rebuilt_loop.extras_persistent[lifecycle.PROMPT_CONTEXT_KEY]
        )


def test_malformed_receipt_never_injects_or_reports_active(monkeypatch):
    reset_runtime_state()
    agent = Agent()
    loop_data = LoopData()
    response = active_response()
    response["receipt"]["store_id"] = "wrong-store"

    class Bridge:
        def __init__(self, config, *, context):
            del config, context

        def preflight_activation(self, binding):
            del binding
            return response

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)

    result = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=loop_data)
    )

    assert result.state == "configured-awaiting-proof"
    assert result.injected is False
    assert lifecycle.PROMPT_CONTEXT_KEY not in loop_data.extras_persistent
    assert lifecycle.latest_lifecycle_result("store-fixture") == result


def test_observability_failure_does_not_discard_valid_context(monkeypatch):
    reset_runtime_state()
    agent = Agent()
    agent.context.log = SimpleNamespace(
        log=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("log offline"))
    )
    loop_data = LoopData()

    class Bridge:
        def __init__(self, config, *, context):
            del config, context

        def preflight_activation(self, binding):
            del binding
            return active_response()

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)

    result = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=loop_data)
    )

    assert result.injected is True
    assert result.state == "active"
    assert loop_data.extras_persistent[lifecycle.PROMPT_CONTEXT_KEY].startswith(
        "bounded safe context\n\n"
    )


def test_cleanup_retires_checkpoint_and_next_turn_gets_a_fresh_id(monkeypatch):
    reset_runtime_state()
    agent = Agent()
    calls = 0

    class Bridge:
        def __init__(self, config, *, context):
            del config, context

        def preflight_activation(self, binding):
            nonlocal calls
            del binding
            calls += 1
            return active_response(result_count=0)

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)
    first_loop = LoopData()
    first = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=first_loop)
    )

    lifecycle.cleanup_lifecycle_context(agent=agent, loop_data=first_loop)
    second_loop = LoopData()
    second = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=second_loop)
    )

    assert calls == 2
    assert first.checkpoint_id is not None
    assert second.checkpoint_id is not None
    assert second.checkpoint_id != first.checkpoint_id
    assert first.checkpoint_id not in second_loop.extras_persistent[
        lifecycle.PROMPT_CONTEXT_KEY
    ]


def test_capture_checkpoint_validation_rejects_wrong_or_retired_slots(monkeypatch):
    reset_runtime_state()
    agent = Agent()

    class Bridge:
        def __init__(self, config, *, context):
            del config, context

        def preflight_activation(self, binding):
            del binding
            return active_response(result_count=0)

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)
    loop_data = LoopData()
    result = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=loop_data)
    )
    assert result.checkpoint_id is not None
    operation_id = lifecycle._checkpoint_operation_id(result.checkpoint_id, 2)
    source_ref = lifecycle._checkpoint_source_ref(result.checkpoint_id)

    assert lifecycle.validate_capture_checkpoint(
        agent=agent, operation_id=operation_id, source_ref=source_ref
    ) == result.checkpoint_id
    with pytest.raises(ValueError, match="operation_id"):
        lifecycle.validate_capture_checkpoint(
            agent=agent,
            operation_id=f"auto-{result.checkpoint_id}-4",
            source_ref=source_ref,
        )
    with pytest.raises(ValueError, match="source_ref"):
        lifecycle.validate_capture_checkpoint(
            agent=agent,
            operation_id=operation_id,
            source_ref="agent-checkpoint:stale",
        )

    lifecycle.cleanup_lifecycle_context(agent=agent, loop_data=loop_data)

    with pytest.raises(ValueError, match="active receipt-backed"):
        lifecycle.validate_capture_checkpoint(
            agent=agent, operation_id=operation_id, source_ref=source_ref
        )


def test_checkpoint_is_not_injected_when_combined_context_exceeds_bound(monkeypatch):
    reset_runtime_state()
    agent = Agent()
    loop_data = LoopData()

    class Bridge:
        def __init__(self, config, *, context):
            del config, context

        def preflight_activation(self, binding):
            del binding
            return active_response(context="x" * lifecycle.MAX_CONTEXT_CHARS)

    monkeypatch.setattr(lifecycle, "_load_scoped_config", lambda received: {})
    monkeypatch.setattr(lifecycle, "load_activation_binding", lambda config: binding_status())
    monkeypatch.setattr(lifecycle, "TreeRingCli", Bridge)

    result = asyncio.run(
        lifecycle.inject_lifecycle_context(agent=agent, loop_data=loop_data)
    )

    assert result.state == "configured-awaiting-proof"
    assert result.injected is False
    assert result.checkpoint_id is None
    assert lifecycle.PROMPT_CONTEXT_KEY not in loop_data.extras_persistent


def test_cleanup_removes_only_ephemeral_tree_ring_context():
    reset_runtime_state()
    agent = Agent()
    loop_data = LoopData()
    loop_data.extras_persistent.update(
        {lifecycle.PROMPT_CONTEXT_KEY: "safe", "other": "preserve"}
    )
    loop_data.extras_temporary[lifecycle.PROMPT_CONTEXT_KEY] = "safe"
    key = lifecycle._turn_key(
        lifecycle.InvocationContext.from_agent(agent), agent
    )
    with lifecycle._STATE_LOCK:
        lifecycle._TURN_CONTEXTS[key] = lifecycle._CachedContext(
            lifecycle.LifecycleResult("session_start", "active", True),
            "safe",
            "store-fixture",
        )

    lifecycle.cleanup_lifecycle_context(agent=agent, loop_data=loop_data)

    assert key not in lifecycle._TURN_CONTEXTS
    assert loop_data.extras_persistent == {"other": "preserve"}
    assert loop_data.extras_temporary == {}
