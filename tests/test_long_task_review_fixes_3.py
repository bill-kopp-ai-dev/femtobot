"""Regression tests for the *third* code-review pass.

Each test pins a specific bug fix so future refactors do not silently
reintroduce the issue.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from femtobot.agent.tools.context import ToolContext
from femtobot.api.goal_handlers import (
    GoalRegistry,
    handle_create_goal,
    handle_post_answer,
    register_goal_routes,
)
from femtobot.api.goal_runtime import GoalEvent, GoalJobStatus
from femtobot.session.goal_state import GOAL_STATE_KEY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_noop(*_args, **_kwargs):
    """Async no-op used by stub bus implementations."""


def _build_loop_with_sessions(tmp_path, captured_inbound=None):
    """Build a minimal stub ``agent_loop`` with a real ``SessionManager``
    and an optional inbound-capture list.  Returns ``(app, loop_stub)``.
    """
    from aiohttp import web

    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)

    async def _publish(msg):
        if captured_inbound is not None:
            captured_inbound.append(msg)

    class _LoopStub:
        bus = SimpleNamespace(publish_inbound=_publish)

        @property
        def sessions(self):
            return sessions

    app = web.Application()
    register_goal_routes(app)
    app["agent_loop"] = _LoopStub()
    return app, _LoopStub(), sessions


# ---------------------------------------------------------------------------
# Fix #1 — handle_post_answer persists session to disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_post_answer_persists_answer_to_disk(tmp_path):
    """After a successful /answer, the pending ask must be reflected in
    the on-disk session file (not just in memory)."""
    from aiohttp.test_utils import TestClient, TestServer

    captured: list = []
    app, _, _ = _build_loop_with_sessions(tmp_path, captured_inbound=captured)

    registry: GoalRegistry = app["goal_registry"]
    job = registry.create(session_key="api:worker-1")
    session = app["agent_loop"].sessions.get_or_create("api:worker-1")
    cid = "ask_persist0001"
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "pending_asks": [
            {
                "correlation_id": cid,
                "target": "orchestrator",
                "question": "Q?",
                "options": [],
                "status": "pending",
                "created_at": "2026-07-13T12:00:00.000Z",
                "deadline_at": "2026-07-13T13:00:00.000Z",
                "answered_at": None,
                "response": None,
                "goal_id": None,
                "session_key": "api:worker-1",
            }
        ],
    }

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            f"/v1/goals/{job.goal_id}/answer",
            json={"correlation_id": cid, "response": "Approved"},
        ) as resp:
            assert resp.status == 200

        # Drop the in-memory cache and re-load — the answer must be on disk.
        app["agent_loop"].sessions._cache.clear()
        reloaded = app["agent_loop"].sessions.get_or_create("api:worker-1")
        asks_raw = reloaded.metadata.get("pending_asks") or []
        assert asks_raw
        target = next(a for a in asks_raw if a["correlation_id"] == cid)
        assert target["status"] == "answered"
        assert target["response"] == "Approved"
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Fix #12 — handle_post_answer AWAITs publish_inbound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_post_answer_awaits_publish_inbound(tmp_path):
    """Regression: the handler must await ``publish_inbound`` — otherwise
    the inbound is silently lost.  A mock that returns a non-async value
    must crash loudly, not silently swallow the call."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from femtobot.session.manager import SessionManager

    app = web.Application()
    register_goal_routes(app)
    sessions = SessionManager(tmp_path)
    registry: GoalRegistry = app["goal_registry"]
    job = registry.create(session_key="api:worker-1")
    session = sessions.get_or_create("api:worker-1")
    cid = "ask_await00001"
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "pending_asks": [
            {
                "correlation_id": cid,
                "target": "orchestrator",
                "question": "Q?",
                "options": [],
                "status": "pending",
                "created_at": "2026-07-13T12:00:00.000Z",
                "deadline_at": "2026-07-13T13:00:00.000Z",
                "answered_at": None,
                "response": None,
                "goal_id": None,
                "session_key": "api:worker-1",
            }
        ],
    }

    # Stub bus with a sync ``publish_inbound`` — must surface TypeError.
    class _LoopStub:
        bus = SimpleNamespace(publish_inbound=lambda *a, **kw: None)

        @property
        def sessions(self):
            return sessions

    app["agent_loop"] = _LoopStub()

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            f"/v1/goals/{job.goal_id}/answer",
            json={"correlation_id": cid, "response": "yes"},
        ) as resp:
            # The handler raises a TypeError (awaiting None), aiohttp
            # returns 500.  The point is: it does NOT silently succeed.
            assert resp.status == 500
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Fix #4 — handle_create_goal publishes bootstrap inbound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_create_goal_publishes_bootstrap_inbound(tmp_path):
    """The admission endpoint must publish an inbound that the agent
    loop picks up — otherwise the goal sits idle."""
    from aiohttp.test_utils import TestClient, TestServer

    captured: list = []
    app, _, _ = _build_loop_with_sessions(tmp_path, captured_inbound=captured)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            "/v1/goals",
            json={
                "session_id": "worker-bootstrap",
                "objective": "Ship the v1 release",
            },
        ) as resp:
            assert resp.status == 202
            body = await resp.json()
            goal_id = body["goal_id"]
        # The bootstrap inbound reached the bus.
        assert len(captured) == 1
        msg = captured[0]
        assert msg.metadata["async_goal_id"] == goal_id
        assert msg.metadata["original_command"] == "/goal"
        assert "Ship the v1 release" in msg.content
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_create_goal_falls_back_to_messages_when_no_objective(tmp_path):
    """When the caller passes ``messages`` instead of ``objective``,
    the bootstrap inbound joins them into a single content seed."""
    from aiohttp.test_utils import TestClient, TestServer

    captured: list = []
    app, _, _ = _build_loop_with_sessions(tmp_path, captured_inbound=captured)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            "/v1/goals",
            json={
                "session_id": "worker-messages",
                "messages": [
                    {"role": "user", "content": "First line"},
                    {"role": "user", "content": "Second line"},
                ],
            },
        ) as resp:
            assert resp.status == 202
        assert len(captured) == 1
        msg = captured[0]
        assert "First line" in msg.content
        assert "Second line" in msg.content
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_create_goal_admits_without_agent_loop(tmp_path):
    """When the app has no ``agent_loop`` bound, the endpoint still
    admits the goal — the operator can poll status and drive progress
    via /answer later."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    # Deliberately no ``app["agent_loop"]`` set.

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            "/v1/goals",
            json={"session_id": "orphan", "objective": "ship"},
        ) as resp:
            assert resp.status == 202
            body = await resp.json()
            assert body["status"] == "accepted"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_create_goal_marks_running_after_publish(tmp_path):
    """After publishing the bootstrap inbound, the job status must move
    from ``accepted`` to ``running``."""
    from aiohttp.test_utils import TestClient, TestServer

    captured: list = []
    app, _, _ = _build_loop_with_sessions(tmp_path, captured_inbound=captured)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            "/v1/goals",
            json={"session_id": "worker-3", "objective": "ship"},
        ) as resp:
            body = await resp.json()
            goal_id = body["goal_id"]
        async with client.get(f"/v1/goals/{goal_id}") as resp2:
            status = await resp2.json()
        assert status["status"] == "running"
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Fix #5 — cmd_goal_status formats started_at as ISO
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_goal_status_formats_started_at_as_iso(tmp_path):
    """``Started at (UTC): <ISO>`` instead of the previous
    ``Started at: <epoch>``."""
    from types import SimpleNamespace

    from femtobot.command.builtin import cmd_goal_status
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    epoch = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    session.metadata = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "ship",
            "created_at": "2026-07-13T12:00:00.000Z",
        },
        "goal_started_at": epoch,
    }
    msg = SimpleNamespace(
        channel="cli",
        chat_id="chat-1",
        metadata={"render_as": "text"},
        content="",
    )
    ctx = SimpleNamespace(args="status", raw="/goal status", msg=msg, session=session)
    out = await cmd_goal_status(ctx)
    assert "Started at (UTC):" in out.content
    assert "2026-07-13T12:00:00.000Z" in out.content
    assert "Started at: `" not in out.content


# ---------------------------------------------------------------------------
# Fix #6 — cmd_goal persists goal blob to disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_goal_persists_goal_blob_to_disk(tmp_path):
    """``/goal <objective>`` must save the new blob to disk before the
    loop sees the inbound — otherwise a crash between the slash command
    and the next turn would lose the goal."""
    from types import SimpleNamespace

    from femtobot.command.builtin import cmd_goal
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    msg = SimpleNamespace(
        channel="cli",
        chat_id="chat-1",
        metadata={"render_as": "text"},
        content="",
    )
    loop = SimpleNamespace(sessions=sessions)
    ctx = SimpleNamespace(
        args="Ship the v1 release",
        raw="/goal Ship the v1 release",
        msg=msg,
        session=session,
        loop=loop,
    )
    out = await cmd_goal(ctx)
    # ``cmd_goal`` returns None (hands off to the runner).
    assert out is None

    # Drop the in-memory cache and re-load — the goal must be on disk.
    sessions._cache.clear()
    reloaded = sessions.get_or_create("cli:chat-1")
    assert reloaded.metadata.get(GOAL_STATE_KEY, {}).get("objective") == "Ship the v1 release"


@pytest.mark.asyncio
async def test_cmd_goal_complete_persists_terminal_state(tmp_path):
    """``/goal complete [recap]`` must save the terminal state to disk."""
    from types import SimpleNamespace

    from femtobot.command.builtin import cmd_goal_complete
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "ship",
            "created_at": "2026-07-13T12:00:00.000Z",
        },
    }
    msg = SimpleNamespace(
        channel="cli",
        chat_id="chat-1",
        metadata={"render_as": "text"},
        content="",
    )
    loop = SimpleNamespace(sessions=sessions)
    ctx = SimpleNamespace(
        args="finished",
        raw="/goal complete finished",
        msg=msg,
        session=session,
        loop=loop,
    )
    await cmd_goal_complete(ctx)
    sessions._cache.clear()
    reloaded = sessions.get_or_create("cli:chat-1")
    assert reloaded.metadata[GOAL_STATE_KEY]["status"] == "completed"
    assert reloaded.metadata[GOAL_STATE_KEY]["recap"] == "finished"


@pytest.mark.asyncio
async def test_cmd_goal_cancel_persists_cancelled_state(tmp_path):
    """``/goal cancel [reason]`` must save the cancelled state to disk."""
    from types import SimpleNamespace

    from femtobot.command.builtin import cmd_goal_cancel
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "ship",
            "created_at": "2026-07-13T12:00:00.000Z",
        },
    }
    msg = SimpleNamespace(
        channel="cli",
        chat_id="chat-1",
        metadata={"render_as": "text"},
        content="",
    )
    loop = SimpleNamespace(sessions=sessions)
    ctx = SimpleNamespace(
        args="lost interest",
        raw="/goal cancel lost interest",
        msg=msg,
        session=session,
        loop=loop,
    )
    await cmd_goal_cancel(ctx)
    sessions._cache.clear()
    reloaded = sessions.get_or_create("cli:chat-1")
    assert reloaded.metadata[GOAL_STATE_KEY]["status"] == "cancelled"
    assert reloaded.metadata[GOAL_STATE_KEY]["cancel_reason"] == "lost interest"


@pytest.mark.asyncio
async def test_cmd_goal_block_persists_blocked_state(tmp_path):
    """``/goal block [reason]`` must save the blocked state to disk."""
    from types import SimpleNamespace

    from femtobot.command.builtin import cmd_goal_block
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "ship",
            "created_at": "2026-07-13T12:00:00.000Z",
        },
    }
    msg = SimpleNamespace(
        channel="cli",
        chat_id="chat-1",
        metadata={"render_as": "text"},
        content="",
    )
    loop = SimpleNamespace(sessions=sessions)
    ctx = SimpleNamespace(
        args="needs human",
        raw="/goal block needs human",
        msg=msg,
        session=session,
        loop=loop,
    )
    await cmd_goal_block(ctx)
    sessions._cache.clear()
    reloaded = sessions.get_or_create("cli:chat-1")
    assert reloaded.metadata[GOAL_STATE_KEY]["status"] == "blocked"
    assert reloaded.metadata["goal_block_reason"] == "needs human"


@pytest.mark.asyncio
async def test_cmd_goal_complete_uses_iso_completed_at(tmp_path):
    """``completed_at`` must be an ISO string with milliseconds, not an
    epoch float."""
    import re

    from types import SimpleNamespace

    from femtobot.command.builtin import cmd_goal_complete
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "ship",
            "created_at": "2026-07-13T12:00:00.000Z",
        },
    }
    msg = SimpleNamespace(
        channel="cli",
        chat_id="chat-1",
        metadata={"render_as": "text"},
        content="",
    )
    loop = SimpleNamespace(sessions=sessions)
    ctx = SimpleNamespace(
        args="done",
        raw="/goal complete done",
        msg=msg,
        session=session,
        loop=loop,
    )
    await cmd_goal_complete(ctx)
    completed_at = session.metadata[GOAL_STATE_KEY]["completed_at"]
    iso_ms_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    assert iso_ms_re.match(completed_at), completed_at


# ---------------------------------------------------------------------------
# Fix — ask_orchestrator persists ask to disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_orchestrator_persists_pending_ask_to_disk(tmp_path):
    """``ask_orchestrator`` must save the session so the ask survives a
    crash before the worker resumes."""
    from femtobot.agent.goal_permission import goal_mutation_scope
    from femtobot.agent.tools.ask_orchestrator import AskOrchestratorTool
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
    ctx.long_task_config = LongTaskConfig(max_goal_ask_attempts=0)
    session = sessions.get_or_create("cli:chat-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
    }
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))

    with goal_mutation_scope(True):
        await tool.execute(question="Pick A or B?")
    # Drop the in-memory cache and re-load.
    sessions._cache.clear()
    reloaded = sessions.get_or_create("cli:chat-1")
    asks_raw = reloaded.metadata.get("pending_asks") or []
    assert asks_raw
    assert asks_raw[0]["question"] == "Pick A or B?"
    assert asks_raw[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Fix — long_task tool persists goal blob to disk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_task_tool_persists_goal_blob_to_disk(tmp_path):
    """``long_task`` tool must save the new goal blob to disk so a crash
    before the next turn does not lose the bootstrap."""
    from femtobot.agent.goal_permission import goal_mutation_scope
    from femtobot.agent.tools.long_task import LongTaskTool
    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    ctx = ToolContext(
        config=SimpleNamespace(),
        workspace=str(tmp_path),
        bus=None,
        sessions=sessions,
        runtime_events=None,
    )
    tool = LongTaskTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))

    with goal_mutation_scope(True):
        await tool.execute(objective="Refactor X")
    sessions._cache.clear()
    reloaded = sessions.get_or_create("cli:chat-1")
    assert reloaded.metadata.get(GOAL_STATE_KEY, {}).get("objective") == "Refactor X"


@pytest.mark.asyncio
async def test_complete_goal_tool_persists_terminal_state_to_disk(tmp_path):
    """``complete_goal(action='complete')`` must save the terminal state
    to disk."""
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
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        await tool.execute(action="complete", recap="done")
    sessions._cache.clear()
    reloaded = sessions.get_or_create("cli:chat-1")
    assert reloaded.metadata[GOAL_STATE_KEY]["status"] == "completed"
    assert reloaded.metadata[GOAL_STATE_KEY]["recap"] == "done"


@pytest.mark.asyncio
async def test_replace_goal_tool_persists_replacement_to_disk(tmp_path):
    """``complete_goal(action='replace')`` must save the new objective."""
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
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(SimpleNamespace(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        await tool.execute(action="replace", objective="Refined objective")
    sessions._cache.clear()
    reloaded = sessions.get_or_create("cli:chat-1")
    assert reloaded.metadata[GOAL_STATE_KEY]["objective"] == "Refined objective"
    assert reloaded.metadata[GOAL_STATE_KEY]["previous_objective"] == "ship"


# ---------------------------------------------------------------------------
# Fix #17 — GoalRegistry event queue no longer silently unbounded
# ---------------------------------------------------------------------------


def test_goal_registry_publish_does_not_block_on_unbounded_queue():
    """An unbounded asyncio.Queue never raises QueueFull; the warning
    path is therefore unreachable in the default configuration.  This
    test verifies the publish path stays cheap and doesn't queue."""
    import asyncio

    reg = GoalRegistry()
    job = reg.create(session_key="api:w")
    # The queue already has 1 entry from the CREATED event in ``create()``.
    queue = reg.events_queue(job.goal_id)
    initial = queue.qsize()
    assert initial >= 1

    # ``put_nowait`` on an unbounded queue never raises — guards against
    # future changes that bound the queue without thinking through the
    # drop semantics.
    queue.put_nowait(GoalEvent.new(goal_id=job.goal_id, kind="log"))
    assert queue.qsize() == initial + 1
    # ``asyncio`` event loop integration: a coroutine can drain the queue.
    loop = asyncio.new_event_loop()
    try:
        async def _drain():
            return await queue.get()

        assert loop.run_until_complete(_drain()) is not None
    finally:
        loop.close()