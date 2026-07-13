"""Regression tests for issues found during the long-task-by-default
code review.

Each test pins a specific bug fix so future refactors do not silently
reintroduce the problem.
"""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest


async def _async_noop(*_args, **_kwargs):
    """Async no-op used by stub bus implementations."""

from femtobot.agent.tool_visibility import (
    complete_goal_visible,
    filter_tool_schemas_for_turn,
    long_task_visible,
)
from femtobot.agent.tools.context import RequestContext, ToolContext
from femtobot.api.goal_schemas import AsyncGoalAnswerRequest
from femtobot.session.goal_state import GOAL_STATE_KEY, sustained_goal_active
from femtobot.session.pending_asks import (
    AskStatus,
    PendingAsk,
    append_pending_ask,
    count_pending_asks,
    generate_correlation_id,
    list_pending_asks,
    update_pending_ask,
    validate_question_payload,
)


# ---------------------------------------------------------------------------
# ask_orchestrator — timestamps use ISO with milliseconds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_orchestrator_uses_iso_timestamps_with_milliseconds(tmp_path):
    """``created_at`` and ``deadline_at`` must be ISO strings with
    millisecond precision — the previous implementation used
    ``time.strftime`` twice which silently truncated milliseconds and
    could disagree by one second between the two timestamps."""
    from femtobot.agent.tools.ask_orchestrator import AskOrchestratorTool
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
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(RequestContext(channel="cli", chat_id="chat-1"))

    out = await tool.execute(question="Pick A or B?")
    assert "ask_" in out
    asks = list_pending_asks(session.metadata)
    assert len(asks) == 1
    ask = asks[0]

    iso_ms_re = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
    )
    assert iso_ms_re.match(ask.created_at), ask.created_at
    assert iso_ms_re.match(ask.deadline_at or ""), ask.deadline_at


