"""Regression tests for the *second* code-review pass.

Each test pins a specific bug fix so future refactors do not silently
reintroduce the issue.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from femtobot.agent.tools.context import ToolContext
from femtobot.api.goal_handlers import (
    AsyncGoalAccepted,
    AsyncGoalRequest,
    GoalRegistry,
    handle_create_goal,
    handle_goal_events,
    handle_post_answer,
    register_goal_routes,
)
from femtobot.api.goal_runtime import (
    GoalEvent,
    GoalEventKind,
    GoalJobStatus,
    create_goal_job,
    merge_events,
    serialize_goal_event,
    terminal_status,
)
from femtobot.api.goal_schemas import AsyncGoalAnswerRequest
from femtobot.session.goal_state import (
    GOAL_STATE_KEY,
    explicit_goal_requested,
    goal_state_runtime_lines,
    implicit_goal_requested,
    is_self_contained_objective,
    sustained_goal_active,
)
from femtobot.session.pending_asks import (
    AskStatus,
    AskTarget,
    PendingAsk,
    append_pending_ask,
    generate_correlation_id,
    list_pending_asks,
    update_pending_ask,
    validate_question_payload,
)


# ---------------------------------------------------------------------------
# Fix #1 — _parse_iso tolerates malformed strings
# ---------------------------------------------------------------------------


def test_goal_job_elapsed_s_tolerates_malformed_created_at():
    """When ``created_at`` is corrupted, ``elapsed_s`` must not crash."""
    job = create_goal_job(session_key="api:w")
    # Force a bad timestamp.
    job.created_at = "not-an-iso-string"
    assert job.elapsed_s() == 0.0


def test_goal_job_elapsed_s_tolerates_non_string_created_at():
    """Non-string timestamps must not crash the elapsed-time calc."""
    job = create_goal_job(session_key="api:w")
    job.created_at = None  # type: ignore[assignment]
    assert job.elapsed_s() == 0.0


# ---------------------------------------------------------------------------
# Fix #3 — update_status uses ISO with milliseconds
# ---------------------------------------------------------------------------


def test_goal_registry_update_status_uses_iso_with_milliseconds():
    reg = GoalRegistry()
    job = reg.create(session_key="api:w")
    before = job.updated_at
    time.sleep(0.005)
    reg.update_status(job.goal_id, GoalJobStatus.RUNNING)
    after = job.updated_at
    iso_ms_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    assert iso_ms_re.match(after), after
    assert after != before


# ---------------------------------------------------------------------------
# Fix #4 — handle_create_goal validates body field types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_create_goal_rejects_non_object_body(tmp_path):
    """A JSON array body must be rejected with a clear 400 — the previous
    implementation crashed with a confusing ``TypeError``."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # aiohttp test client doesn't let us send arbitrary JSON without
        # a Content-Type, so use json= and content_type via post.
        import aiohttp

        async with client.post(
            "/v1/goals",
            data="[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        ) as resp:
            assert resp.status == 400
            body = await resp.json()
            assert "object" in body["error"]["message"].lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_create_goal_rejects_messages_as_object():
    """``messages`` must be a list — an object would silently produce a junk
    list of keys under ``list({...})``."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            "/v1/goals",
            json={
                "session_id": "worker-1",
                "messages": {"role": "user", "content": "hi"},
            },
        ) as resp:
            assert resp.status == 400
            body = await resp.json()
            assert "list" in body["error"]["message"].lower()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_create_goal_rejects_metadata_as_array():
    """``metadata`` must be an object."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            "/v1/goals",
            json={
                "session_id": "worker-1",
                "messages": [{"role": "user", "content": "hi"}],
                "metadata": [1, 2, 3],
            },
        ) as resp:
            assert resp.status == 400
            body = await resp.json()
            assert "object" in body["error"]["message"].lower()
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Fix #5 — handle_post_answer serializes concurrent answers per goal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_post_answer_rejects_double_answer(tmp_path):
    """When two answer requests race for the same pending ask, only one
    must succeed; the second must get a 409 instead of enqueuing a
    second resume inbound."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from femtobot.session.manager import SessionManager

    app = web.Application()
    register_goal_routes(app)
    sessions = SessionManager(tmp_path)
    registry: GoalRegistry = app["goal_registry"]
    job = registry.create(session_key="api:worker-1")
    session = sessions.get_or_create("api:worker-1")
    cid = "ask_race1234"
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

    published: list = []

    async def _capture(msg):
        published.append(msg)

    class _LoopStub:
        bus = SimpleNamespace(
            publish_inbound=_capture,
        )

        @property
        def sessions(self):
            return sessions

    app["agent_loop"] = _LoopStub()

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # First request: should succeed.
        async with client.post(
            f"/v1/goals/{job.goal_id}/answer",
            json={"correlation_id": cid, "response": "first"},
        ) as r1:
            assert r1.status == 200
        # Second request (concurrent or sequential): the ask is now answered.
        async with client.post(
            f"/v1/goals/{job.goal_id}/answer",
            json={"correlation_id": cid, "response": "second"},
        ) as r2:
            # The fallback path matches any pending ask; the first answer
            # already moved the ask to ANSWERED, so the second call has no
            # target → 409.
            assert r2.status == 409, await r2.text()
        # Exactly one inbound published
        assert len(published) == 1
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Fix #6 — handle_goal_events supports replay + idle heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_goal_events_replays_history_then_closes_when_terminal():
    """If the goal is already terminal, the events endpoint must replay
    the history and close — no hanging connection."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    registry: GoalRegistry = app["goal_registry"]
    job = registry.create(session_key="api:w")
    registry.update_status(job.goal_id, GoalJobStatus.RUNNING)
    registry.update_status(job.goal_id, GoalJobStatus.COMPLETE)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.get(f"/v1/goals/{job.goal_id}/events") as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type", "").startswith("application/x-ndjson")
            body = await resp.read()
        # History replayed + terminal close marker
        lines = body.decode("utf-8").splitlines()
        # Replay contains at least the created + final event (status_changed +
        # final both carry FINAL payload).
        non_empty = [ln for ln in lines if ln.strip()]
        assert len(non_empty) >= 3
        parsed = [json.loads(ln) for ln in non_empty]
        kinds = {e["kind"] for e in parsed}
        assert "goal_created" in kinds
        assert "status_changed" in kinds
        assert "final" in kinds
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_goal_events_rejects_out_of_range_idle_timeout():
    """The idle_timeout_s parameter is clamped to [0, 600] — garbage
    values must not crash the handler.  Use a terminal goal so the
    handler returns immediately without streaming forever."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    registry: GoalRegistry = app["goal_registry"]
    job = registry.create(session_key="api:w")
    # Make the goal terminal so the handler closes immediately.
    registry.update_status(job.goal_id, GoalJobStatus.COMPLETE)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        # Very large idle timeout should be clamped to 600.
        async with client.get(
            f"/v1/goals/{job.goal_id}/events?idle_timeout_s=999999"
        ) as resp:
            assert resp.status == 200
            await resp.read()
        # Non-numeric falls back to default.
        async with client.get(
            f"/v1/goals/{job.goal_id}/events?idle_timeout_s=notanumber"
        ) as resp:
            assert resp.status == 200
            await resp.read()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_goal_events_replay_zero_skips_history():
    """``?replay=0`` must skip the historical replay and start streaming."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    registry: GoalRegistry = app["goal_registry"]
    job = registry.create(session_key="api:w")
    registry.update_status(job.goal_id, GoalJobStatus.COMPLETE)

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.get(
            f"/v1/goals/{job.goal_id}/events?replay=0"
        ) as resp:
            assert resp.status == 200
            body = await resp.read()
        # With replay=0 only the trailing newline + EOF — no history.
        non_empty = [ln for ln in body.decode("utf-8").splitlines() if ln.strip()]
        assert non_empty == []
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Fix #7 — process_direct rejects invalid execution_mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_direct_rejects_invalid_execution_mode(tmp_path):
    """An unknown execution_mode value must raise ValueError rather than
    silently falling back to sync (which would bypass the long-task queue)."""
    from femtobot.agent.loop import AgentLoop
    from femtobot.bus.queue import MessageBus

    class _StubProvider:
        generation = SimpleNamespace(max_tokens=8192)

        def get_default_model(self) -> str:
            return "stub"

        async def chat(self, *args, **kwargs):
            return None

        async def chat_stream(self, *args, **kwargs):
            yield None

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
    )
    with pytest.raises(ValueError) as exc_info:
        await loop.process_direct(
            content="X",
            session_key="cli:direct",
            execution_mode="goal-aware",  # typo: hyphen instead of underscore
        )
    assert "Invalid execution_mode" in str(exc_info.value)


