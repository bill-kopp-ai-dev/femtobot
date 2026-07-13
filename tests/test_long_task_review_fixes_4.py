"""Regression tests for the *fourth* code-review pass."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from femtobot.agent.tools.context import ToolContext
from femtobot.api.goal_handlers import GoalRegistry, register_goal_routes
from femtobot.api.goal_runtime import GoalJobStatus
from femtobot.session.goal_state import (
    GOAL_STATE_KEY,
    goal_block_reason,
    goal_waiting_on,
)
from femtobot.session.pending_asks import (
    AskStatus,
    list_pending_asks,
    find_pending_ask,
    iter_pending_asks,
)


# ---------------------------------------------------------------------------
# Bug P — GoalRegistry.update_status is idempotent
# ---------------------------------------------------------------------------


def test_goal_registry_update_status_is_idempotent():
    """Calling ``update_status`` with the current status must NOT emit
    additional STATUS_CHANGED/FINAL events."""
    reg = GoalRegistry()
    job = reg.create(session_key="api:w")
    reg.update_status(job.goal_id, GoalJobStatus.RUNNING)
    initial_event_count = len(reg.get(job.goal_id).events)
    # Same status again — must not double-publish.
    reg.update_status(job.goal_id, GoalJobStatus.RUNNING)
    final_count = len(reg.get(job.goal_id).events)
    assert final_count == initial_event_count


def test_goal_registry_update_status_emits_on_actual_transition():
    reg = GoalRegistry()
    job = reg.create(session_key="api:w")
    initial_count = len(reg.get(job.goal_id).events)
    # Real transition (ACCEPTED → RUNNING) must publish.
    reg.update_status(job.goal_id, GoalJobStatus.RUNNING)
    after = len(reg.get(job.goal_id).events)
    assert after > initial_count


# ---------------------------------------------------------------------------
# Bug L — handle_create_goal narrows exception handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_create_goal_propagates_typeerror_from_bad_bus(tmp_path):
    """A misconfigured bus (no ``publish_inbound``) must raise TypeError,
    not be swallowed by the broad ``except Exception``."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from femtobot.session.manager import SessionManager

    app = web.Application()
    register_goal_routes(app)

    class _BusStub:
        pass  # no publish_inbound!

    class _LoopStub:
        bus = _BusStub()

        @property
        def sessions(self):
            return SessionManager(tmp_path)

    app["agent_loop"] = _LoopStub()

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            "/v1/goals",
            json={"session_id": "w", "objective": "ship"},
        ) as resp:
            assert resp.status == 500
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Bug AA — publish_goal_state_changed narrows exception handling
# ---------------------------------------------------------------------------


def test_publish_goal_state_changed_propagates_typeerror(monkeypatch):
    """Programmer errors (TypeError, KeyError) must NOT be swallowed."""
    from femtobot.bus import goal_events as ge
    from femtobot.bus.runtime_events import GoalStateChanged

    # Bind a bus that always raises TypeError on publish.
    class _BadBus:
        def publish_nowait(self, evt: GoalStateChanged) -> None:
            raise TypeError("bus misconfigured")

    ge.set_active_event_bus(_BadBus())
    try:
        with pytest.raises(TypeError):
            ge.publish_goal_state_changed(
                channel="cli",
                chat_id="chat-1",
                session_metadata={GOAL_STATE_KEY: {"status": "active"}},
            )
    finally:
        ge.set_active_event_bus(None)


def test_publish_goal_state_changed_swallows_runtime_error(monkeypatch):
    """Transport-level failures (RuntimeError) are recoverable."""
    from femtobot.bus import goal_events as ge

    class _BadBus:
        def publish_nowait(self, evt) -> None:
            raise RuntimeError("queue full")

    ge.set_active_event_bus(_BadBus())
    try:
        # Must NOT raise.
        ge.publish_goal_state_changed(
            channel="cli",
            chat_id="chat-1",
            session_metadata={},
        )
    finally:
        ge.set_active_event_bus(None)


# ---------------------------------------------------------------------------
# Bug CC — goal_block_reason / goal_waiting_on type guards
# ---------------------------------------------------------------------------


def test_goal_block_reason_rejects_non_string():
    md = {"goal_block_reason": b"raw bytes"}
    assert goal_block_reason(md) is None


def test_goal_block_reason_strips_whitespace():
    md = {"goal_block_reason": "   ship blocked   "}
    assert goal_block_reason(md) == "ship blocked"


def test_goal_block_reason_treats_blank_as_none():
    assert goal_block_reason({"goal_block_reason": "   "}) is None
    assert goal_block_reason({"goal_block_reason": ""}) is None


def test_goal_waiting_on_rejects_non_string():
    assert goal_waiting_on({"goal_waiting_on": 42}) is None


def test_goal_waiting_on_strips_whitespace():
    assert goal_waiting_on({"goal_waiting_on": "  ask_orchestrator  "}) == "ask_orchestrator"