@pytest.mark.asyncio
async def test_ask_orchestrator_created_at_matches_deadline_offset(tmp_path):
    """``deadline_at`` must equal ``created_at + timeout_s`` exactly."""
    from femtobot.agent.tools.ask_orchestrator import AskOrchestratorTool
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
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(RequestContext(channel="cli", chat_id="chat-1"))

    timeout_s = 600
    await tool.execute(question="Q?", timeoutS=str(timeout_s))
    ask = list_pending_asks(session.metadata)[0]
    # Both come from the same ``_now_iso_ms()`` call so created_at < deadline_at
    # by *exactly* the timeout interval.
    from datetime import datetime, timezone

    def _parse(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    delta = (_parse(ask.deadline_at) - _parse(ask.created_at)).total_seconds()
    assert delta == timeout_s


@pytest.mark.asyncio
async def test_ask_orchestrator_timeout_rejects_bool_to_prevent_1s_timeout(tmp_path):
    """``True`` as a timeout must NOT collapse to 1 second — ``int(True)==1``
    would silently bypass the 30-second lower bound."""
    from femtobot.agent.tools.ask_orchestrator import AskOrchestratorTool
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
    tool = AskOrchestratorTool.create(ctx)
    tool.set_context(RequestContext(channel="cli", chat_id="chat-1"))

    out = await tool.execute(question="Q?", timeoutS=True)  # type: ignore[arg-type]
    # bool rejected -> default 1800 used -> ask persisted with 1800s timeout
    assert "ask_" in out
    ask = list_pending_asks(session.metadata)[0]
    from datetime import datetime, timezone

    def _parse(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    delta = (_parse(ask.deadline_at) - _parse(ask.created_at)).total_seconds()
    assert delta == 1800


# ---------------------------------------------------------------------------
# pending_asks — tighten validation
# ---------------------------------------------------------------------------


def test_validate_question_payload_rejects_bool_timeout():
    """``True`` must not be coerced to 1 by ``int(True)``."""
    err = validate_question_payload(question="Q?", context=None, timeout_s=True)  # type: ignore[arg-type]
    assert err is not None and "timeoutS" in err


def test_validate_question_payload_accepts_30s_floor():
    err = validate_question_payload(question="Q?", context=None, timeout_s=30)
    assert err is None


def test_validate_question_payload_rejects_below_floor():
    err = validate_question_payload(question="Q?", context=None, timeout_s=29)
    assert err is not None


def test_validate_question_payload_rejects_above_ceiling():
    err = validate_question_payload(question="Q?", context=None, timeout_s=86_401)
    assert err is not None


# ---------------------------------------------------------------------------
# long_task — guards terminal state on CompleteGoalTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_goal_refuses_to_overwrite_terminal_status(tmp_path):
    """Calling ``complete`` on an already-completed goal must NOT silently
    rewrite history — instead it must refuse with a clear error."""
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
        GOAL_STATE_KEY: {
            "status": "completed",
            "objective": "ship",
            "completed_at": "2026-07-13T00:00:00.000Z",
            "recap": "done",
        },
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(RequestContext(channel="cli", chat_id="chat-1"))
    out = await tool.execute(action="complete", recap="second attempt")
    assert "already completed" in out.lower()
    # History preserved
    assert session.metadata[GOAL_STATE_KEY]["recap"] == "done"
    assert session.metadata[GOAL_STATE_KEY]["completed_at"] == "2026-07-13T00:00:00.000Z"


@pytest.mark.asyncio
async def test_complete_goal_replace_allowed_on_terminal_status(tmp_path):
    """``replace`` is the explicit recovery path — it must succeed even
    when the previous goal is terminal."""
    from femtobot.agent.tools.long_task import CompleteGoalTool
    from femtobot.agent.goal_permission import goal_mutation_scope
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
        GOAL_STATE_KEY: {
            "status": "completed",
            "objective": "ship",
        },
    }
    tool = CompleteGoalTool.create(ctx)
    tool.set_context(RequestContext(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        out = await tool.execute(action="replace", objective="Refined objective")
    assert "replaced" in out.lower()
    assert session.metadata[GOAL_STATE_KEY]["objective"] == "Refined objective"
    assert session.metadata[GOAL_STATE_KEY]["status"] == "active"


@pytest.mark.asyncio
async def test_long_task_blob_timestamps_are_iso_strings_with_milliseconds(tmp_path):
    """``created_at`` / ``updated_at`` on the new goal blob must be ISO
    with milliseconds (used by ``/goal status``), not epoch floats."""
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
    tool.set_context(RequestContext(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        await tool.execute(objective="Refactor X")
    session = sessions.get_or_create("cli:chat-1")
    blob = session.metadata[GOAL_STATE_KEY]
    iso_ms_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
    assert iso_ms_re.match(blob["created_at"]), blob["created_at"]
    assert iso_ms_re.match(blob["updated_at"]), blob["updated_at"]
    # ``goal_started_at`` keeps the epoch float for elapsed-time math
    assert isinstance(session.metadata["goal_started_at"], (int, float))


@pytest.mark.asyncio
async def test_long_task_ui_summary_trimmed_to_120_chars(tmp_path):
    """``ui_summary`` is trimmed and capped at 120 characters consistently."""
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
    tool.set_context(RequestContext(channel="cli", chat_id="chat-1"))
    summary_input = "  " + ("x" * 500) + "  "
    with goal_mutation_scope(True):
        await tool.execute(objective="Refactor X", ui_summary=summary_input)
    session = sessions.get_or_create("cli:chat-1")
    stored = session.metadata[GOAL_STATE_KEY]["ui_summary"]
    assert len(stored) == 120
    assert stored.startswith("x")


@pytest.mark.asyncio
async def test_long_task_blank_ui_summary_is_omitted(tmp_path):
    """Whitespace-only ``ui_summary`` should not be stored."""
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
    tool.set_context(RequestContext(channel="cli", chat_id="chat-1"))
    with goal_mutation_scope(True):
        await tool.execute(objective="Refactor X", ui_summary="   ")
    session = sessions.get_or_create("cli:chat-1")
    assert "ui_summary" not in session.metadata[GOAL_STATE_KEY]


# ---------------------------------------------------------------------------
# tool_visibility — by_default docstring + ordering
# ---------------------------------------------------------------------------


def test_tool_visibility_long_task_explicit_predicates_take_priority():
    """``goal_bootstrap_requested`` should win regardless of by_default."""
    cfg = SimpleNamespace(by_default=False)
    md = {"goal_requested_implicitly": True}
    assert long_task_visible(
        session_metadata={}, message_metadata=md, long_task_config=cfg
    ) is True


def test_tool_visibility_long_task_explicit_slash_command_visible():
    cfg = SimpleNamespace(by_default=False)
    md = {"original_command": "/goal"}
    assert long_task_visible(
        session_metadata={}, message_metadata=md, long_task_config=cfg
    ) is True


def test_tool_visibility_long_task_by_default_only_when_no_explicit_marker():
    cfg = SimpleNamespace(by_default=True)
    assert long_task_visible(
        session_metadata={}, message_metadata=None, long_task_config=cfg
    ) is True


def test_tool_visibility_complete_goal_visible_when_session_has_active_goal():
    md = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    assert complete_goal_visible(session_metadata=md) is True


def test_tool_visibility_complete_goal_hidden_when_terminal():
    for terminal in ("completed", "cancelled", "blocked"):
        md = {GOAL_STATE_KEY: {"status": terminal}}
        assert complete_goal_visible(session_metadata=md) is False


def test_filter_tool_schemas_combined_active_and_terminal_visibility():
    """When the session has an active goal, only ``complete_goal`` should be
    visible (not ``long_task``); when there's no goal, neither shows up."""
    cfg = SimpleNamespace(by_default=False)
    schemas = [
        {"name": "read_file"},
        {"name": "long_task"},
        {"name": "complete_goal"},
    ]
    md = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    names = [
        s["name"]
        for s in filter_tool_schemas_for_turn(
            schemas, session_metadata=md, message_metadata=None, long_task_config=cfg
        )
    ]
    assert "read_file" in names
    assert "complete_goal" in names
    assert "long_task" not in names


# ---------------------------------------------------------------------------
# runtime_context — format started_at as ISO
# ---------------------------------------------------------------------------


def test_runtime_context_started_at_is_iso_string_not_epoch_float():
    """The ``goal_active_block`` should expose ``Started at (UTC): ISO``
    instead of the previous ``Started at (epoch): 1720xxx.123`` form."""
    from datetime import datetime, timezone

    from femtobot.runtime_context import goal_active_block

    epoch = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    md = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "goal_started_at": epoch,
    }
    block = goal_active_block(md)
    assert block is not None
    text = block.to_text()
    assert "Started at (UTC):" in text
    assert "2026-07-13T12:00:00.000Z" in text
    # Old format must be gone
    assert "Started at (epoch):" not in text


# ---------------------------------------------------------------------------
# AsyncGoalAnswerRequest validates with payload validator
# ---------------------------------------------------------------------------


def test_async_goal_answer_request_rejects_empty_response():
    payload = AsyncGoalAnswerRequest(response="   ")
    err = payload.validate()
    assert err is not None and "response" in err


def test_async_goal_answer_request_rejects_oversized_response():
    payload = AsyncGoalAnswerRequest(response="x" * 16_001)
    err = payload.validate()
    assert err is not None and "exceeds" in err


# ---------------------------------------------------------------------------
# pending_asks — terminal states don't accept further transitions
# ---------------------------------------------------------------------------


def test_update_pending_ask_ignores_duplicate_pending_transition():
    """``update_pending_ask(..., status=PENDING)`` on a pending ask is a
    no-op — defensive so callers can safely call us after a resume."""
    md: dict = {}
    ask = PendingAsk(
        correlation_id=generate_correlation_id(),
        target="orchestrator",
        question="x?",
    )
    append_pending_ask(md, ask)
    ok = update_pending_ask(md, ask.correlation_id, status=AskStatus.PENDING)
    assert ok is False


def test_update_pending_ask_already_answered_cannot_be_re_answered():
    """Once an ask is ANSWERED, further transitions are ignored — keeps
    history clean."""
    md: dict = {}
    ask = PendingAsk(
        correlation_id=generate_correlation_id(),
        target="orchestrator",
        question="x?",
    )
    append_pending_ask(md, ask)
    update_pending_ask(
        md, ask.correlation_id, status=AskStatus.ANSWERED, response="A"
    )
    # second update with different response must be ignored
    update_pending_ask(
        md, ask.correlation_id, status=AskStatus.ANSWERED, response="B"
    )
    asks = list_pending_asks(md)
    assert asks[0].response == "A"


# ---------------------------------------------------------------------------
# cancelled pending asks don't count toward the ask budget
# ---------------------------------------------------------------------------


def test_cancelled_asks_do_not_count_toward_budget():
    """Cancelled asks must be excluded from the budget counter, otherwise
    the orchestrator could exhaust its own budget by cancelling a few."""
    md: dict = {}
    for i in range(3):
        append_pending_ask(
            md,
            PendingAsk(
                correlation_id=f"ask_pending{i:04d}",
                target="orchestrator",
                question=f"q{i}?",
            ),
        )
    for i in range(3):
        update_pending_ask(md, f"ask_pending{i:04d}", status=AskStatus.CANCELLED)
    assert count_pending_asks(md) == 0


# ---------------------------------------------------------------------------
# goal_handlers — typed update_pending_ask
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_post_answer_uses_typed_ask_status(tmp_path):
    """``handle_post_answer`` must accept ``AskStatus.ANSWERED`` not a
    string literal — regression check for the typed signature."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from femtobot.api.goal_handlers import (
        GoalRegistry,
        handle_post_answer,
        register_goal_routes,
    )
    from femtobot.session.manager import SessionManager

    # Set up minimal app + goal registry + session
    app = web.Application()
    register_goal_routes(app)
    sessions = SessionManager(tmp_path)
    registry: GoalRegistry = app["goal_registry"]
    session = sessions.get_or_create("api:worker-1")
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "pending_asks": [
            {
                "correlation_id": "ask_test1234",
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

    class _LoopStub:
        bus = SimpleNamespace(
            publish_inbound=_async_noop,
        )

        @property
        def sessions(self):
            return sessions

    app["agent_loop"] = _LoopStub()
    # Pre-register the goal so get() succeeds
    goal_id = registry.create(session_key="api:worker-1").goal_id

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.post(
            f"/v1/goals/{goal_id}/answer",
            json={
                "correlation_id": "ask_test1234",
                "response": "Approved",
            },
        )
        assert resp.status == 200, await resp.text()
        # The ask must now be ANSWERED with the response
        asks = list_pending_asks(session.metadata)
        assert asks[0].status is AskStatus.ANSWERED
        assert asks[0].response == "Approved"
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# pending_asks — pending list correctly excludes non-pending statuses
# ---------------------------------------------------------------------------


def test_list_pending_asks_round_trips_status_enum():
    """``from_dict`` must accept string statuses from JSON, hydrate them
    back into ``AskStatus`` so ``is`` comparisons keep working."""
    md = {
        "pending_asks": [
            {
                "correlation_id": "ask_test1111",
                "target": "orchestrator",
                "question": "q",
                "options": [],
                "status": "pending",
                "created_at": "2026-07-13T12:00:00.000Z",
            }
        ]
    }
    asks = list_pending_asks(md)
    assert asks[0].status is AskStatus.PENDING


# ---------------------------------------------------------------------------
# guard the public helper signatures (prevent future regressions)
# ---------------------------------------------------------------------------


def test_validate_question_payload_flags_string_question_too_long():
    """Strings longer than 4 000 chars must be rejected with a clear message."""
    err = validate_question_payload(
        question="x" * 4001, context=None, timeout_s=60
    )
    assert err is not None and "4000" in err


def test_validate_question_payload_flags_context_too_long():
    """Context longer than 8 000 chars must be rejected."""
    err = validate_question_payload(
        question="ok?", context="y" * 8001, timeout_s=60
    )
    assert err is not None and "8000" in err


def test_validate_question_payload_flags_non_string_timeout():
    err = validate_question_payload(question="ok?", context=None, timeout_s="abc")
    assert err is not None and "number" in err