"""Tests for M6 — ask_orchestrator tool."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from femtobot.agent.tools.ask_orchestrator import (
    AskOrchestratorTool,
    _ask_max_attempts,
    _check_ask_budget,
    _resolve_channel,
    _resolve_chat_id,
)
from femtobot.agent.tools.context import RequestContext, ToolContext
from femtobot.session.goal_state import GOAL_STATE_KEY, goal_waiting_on
from femtobot.session.pending_asks import (
    AskStatus,
    AskTarget,
    PendingAsk,
    count_pending_asks,
    list_pending_asks,
)


def _make_tool_ctx(tmp_path, *, max_ask_attempts: int = 3) -> ToolContext:
    from femtobot.config.schema import LongTaskConfig
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    ctx = ToolContext(
        config=SimpleNamespace(),
        workspace=str(tmp_path),
        bus=None,
        sessions=sessions,
        runtime_events=None,
    )
    # ``ToolContext`` does not declare ``long_task_config`` as a field; attach
    # the long-task profile as a plain attribute so the tool can read it.
    ctx.long_task_config = LongTaskConfig(
        max_goal_ask_attempts=max_ask_attempts
    )
    return ctx


def _make_session_with_active_goal(ctx: ToolContext, chat_id: str = "chat-1"):
    sessions = ctx.sessions
    session = sessions.get_or_create(f"cli:{chat_id}")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "Ship v1"},
    }
    return session


def _make_request(channel: str = "cli", chat_id: str = "chat-1") -> RequestContext:
    return RequestContext(channel=channel, chat_id=chat_id)


# ---------------------------------------------------------------------------
# PR 6.1 — tool structure
# ---------------------------------------------------------------------------


def test_ask_orchestrator_tool_has_required_schema():
    tool = AskOrchestratorTool()
    props = tool.parameters.get("properties", {})
    assert "question" in props
    assert set(props.keys()) >= {
        "question", "context", "options", "timeoutS", "blocking", "target"
    }
    assert "question" in tool.parameters.get("required", [])


def test_ask_orchestrator_capabilities():
    tool = AskOrchestratorTool()
    assert "orchestrator" in tool.get_capabilities()
    assert "long-running" in tool.get_capabilities()


# ---------------------------------------------------------------------------
# PR 6.2 — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_orchestrator_persists_pending_ask(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    session = _make_session_with_active_goal(ctx)
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(
        question="Pick A or B?",
        options="A,B",
    )
    assert "correlation_id=ask_" in out
    assert "blocked" in out.lower()
    asks = list_pending_asks(session.metadata)
    assert len(asks) == 1
    ask = asks[0]
    assert ask.question == "Pick A or B?"
    assert ask.options == ["A", "B"]
    assert ask.status is AskStatus.PENDING
    assert goal_waiting_on(session.metadata) == "ask_orchestrator"


@pytest.mark.asyncio
async def test_ask_orchestrator_rejects_without_active_goal(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    sessions = ctx.sessions
    sessions.get_or_create("cli:chat-1")  # empty session
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(question="what?")
    assert "active sustained goal" in out.lower()


@pytest.mark.asyncio
async def test_ask_orchestrator_rejects_empty_question(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    _make_session_with_active_goal(ctx)
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(question="   ")
    assert "question" in out.lower()


@pytest.mark.asyncio
async def test_ask_orchestrator_rejects_oversized_timeout(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    _make_session_with_active_goal(ctx)
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(question="X?", timeoutS="5")
    assert "timeoutS" in out


# ---------------------------------------------------------------------------
# PR 6.2 — budget cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_orchestrator_enforces_budget(tmp_path):
    ctx = _make_tool_ctx(tmp_path, max_ask_attempts=2)
    session = _make_session_with_active_goal(ctx)
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(_make_request())
    # Burn the budget
    await tool.execute(question="Q1?")
    await tool.execute(question="Q2?")
    out = await tool.execute(question="Q3?")
    assert "budget exhausted" in out.lower()
    assert count_pending_asks(session.metadata) == 2


@pytest.mark.asyncio
async def test_ask_orchestrator_disabled_budget_allows_unlimited(tmp_path):
    ctx = _make_tool_ctx(tmp_path, max_ask_attempts=0)
    _make_session_with_active_goal(ctx)
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(_make_request())
    for i in range(5):
        out = await tool.execute(question=f"Q{i}?")
        assert "budget exhausted" not in out.lower()


# ---------------------------------------------------------------------------
# PR 6.3 — routing helpers
# ---------------------------------------------------------------------------


def test_resolve_channel_uses_escalation_when_configured():
    from femtobot.config.schema import LongTaskConfig

    ctx = SimpleNamespace(long_task_config=LongTaskConfig(escalation_channel="api"))
    assert _resolve_channel(ctx, default_channel="cli") == "api"
    ctx2 = SimpleNamespace(long_task_config=LongTaskConfig())
    assert _resolve_channel(ctx2, default_channel="cli") == "cli"
    ctx3 = SimpleNamespace(long_task_config=None)
    assert _resolve_channel(ctx3, default_channel="cli") == "cli"


def test_resolve_chat_id_uses_escalation_when_configured():
    from femtobot.config.schema import LongTaskConfig

    ctx = SimpleNamespace(long_task_config=LongTaskConfig(escalation_chat_id="orch"))
    assert _resolve_chat_id(ctx, default_chat_id="chat-1") == "orch"
    ctx2 = SimpleNamespace(long_task_config=LongTaskConfig())
    assert _resolve_chat_id(ctx2, default_chat_id="chat-1") == "chat-1"
    ctx3 = SimpleNamespace(long_task_config=None)
    assert _resolve_chat_id(ctx3, default_chat_id="chat-1") == "chat-1"


def test_ask_max_attempts_defaults_to_three():
    assert _ask_max_attempts(SimpleNamespace(long_task_config=None)) == 3
    assert _ask_max_attempts(SimpleNamespace()) == 3
    cfg = SimpleNamespace(max_goal_ask_attempts=7)
    assert _ask_max_attempts(SimpleNamespace(long_task_config=cfg)) == 7


def test_check_ask_budget_returns_error_when_exceeded():
    md = {}
    for i in range(2):
        md["pending_asks"] = md.get("pending_asks", []) + [
            {
                "correlation_id": f"ask_pending{i:04d}",
                "target": "orchestrator",
                "question": f"q{i}?",
                "options": [],
                "status": "pending",
                "created_at": "now",
                "deadline_at": None,
                "answered_at": None,
                "response": None,
                "goal_id": None,
                "session_key": None,
            }
        ]
    err = _check_ask_budget(md, max_attempts=2)
    assert err is not None and "budget" in err.lower()
    err2 = _check_ask_budget(md, max_attempts=5)
    assert err2 is None


def test_check_ask_budget_zero_disables_cap():
    md = {"pending_asks": [{"status": "pending"}] * 100}
    assert _check_ask_budget(md, max_attempts=0) is None


# ---------------------------------------------------------------------------
# PR 6.4 — non-blocking variant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_orchestrator_nonblocking_returns_immediately(tmp_path):
    ctx = _make_tool_ctx(tmp_path)
    session = _make_session_with_active_goal(ctx)
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(_make_request())
    out = await tool.execute(question="Q?", blocking="false")
    assert "non-blocking" in out.lower()
    # Pending ask is still recorded (so the orchestrator can answer later)
    asks = list_pending_asks(session.metadata)
    assert len(asks) == 1


# ---------------------------------------------------------------------------
# End-to-end: timeout / restart via expire_pending_asks
# ---------------------------------------------------------------------------


def test_expire_pending_asks_after_deadline():
    from datetime import datetime, timedelta, timezone

    from femtobot.session.pending_asks import expire_pending_asks

    md = {}
    past = datetime.now(timezone.utc) - timedelta(seconds=120)
    past_iso = past.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    ask = PendingAsk(
        correlation_id="ask_overdue123",
        target=AskTarget.ORCHESTRATOR,
        question="x?",
        created_at=past_iso,
        deadline_at=past_iso,
    )
    md["pending_asks"] = [ask.to_dict()]
    expired = expire_pending_asks(md)
    assert len(expired) == 1
    assert expired[0].status is AskStatus.TIMED_OUT


# ---------------------------------------------------------------------------
# ask_target enum mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_target_human_routes_to_current_channel(tmp_path):
    """When the agent picks ``target=human`` we still publish on the
    current channel so the user sees the question immediately."""
    ctx = _make_tool_ctx(tmp_path)
    _make_session_with_active_goal(ctx)
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(_make_request(channel="cli", chat_id="chat-1"))
    out = await tool.execute(question="Continue?", target="human")
    assert "ask_" in out
    # Verify the pending ask was recorded with target=human
    from femtobot.session.pending_asks import list_pending_asks

    session = ctx.sessions.get_or_create("cli:chat-1")
    asks = list_pending_asks(session.metadata)
    assert asks[0].target is AskTarget.HUMAN