@pytest.mark.asyncio
async def test_process_direct_accepts_sync_and_goal_aware(tmp_path, monkeypatch):
    """``sync`` and ``goal_aware`` must both pass validation."""
    from femtobot.agent.loop import AgentLoop
    from femtobot.bus.queue import MessageBus

    class _StubProvider:
        generation = SimpleNamespace(max_tokens=8192)

        def get_default_model(self) -> str:
            return "stub"

        async def chat(self, *args, **kwargs):
            return None

        async def chat_stream(self, *args, **kwargs):
            yield None

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
    )

    async def _stub(msg, **kwargs):
        return None

    async def _acquire_lock(key):
        class _Ctx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        return _Ctx()

    class _StubRE:
        def run_status_changed(self, *a, **kw):
            class _Awaitable:
                def __await__(self):
                    return iter(())

            return _Awaitable()

        def clear_turn(self, *a, **kw):
            return None

    monkeypatch.setattr(loop, "_process_message", _stub)
    monkeypatch.setattr(loop, "_connect_mcp", lambda: asyncio.sleep(0))
    monkeypatch.setattr(loop, "_acquire_session_lock", _acquire_lock)
    monkeypatch.setattr(loop, "_runtime_events", lambda: _StubRE())

    # Both must succeed (no raise)
    for mode in ("sync", "goal_aware"):
        await loop.process_direct(
            content="X", session_key="cli:direct", execution_mode=mode
        )