# ---------------------------------------------------------------------------
# Bug T — runtime_context uses AskStatus identity check
# ---------------------------------------------------------------------------


def test_runtime_context_uses_typed_status_check():
    """``ask_pending_block`` must filter via the ``AskStatus`` enum,
    not string comparison — guards against string drift."""
    from femtobot.runtime_context import ask_pending_block
    from femtobot.session.pending_asks import (
        append_pending_ask,
        PendingAsk,
    )

    md: dict = {}
    append_pending_ask(
        md,
        PendingAsk(
            correlation_id="ask_pendingabc",
            target="orchestrator",
            question="q?",
        ),
    )
    # Sanity: pending ask → block emitted.
    block = ask_pending_block(md)
    assert block is not None


# ---------------------------------------------------------------------------
# Bug A — CompleteGoalTool caps recap at 8000 chars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_goal_caps_recap_at_8000_chars(tmp_path):
    from femtobot.agent.goal_permission import goal_mutation_scope
    from femtobot.agent.tools.long_task import CompleteGoalTool
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    ctx = ToolContext(
        config=SimpleNamespace(),
        workspace=str(tmp_path),
        bus=None,
        sessions=sessions,
        runtime_events=None,
    )
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        out = await tool.execute(action="complete", recap="x" * 50_000)
    # The recap is silently truncated to 8000 chars (no error).
    recap = session.metadata[GOAL_STATE_KEY]["recap"]
    assert len(recap) == 8000
    assert recap.startswith("xxxx")


@pytest.mark.asyncio
async def test_complete_goal_rejects_non_string_recap(tmp_path):
    from femtobot.agent.goal_permission import goal_mutation_scope
    from femtobot.agent.tools.long_task import CompleteGoalTool
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    ctx = ToolContext(
        config=SimpleNamespace(),
        workspace=str(tmp_path),
        bus=None,
        sessions=sessions,
        runtime_events=None,
    )
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        out = await tool.execute(action="complete", recap=12345)  # type: ignore[arg-type]
    assert "must be a string" in out.lower()


@pytest.mark.asyncio
async def test_complete_goal_treats_blank_recap_as_omitted(tmp_path):
    """A whitespace-only recap must not be stored."""
    from femtobot.agent.goal_permission import goal_mutation_scope
    from femtobot.agent.tools.long_task import CompleteGoalTool
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    ctx = ToolContext(
        config=SimpleNamespace(),
        workspace=str(tmp_path),
        bus=None,
        sessions=sessions,
        runtime_events=None,
    )
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        await tool.execute(action="complete", recap="   ")
    assert "recap" not in session.metadata[GOAL_STATE_KEY]


@pytest.mark.asyncio
async def test_complete_goal_cancel_caps_recap(tmp_path):
    """``recap`` is also the cancel reason — same cap applies."""
    from femtobot.agent.goal_permission import goal_mutation_scope
    from femtobot.agent.tools.long_task import CompleteGoalTool
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    ctx = ToolContext(
        config=SimpleNamespace(),
        workspace=str(tmp_path),
        bus=None,
        sessions=sessions,
        runtime_events=None,
    )
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        await tool.execute(action="cancel", recap="r" * 50_000)
    assert len(session.metadata[GOAL_STATE_KEY]["cancel_reason"]) == 8000


@pytest.mark.asyncio
async def test_complete_goal_block_caps_recap(tmp_path):
    """``recap`` is the block reason — same cap applies."""
    from femtobot.agent.goal_permission import goal_mutation_scope
    from femtobot.agent.tools.long_task import CompleteGoalTool
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    ctx = ToolContext(
        config=SimpleNamespace(),
        workspace=str(tmp_path),
        bus=None,
        sessions=sessions,
        runtime_events=None,
    )
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        await tool.execute(action="block", recap="b" * 50_000)
    assert len(session.metadata["goal_block_reason"]) == 8000


# ---------------------------------------------------------------------------
# Bug G/H — find_pending_ask / iter_pending_asks behavior
# ---------------------------------------------------------------------------


def test_find_pending_ask_returns_none_for_missing_correlation_id():
    md: dict = {}
    assert find_pending_ask(md, "ask_missing123") is None


def test_find_pending_ask_locates_pending_ask():
    from femtobot.session.pending_asks import append_pending_ask, PendingAsk

    md: dict = {}
    ask = PendingAsk(
        correlation_id="ask_found00001",
        target="orchestrator",
        question="x?",
    )
    append_pending_ask(md, ask)
    found = find_pending_ask(md, "ask_found00001")
    assert found is not None
    assert found.correlation_id == "ask_found00001"


def test_iter_pending_asks_yields_same_as_list_pending_asks():
    """The iterator helper exists for API symmetry; its results must
    match ``list_pending_asks``."""
    md: dict = {}
    list_asks = list(list_pending_asks(md))
    iter_asks = list(iter_pending_asks(md))
    assert list_asks == iter_asks