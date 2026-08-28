from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from threading import Lock
from typing import Any

from usr.plugins.tree_ring_memory.helpers.activation import (
    ActivationBinding,
    load_activation_binding,
)
from usr.plugins.tree_ring_memory.helpers.cli import TreeRingCli
from usr.plugins.tree_ring_memory.helpers.config import load_config
from usr.plugins.tree_ring_memory.helpers.context import InvocationContext


PROMPT_CONTEXT_KEY = "tree_ring_memory"
MAX_CONTEXT_CHARS = 16_000
MAX_PREFLIGHT_RESULTS = 8
MAX_CONCURRENT_PREFLIGHTS = 4
CHECKPOINT_PREFIX = "trcp_v1_"
_PERSISTED_CHAT_MARKER = "_persist_chat_saved"


@dataclass(frozen=True)
class LifecycleResult:
    """Redacted result of one Agent Zero lifecycle integration attempt."""

    event: str
    state: str
    injected: bool
    context_chars: int = 0
    result_count: int = 0
    checkpoint_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class _CachedContext:
    result: LifecycleResult
    context: str
    store_id: str


_STATE_LOCK = Lock()
_PREFLIGHT_SLOTS = asyncio.Semaphore(MAX_CONCURRENT_PREFLIGHTS)
_TURN_CONTEXTS: dict[tuple[str, str, str, str], _CachedContext] = {}
_LATEST_BY_STORE: dict[str, LifecycleResult] = {}


async def inject_lifecycle_context(
    *, agent: Any, loop_data: Any
) -> LifecycleResult:
    """Run receipt-backed preflight and attach only its safe prompt context.

    The adapter deliberately never reads ``loop_data.user_message`` or agent
    history. Identity and project configuration come only from Agent Zero's
    trusted runtime objects. The synchronous CLI process is moved off the event
    loop; its own configured subprocess timeout remains the cancellation bound.
    """

    if agent is None:
        return LifecycleResult(
            event="unavailable", state="configured-awaiting-proof", injected=False
        )

    identity = InvocationContext.from_agent(agent)
    event = _lifecycle_event(agent, identity)
    key = _turn_key(identity, agent)
    cached = _cached_context(key)
    if cached is not None:
        had_context = _has_context(loop_data)
        if _attach_context(loop_data, cached.context):
            event = (
                "compaction_rehydrate"
                if not had_context
                else cached.result.event
            )
            return LifecycleResult(
                event=event,
                state=cached.result.state,
                injected=True,
                context_chars=cached.result.context_chars,
                result_count=cached.result.result_count,
                checkpoint_id=cached.result.checkpoint_id,
            )
        result = LifecycleResult(
            event=event,
            state="configured-awaiting-proof",
            injected=False,
            error="Agent Zero prompt extras are unavailable.",
        )
        _record_latest(cached.store_id, result)
        _log_result(agent, result)
        return result

    config = _load_scoped_config(agent)
    binding_status = load_activation_binding(config)
    binding = binding_status.binding
    if binding is None or binding_status.state != "configured-awaiting-proof":
        result = LifecycleResult(
            event=event,
            state=binding_status.state,
            injected=False,
            error=binding_status.error,
        )
        _record_latest(binding_status.store_id, result)
        return result

    bridge = TreeRingCli(config, context=identity)
    try:
        # TreeRingCli applies cli.timeout_seconds to the child process. Keeping
        # one bounded child per turn avoids unbounded background tasks while
        # preventing synchronous subprocess I/O from blocking Agent Zero.
        async with _PREFLIGHT_SLOTS:
            response = await asyncio.to_thread(
                bridge.preflight_activation, binding
            )
        recalled_context, result_count = _validated_context(response, binding)
        checkpoint_id = _new_checkpoint_id()
        context = _compose_prompt_context(
            recalled_context,
            checkpoint_id=checkpoint_id,
        )
        if not _attach_context(loop_data, context):
            raise ValueError("Agent Zero prompt extras are unavailable.")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        result = LifecycleResult(
            event=event,
            state="configured-awaiting-proof",
            injected=False,
            error=str(exc),
        )
        _record_latest(binding.store_id, result)
        _log_result(agent, result)
        return result

    result = LifecycleResult(
        event=event,
        state="active",
        injected=True,
        context_chars=len(context),
        result_count=result_count,
        checkpoint_id=checkpoint_id,
    )
    with _STATE_LOCK:
        _TURN_CONTEXTS[key] = _CachedContext(
            result=result, context=context, store_id=binding.store_id
        )
        _LATEST_BY_STORE[binding.store_id] = result
    _log_result(agent, result)
    return result


