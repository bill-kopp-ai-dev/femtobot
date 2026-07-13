"""Tests for M2 of long-task-by-default — long_task and complete_goal tools.

M2 introduces the two new tools, the per-turn tool-schema filter, and
the loop hook that marks non-slash inbounds as ``goal_requested`` when
``by_default=true``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from femtobot.agent.goal_permission import (
    goal_mutation_allowed,
    goal_mutation_scope,
    revoke_goal_mutation_permission,
)
from femtobot.agent.tools.context import RequestContext, ToolContext
from femtobot.agent.tools.long_task import (
    CompleteGoalTool,
    LongTaskTool,
    current_goal_blob,
)
from femtobot.session.goal_state import GOAL_STATE_KEY, sustained_goal_active


def _make_tool_ctx(tmp_path) -> ToolContext:
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    return ToolContext(
        config=SimpleNamespace(),
        workspace=str(tmp_path),
        bus=None,
        sessions=sessions,
        runtime_events=None,
    )


def _make_request(channel: str = "cli", chat_id: str = "chat-1") -> RequestContext:
    return RequestContext(channel=channel, chat_id=chat_id)


# ---------------------------------------------------------------------------
# LongTaskTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_task_records_active_goal(tmp_path):
    sessions_holder: dict = {}

    class _CTX:
        sessions = None
        runtime_events = None

    ctx = _CTX()
    sessions_holder["sessions"] = ctx.sessions
    # Use real SessionManager via ToolContext:
    ctx = _make_tool_ctx(tmp_path)

    tool = LongTaskTool.create(ctx)
    tool.set_context(_make_request())
    assert not goal_mutation_allowed()

    with goal_mutation_scope(True):
        out = await tool.execute(objective="Refactor module X")

    assert "Goal recorded" in out
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    assert sustained_goal_active(session.metadata)
    blob = session.metadata[GOAL_STATE_KEY]
    assert blob["objective"] == "Refactor module X"
    assert blob["source"] == "long_task"


@pytest.mark.asyncio
async def test_long_task_requires_mutation_permission(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    tool = LongTaskTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(objective="Refactor X")
    assert "not allowed" in out.lower()
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    assert not sustained_goal_active(session.metadata)


@pytest.mark.asyncio
async def test_long_task_rejects_open_questions(tmp_path):
    from femtobot.config.schema import LongTaskConfig

    ctx = _make_tool_ctx(tmp_path)
    ctx.long_task_config = LongTaskConfig(
        require_objective_self_containment=True
    )
    tool = LongTaskTool.create(ctx)
    tool.set_context(_make_request())
    with goal_mutation_scope(True):
        out = await tool.execute(objective="How can I refactor X?")
    assert "open-ended" in out.lower()


@pytest.mark.asyncio
async def test_long_task_allows_questions_when_disabled(tmp_path):
    from femtobot.config.schema import LongTaskConfig

    ctx = _make_tool_ctx(tmp_path)
    ctx.long_task_config = LongTaskConfig(
        require_objective_self_containment=False
    )
    tool = LongTaskTool.create(ctx)
    tool.set_context(_make_request())
    with goal_mutation_scope(True):
        out = await tool.execute(objective="How do I refactor X?")
    assert "recorded" in out.lower()


@pytest.mark.asyncio
async def test_long_task_rejects_oversized_objective(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    tool = LongTaskTool.create(ctx)
    tool.set_context(_make_request())
    with goal_mutation_scope(True):
        out = await tool.execute(objective="x" * 5000)
    assert "exceeds" in out.lower()


@pytest.mark.asyncio
async def test_long_task_rejects_non_string_objective(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    tool = LongTaskTool.create(ctx)
    tool.set_context(_make_request())
    with goal_mutation_scope(True):
        out = await tool.execute(objective=12345)  # type: ignore[arg-type]
    assert "must be a string" in out.lower()


@pytest.mark.asyncio
async def test_long_task_records_replacement_chain(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    tool = LongTaskTool.create(ctx)
    tool.set_context(_make_request())
    with goal_mutation_scope(True):
        await tool.execute(objective="First objective")
    with goal_mutation_scope(True):
        out = await tool.execute(objective="Refined objective")
    assert "recorded" in out.lower()
    blob = session.metadata[GOAL_STATE_KEY]
    assert blob["objective"] == "Refined objective"
    assert blob["previous_objective"] == "First objective"
    assert "replaced_at" in blob


# ---------------------------------------------------------------------------
# CompleteGoalTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_goal_completes_active_goal(tmp_path):
    from femtobot.session.goal_state import GOAL_STATE_KEY

    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship v1"},
        "goal_started_at": 1.0,
    }

    tool = CompleteGoalTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(action="complete", recap="done")
    assert "complete" in out.lower()
    blob = session.metadata[GOAL_STATE_KEY]
    assert blob["status"] == "completed"
    assert blob["recap"] == "done"
    assert not sustained_goal_active(session.metadata)


@pytest.mark.asyncio
async def test_complete_goal_cancels_active_goal(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(action="cancel", recap="lost interest")
    assert "cancel" in out.lower()
    assert session.metadata[GOAL_STATE_KEY]["status"] == "cancelled"
    assert session.metadata[GOAL_STATE_KEY]["cancel_reason"] == "lost interest"


@pytest.mark.asyncio
async def test_complete_goal_blocks_with_reason(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(action="block", recap="needs approval")
    assert "block" in out.lower()
    assert session.metadata[GOAL_STATE_KEY]["status"] == "blocked"
    assert session.metadata["goal_block_reason"] == "needs approval"


@pytest.mark.asyncio
async def test_complete_goal_replace_requires_permission(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "goal_started_at": 1.0,
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(action="replace", objective="Refined objective")
    assert "not allowed" in out.lower()


@pytest.mark.asyncio
async def test_complete_goal_replace_with_permission(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "goal_started_at": 1.0,
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(_make_request())
    with goal_mutation_scope(True):
        out = await tool.execute(
            action="replace",
            objective="Refined objective",
            ui_summary="Refined",
        )
    assert "replaced" in out.lower()
    blob = session.metadata[GOAL_STATE_KEY]
    assert blob["objective"] == "Refined objective"
    assert blob["previous_objective"] == "ship"
    assert blob["status"] == "active"


@pytest.mark.asyncio
async def test_complete_goal_unknown_action_rejected(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(action="nuke")
    assert "unknown" in out.lower()


@pytest.mark.asyncio
async def test_complete_goal_without_active_goal_refuses(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    sessions.get_or_create("cli:chat-1")  # empty session
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(action="complete")
    assert "no active goal" in out.lower()


@pytest.mark.asyncio
async def test_complete_goal_revokes_mutation_permission(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(_make_request())
    with goal_mutation_scope(True):
        assert goal_mutation_allowed() is True
        await tool.execute(action="complete")
    assert goal_mutation_allowed() is False
    revoke_goal_mutation_permission()  # cleanup


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def test_current_goal_blob_returns_dict_or_none():
    blob = {"status": "active", "objective": "ship"}
    assert current_goal_blob({GOAL_STATE_KEY: blob}) == blob
    assert current_goal_blob({}) is None


def test_tool_schema_lists_capabilities():
    long_tool = LongTaskTool()
    assert "long-running" in long_tool.get_capabilities()
    assert "goal-management" in long_tool.get_capabilities()
    complete_tool = CompleteGoalTool()
    assert "long-running" in complete_tool.get_capabilities()