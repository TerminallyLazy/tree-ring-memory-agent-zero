from __future__ import annotations

import sys
from types import ModuleType
from types import SimpleNamespace

from usr.plugins.tree_ring_memory.helpers.context import InvocationContext


class FakeContext:
    def __init__(self) -> None:
        self.id = "child-session"
        self.data = {"_parallel_parent_context_id": "parent-workflow"}
        self.output_data = {}

    def get_data(self, key):
        return self.data.get(key)


def test_agent_zero_parallel_context_maps_to_tree_ring_identity(monkeypatch):
    import helpers

    projects = ModuleType("helpers.projects")
    projects.get_context_project_name = lambda context: "tree-ring"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "helpers.projects", projects)
    monkeypatch.setattr(helpers, "projects", projects, raising=False)
    agent = SimpleNamespace(
        context=FakeContext(),
        config=SimpleNamespace(profile="reviewer"),
        agent_name="A2",
        number=2,
    )

    mapped = InvocationContext.from_agent(agent)

    assert mapped.agent_profile == "reviewer"
    assert mapped.project == "tree-ring"
    assert mapped.workflow_id == "parent-workflow"
    assert mapped.session_id == "child-session"


def test_agent_profile_falls_back_to_agent_name():
    agent = SimpleNamespace(
        context=SimpleNamespace(id="chat-1", data={}, output_data={}),
        config=SimpleNamespace(profile=""),
        agent_name="A3",
        number=3,
    )

    mapped = InvocationContext.from_agent(agent)

    assert mapped.agent_profile == "A3"
    assert mapped.workflow_id == "chat-1"
    assert mapped.session_id == "chat-1"