def cleanup_lifecycle_context(*, agent: Any, loop_data: Any | None = None) -> None:
    """Drop ephemeral lifecycle context at Agent Zero's monologue boundary."""

    if agent is None:
        return
    identity = InvocationContext.from_agent(agent)
    with _STATE_LOCK:
        _TURN_CONTEXTS.pop(_turn_key(identity, agent), None)
    _remove_context(loop_data)


def latest_lifecycle_result(store_id: str | None) -> LifecycleResult | None:
    """Return redacted process-local injection evidence for API normalization."""

    if not store_id:
        return None
    with _STATE_LOCK:
        return _LATEST_BY_STORE.get(store_id)


def _load_scoped_config(agent: Any) -> dict[str, Any]:
    configured: dict[str, Any] = {}
    try:
        from helpers import plugins as framework_plugins

        value = framework_plugins.get_plugin_config(
            "tree_ring_memory", agent=agent
        )
        if isinstance(value, dict):
            configured = value
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        configured = {}
    return load_config(configured)


def _validated_context(
    response: Any, binding: ActivationBinding
) -> tuple[str, int]:
    if not isinstance(response, dict) or response.get("state") != "active":
        raise ValueError("Tree Ring preflight did not return active context.")
    context = response.get("context")
    receipt = response.get("receipt")
    if not isinstance(context, str) or not context.strip():
        raise ValueError("Tree Ring preflight returned empty context.")
    if len(context) > MAX_CONTEXT_CHARS:
        raise ValueError("Tree Ring preflight context exceeded the prompt safety bound.")
    if not isinstance(receipt, dict):
        raise ValueError("Tree Ring preflight did not return a receipt.")
    if receipt.get("harness_id") != "agent-zero":
        raise ValueError("Tree Ring preflight receipt named the wrong harness.")
    if receipt.get("protocol_version") != binding.protocol_version:
        raise ValueError("Tree Ring preflight receipt used the wrong protocol.")
    if receipt.get("store_id") != binding.store_id:
        raise ValueError("Tree Ring preflight receipt named the wrong store.")
    if (
        receipt.get("project_root_fingerprint")
        != binding.project_root_fingerprint
    ):
        raise ValueError("Tree Ring preflight receipt named the wrong project.")
    if receipt.get("status") != "success":
        raise ValueError("Tree Ring preflight receipt was not successful.")
    result_count = receipt.get("result_count")
    if (
        type(result_count) is not int
        or result_count < 0
        or result_count > MAX_PREFLIGHT_RESULTS
    ):
        raise ValueError("Tree Ring preflight receipt had an invalid result count.")
    return context, result_count


def _new_checkpoint_id() -> str:
    """Return a fresh non-authorizing identifier for one Agent Zero turn."""

    return CHECKPOINT_PREFIX + secrets.token_hex(16)


def _compose_prompt_context(
    recalled_context: str, *, checkpoint_id: str
) -> str:
    operation_ids = tuple(
        _checkpoint_operation_id(checkpoint_id, index) for index in range(1, 4)
    )
    source_ref = _checkpoint_source_ref(checkpoint_id)
    checkpoint = (
        "## Automatic Tree Ring memory checkpoint\n"
        f"Checkpoint ID: `{checkpoint_id}`\n\n"
        "The checkpoint ID is correlation metadata, not an authorization capability. "
        "This checkpoint is bound by Agent Zero to the current agent, project, "
        "workflow, and session. Never pass or override agent_profile, project, "
        "workflow_id, or session_id; the Tree Ring tools derive them from the "
        "trusted host context.\n\n"
        "Before your final response, automatically review only the durable outcomes "
        "of this turn. Select 0-3 concise normal-sensitivity candidates and use only "
        "the Tree Ring `capture` tool. Do not use `remember` or `evidence` for this "
        "automatic checkpoint. Choose one core-approved event/ring pair: preference "
        "or decision with cambium; lesson or correction with cambium or scar; warning "
        "with scar; or seed with seed. "
        "Use one distinct candidate slot per write:\n"
        f"1. operation_id `{operation_ids[0]}`\n"
        f"2. operation_id `{operation_ids[1]}`\n"
        f"3. operation_id `{operation_ids[2]}`\n"
        "A retry of the same candidate must reuse its indexed operation_id. Never "
        "use one slot for different writes. Set source_ref on every candidate to "
        f"`{source_ref}`. If nothing is durable, do not call `capture`.\n\n"
        "Never store raw prompts, transcripts, tool logs, secrets, transient status, "
        "or speculative conclusions. Do not start a background task or recorder."
    )
    combined = f"{recalled_context.rstrip()}\n\n{checkpoint}"
    if len(combined) > MAX_CONTEXT_CHARS:
        raise ValueError(
            "Tree Ring recalled context and checkpoint exceeded the prompt safety bound."
        )
    return combined


