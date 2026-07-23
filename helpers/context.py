from __future__ import annotations

from dataclasses import dataclass
from typing import Any


WORKFLOW_CONTEXT_KEYS = (
    "tree_ring_workflow_id",
    "_parallel_parent_context_id",
    "parent_context_id",
)


@dataclass(frozen=True)
class InvocationContext:
    """Server-derived Agent Zero identity forwarded to Tree Ring.

    Identity is never sourced from tool or API payload fields. This keeps an
    unprivileged caller from impersonating a coordinator profile while still
    giving fan-out workers a shared workflow id and their own session id.
    """

    agent_profile: str | None = None
    project: str | None = None
    workflow_id: str | None = None
    session_id: str | None = None

    @classmethod
    def from_agent(cls, agent: Any) -> "InvocationContext":
        if agent is None:
            return cls()

        context = getattr(agent, "context", None)
        profile = _text(getattr(getattr(agent, "config", None), "profile", None))
        if not profile:
            profile = _text(getattr(agent, "agent_name", None))
        if not profile:
            number = getattr(agent, "number", None)
            profile = f"A{number}" if number is not None else None

        project = None
        if context is not None:
            try:
                from helpers import projects

                project = _text(projects.get_context_project_name(context))
            except (ImportError, AttributeError, TypeError):
                project = None

        session_id = _text(getattr(context, "id", None))
        workflow_id = _workflow_id(context) or session_id
        return cls(
            agent_profile=profile,
            project=project,
            workflow_id=workflow_id,
            session_id=session_id,
        )


def coordinator_profiles(config: dict[str, Any]) -> frozenset[str]:
    configured = (config.get("coordination") or {}).get("coordinator_profiles") or []
    if isinstance(configured, str):
        configured = [configured]
    if not isinstance(configured, list):
        return frozenset()
    return frozenset(
        profile
        for item in configured
        if (profile := _text(item)) is not None
    )


def _workflow_id(context: Any) -> str | None:
    if context is None:
        return None
    for key in WORKFLOW_CONTEXT_KEYS:
        value = _context_value(context, key)
        if value:
            return value
    return None


def _context_value(context: Any, key: str) -> str | None:
    getter = getattr(context, "get_data", None)
    if callable(getter):
        try:
            value = _text(getter(key))
        except (KeyError, TypeError, ValueError):
            value = None
        if value:
            return value
    data = getattr(context, "data", None)
    if isinstance(data, dict):
        value = _text(data.get(key))
        if value:
            return value
    output_data = getattr(context, "output_data", None)
    if isinstance(output_data, dict):
        return _text(output_data.get(key))
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