# ---------------------------------------------------------------------------
# Fix #8 — ask_orchestrator options are bounded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_orchestrator_caps_options_at_100(tmp_path):
    """An LLM passing 1000+ options must not bloat session metadata."""
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

    options = ",".join(f"option-{i}" for i in range(500))
    await tool.execute(question="pick one", options=options)
    asks = list_pending_asks(session.metadata)
    assert len(asks) == 1
    assert len(asks[0].options) <= 100


@pytest.mark.asyncio
async def test_ask_orchestrator_truncates_long_option(tmp_path):
    """An option string longer than 200 chars is truncated to 200."""
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

    await tool.execute(question="pick one", options="a," + ("x" * 500) + ",c")
    asks = list_pending_asks(session.metadata)
    opts = asks[0].options
    # a, x... (200), c
    assert len(opts) == 3
    assert opts[0] == "a"
    assert len(opts[1]) == 200
    assert opts[2] == "c"


# ---------------------------------------------------------------------------
# Fix #9 — validate_question_payload rejects non-string context
# ---------------------------------------------------------------------------


def test_validate_question_payload_rejects_non_string_context():
    err = validate_question_payload(
        question="Q?",
        context=12345,  # type: ignore[arg-type]
        timeout_s=60,
    )
    assert err is not None
    assert "context" in err.lower()
    assert "string" in err.lower()


def test_validate_question_payload_rejects_boolean_context():
    err = validate_question_payload(
        question="Q?",
        context=True,  # type: ignore[arg-type]
        timeout_s=60,
    )
    assert err is not None and "context" in err.lower()


# ---------------------------------------------------------------------------
# Fix #12 — explicit_goal_requested semantics (already covered by M1 tests)
# ---------------------------------------------------------------------------


def test_explicit_and_implicit_are_mutually_exclusive_for_marked_metadata():
    """``explicit_goal_requested`` must NOT trigger on bare ``goal_requested``;
    that's the implicit predicate's job."""
    md = {"goal_requested": True, "original_command": "regular-message"}
    assert explicit_goal_requested(md) is False
    # Implicit without the dedicated flag is False too:
    assert implicit_goal_requested(md) is False

    md_implicit = {"goal_requested_implicitly": True}
    assert implicit_goal_requested(md_implicit) is True
    assert explicit_goal_requested(md_implicit) is False

    md_explicit = {"original_command": "/goal"}
    assert explicit_goal_requested(md_explicit) is True
    assert implicit_goal_requested(md_explicit) is False


# ---------------------------------------------------------------------------
# Fix #13 — merge_events stable tie-breaker
# ---------------------------------------------------------------------------


def test_merge_events_uses_event_id_as_tie_breaker():
    """When two events share the same timestamp, the one minted first
    (lower event_id) must come first in the merged output — keeps the
    ordering deterministic across runs."""
    e1 = GoalEvent.new(goal_id="g", kind=GoalEventKind.LOG)
    # Mint e2 with the same timestamp by direct construction.
    e2 = GoalEvent(
        event_id="evt_zzzzzzzzzzzz",
        goal_id="g",
        kind=GoalEventKind.LOG,
        occurred_at=e1.occurred_at,
        data={"x": 1},
    )
    merged = merge_events([e1], [e2])
    assert merged[0].event_id == e1.event_id
    assert merged[1].event_id == e2.event_id