def _checkpoint_operation_id(checkpoint_id: str, index: int) -> str:
    if index not in {1, 2, 3}:
        raise ValueError("Automatic checkpoint candidate index must be 1, 2, or 3.")
    return f"auto-{checkpoint_id}-{index}"


def _checkpoint_source_ref(checkpoint_id: str) -> str:
    return f"agent-checkpoint:{checkpoint_id}"


def validate_capture_checkpoint(
    *, agent: Any, operation_id: str, source_ref: str
) -> str:
    """Validate one capture slot against the active Agent Zero turn checkpoint."""

    if agent is None:
        raise ValueError("Automatic capture requires an active Agent Zero agent.")
    identity = InvocationContext.from_agent(agent)
    cached = _cached_context(_turn_key(identity, agent))
    checkpoint_id = cached.result.checkpoint_id if cached is not None else None
    if not checkpoint_id or not cached.result.injected:
        raise ValueError(
            "Automatic capture requires an active receipt-backed lifecycle checkpoint."
        )
    allowed_operations = {
        _checkpoint_operation_id(checkpoint_id, index) for index in range(1, 4)
    }
    if operation_id not in allowed_operations:
        raise ValueError(
            "Automatic capture operation_id does not match the active checkpoint slot."
        )
    if source_ref != _checkpoint_source_ref(checkpoint_id):
        raise ValueError(
            "Automatic capture source_ref does not match the active checkpoint."
        )
    return checkpoint_id


def _lifecycle_event(agent: Any, identity: InvocationContext) -> str:
    if _is_subagent(agent, identity):
        return "subagent_start"
    context = getattr(agent, "context", None)
    getter = getattr(context, "get_data", None)
    if callable(getter):
        try:
            if getter(_PERSISTED_CHAT_MARKER):
                return "session_resume"
        except (KeyError, TypeError, ValueError):
            pass
    return "session_start"


def _is_subagent(agent: Any, identity: InvocationContext) -> bool:
    number = getattr(agent, "number", 0)
    if isinstance(number, int) and number > 0:
        return True
    return bool(
        identity.workflow_id
        and identity.session_id
        and identity.workflow_id != identity.session_id
    )


def _turn_key(
    identity: InvocationContext, agent: Any
) -> tuple[str, str, str, str]:
    return (
        identity.session_id or "",
        identity.workflow_id or "",
        identity.agent_profile or "",
        str(getattr(agent, "number", "")),
    )


def _cached_context(
    key: tuple[str, str, str, str]
) -> _CachedContext | None:
    with _STATE_LOCK:
        return _TURN_CONTEXTS.get(key)


def _record_latest(store_id: str | None, result: LifecycleResult) -> None:
    if not store_id:
        return
    with _STATE_LOCK:
        _LATEST_BY_STORE[store_id] = result


def _has_context(loop_data: Any) -> bool:
    extras = getattr(loop_data, "extras_persistent", None)
    return isinstance(extras, dict) and PROMPT_CONTEXT_KEY in extras


def _attach_context(loop_data: Any, context: str) -> bool:
    extras = getattr(loop_data, "extras_persistent", None)
    if not isinstance(extras, dict):
        return False
    extras[PROMPT_CONTEXT_KEY] = context
    return True


def _remove_context(loop_data: Any | None) -> None:
    if loop_data is None:
        return
    for name in ("extras_persistent", "extras_temporary"):
        extras = getattr(loop_data, name, None)
        if isinstance(extras, dict):
            extras.pop(PROMPT_CONTEXT_KEY, None)


def _log_result(agent: Any, result: LifecycleResult) -> None:
    context = getattr(agent, "context", None)
    logger = getattr(context, "log", None)
    log = getattr(logger, "log", None)
    if not callable(log):
        return
    try:
        if result.injected:
            log(
                type="util",
                heading="Tree Ring Memory active",
                content=(
                    f"Injected receipt-backed lifecycle context for {result.event} "
                    f"({result.result_count} safe results)."
                ),
            )
        else:
            log(
                type="warning",
                heading="Tree Ring Memory awaiting proof",
                content=(
                    "Receipt-backed lifecycle context was not injected. "
                    "Start a new Agent Zero turn after repairing activation."
                ),
            )
    except Exception:
        # Logging is observational and must never change activation truth or
        # prevent otherwise-valid prompt context from reaching Agent Zero.
        return