# ---------------------------------------------------------------------------
# Fix #18 — handle_post_answer publishes inbound with full metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_post_answer_includes_response_in_metadata(tmp_path):
    """The synthesized inbound must carry the response in metadata
    (so the worker can read it without re-parsing content)."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from femtobot.session.manager import SessionManager

    app = web.Application()
    register_goal_routes(app)
    sessions = SessionManager(tmp_path)
    registry: GoalRegistry = app["goal_registry"]
    job = registry.create(session_key="api:worker-1")
    session = sessions.get_or_create("api:worker-1")
    cid = "ask_meta12345"
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

    captured = []

    async def _capture(msg):
        captured.append(msg)

    class _LoopStub:
        bus = SimpleNamespace(
            publish_inbound=_capture,
        )

        @property
        def sessions(self):
            return sessions

    app["agent_loop"] = _LoopStub()

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            f"/v1/goals/{job.goal_id}/answer",
            json={"correlation_id": cid, "response": "Approved"},
        ) as resp:
            assert resp.status == 200
        assert len(captured) == 1
        assert captured[0].metadata["ask_answer_correlation_id"] == cid
        assert captured[0].metadata["ask_answer_response"] == "Approved"
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Regression — verify the typed metadata object survives JSON round-trip
# ---------------------------------------------------------------------------


def test_async_goal_request_round_trip_with_typed_payload():
    """Round-trip a fully-typed payload and verify the validator agrees."""
    req = AsyncGoalRequest(
        model="anthropic/claude-opus-4-5",
        messages=[{"role": "user", "content": "hi"}],
        session_id="worker-1",
        objective=None,
        metadata={"trace_id": "abc"},
        stream=False,
    )
    assert req.validate() is None
    # missing session_id fails
    req.session_id = None
    assert req.validate() is not None


def test_async_goal_answer_request_validates_response_against_empty():
    """Empty or whitespace-only response is rejected with a clear error."""
    for empty in ("", "   ", None):
        payload = AsyncGoalAnswerRequest(response=empty)  # type: ignore[arg-type]
        err = payload.validate()
        assert err is not None and "response" in err.lower()


# ---------------------------------------------------------------------------
# Sustained goal predicates survive metadata=None
# ---------------------------------------------------------------------------


def test_sustained_goal_active_tolerates_none_metadata():
    assert sustained_goal_active(None) is False
    assert sustained_goal_active({}) is False


def test_goal_state_runtime_lines_returns_empty_for_unknown_status():
    md = {GOAL_STATE_KEY: {"status": "unknown"}}
    assert goal_state_runtime_lines(md) == []


# ---------------------------------------------------------------------------
# PendingAsk.from_dict hostile inputs
# ---------------------------------------------------------------------------


def test_pending_ask_from_dict_handles_missing_keys():
    """A payload with no keys must produce a valid PendingAsk with
    defaults, not raise."""
    ask = PendingAsk.from_dict({})
    assert ask.status is AskStatus.PENDING
    assert ask.target is AskTarget.ORCHESTRATOR
    assert ask.options == []


def test_pending_ask_from_dict_ignores_non_string_status():
    """Non-string status payloads must fall back to PENDING, not crash."""
    ask = PendingAsk.from_dict({"status": 42, "correlation_id": "ask_xyz1234"})
    assert ask.status is AskStatus.PENDING


def test_pending_ask_from_dict_ignores_garbage_target():
    ask = PendingAsk.from_dict({"target": None, "correlation_id": "ask_xyz1234"})
    assert ask.target is AskTarget.ORCHESTRATOR


# ---------------------------------------------------------------------------
# AsyncGoalAccepted.to_dict and AsyncGoalStatus.to_dict shape
# ---------------------------------------------------------------------------


def test_async_goal_accepted_to_dict_includes_status():
    payload = AsyncGoalAccepted(
        session_id="w",
        goal_id="g",
        poll_url="p",
        events_url="e",
        answer_url="a",
        accepted_at="t",
    )
    d = payload.to_dict()
    assert d["status"] == "accepted"
    assert set(d.keys()) == {
        "status",
        "session_id",
        "goal_id",
        "poll_url",
        "events_url",
        "answer_url",
        "accepted_at",
    }


# ---------------------------------------------------------------------------
# is_self_contained_objective edge cases
# ---------------------------------------------------------------------------


def test_self_contained_objective_rejects_whitespace_only():
    assert is_self_contained_objective("   ") is False
    assert is_self_contained_objective("\n\t") is False


def test_self_contained_objective_treats_newlines_as_whitespace():
    assert is_self_contained_objective("\n  Refactor X\n") is True


def test_self_contained_objective_allow_questions_bypasses_heuristic():
    """``allow_questions=True`` accepts everything non-empty."""
    assert is_self_contained_objective("?", allow_questions=True) is True
    assert is_self_contained_objective("What?", allow_questions=True) is True