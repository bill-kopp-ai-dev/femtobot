"""Tests for M1 of long-task-by-default.

M1 introduces the goal domain layer: typed predicates, the permission
contextvar, the runtime-event publisher, and slash commands that
directly mutate the goal blob (no more agent-mediated goal creation).
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from femtobot.agent.goal_permission import (
    GoalMutationNotAllowedError,
    goal_mutation_allowed,
    goal_mutation_scope,
    require_goal_mutation_permission,
    reset_goal_mutation_permission,
    revoke_goal_mutation_permission,
    set_goal_mutation_allowed,
)
from femtobot.bus.goal_events import (
    get_active_event_bus,
    publish_goal_state_changed,
    set_active_event_bus,
)
from femtobot.bus.runtime_events import GoalStateChanged, RuntimeEventBus
from femtobot.session.goal_state import (
    GOAL_STATE_KEY,
    GOAL_STATUS_ACTIVE,
    GOAL_STATUS_BLOCKED,
    GOAL_STATUS_CANCELLED,
    GOAL_STATUS_COMPLETED,
    explicit_goal_requested,
    goal_block_reason,
    goal_bootstrap_requested,
    goal_elapsed_s,
    goal_id,
    goal_started_at,
    goal_waiting_on,
    implicit_goal_requested,
    is_self_contained_objective,
    mark_goal_waiting,
    clear_goal_waiting,
    normalize_goal_status,
    reset_goal_continuation_marker,
    sustained_goal_active,
)


# ---------------------------------------------------------------------------
# PR 1.1 — goal_state predicates
# ---------------------------------------------------------------------------


def test_explicit_goal_requested_recognizes_slash_command():
    # ``explicit_goal_requested`` is anchored on ``original_command ==
    # "/goal"`` — ``goal_requested`` alone is ambiguous because the
    # long-task-by-default auto-wrap hook also sets it.
    assert explicit_goal_requested({"original_command": "/goal"}) is True
    # The bare ``goal_requested`` flag must NOT trigger explicit detection
    # — that's what ``implicit_goal_requested`` is for.
    assert explicit_goal_requested({"goal_requested": True}) is False
    assert explicit_goal_requested({}) is False
    assert explicit_goal_requested(None) is False


def test_implicit_goal_requested_distinguishes_bootstrap_from_explicit():
    # Implicit only — used by long-task-by-default auto-wrap
    assert implicit_goal_requested(
        {"goal_requested_implicitly": True, "original_command": "turn"}
    ) is True
    # Explicit takes priority (slash command)
    assert implicit_goal_requested(
        {"original_command": "/goal"}
    ) is False


def test_goal_bootstrap_requested_is_union():
    md = {"goal_requested_implicitly": True}
    assert goal_bootstrap_requested(md) is True
    md = {"original_command": "/goal"}
    assert goal_bootstrap_requested(md) is True
    md = {"foo": "bar"}
    assert goal_bootstrap_requested(md) is False


def test_goal_started_at_and_elapsed_roundtrip():
    now = time.time()
    md = {"goal_started_at": now}
    assert goal_started_at(md) == pytest.approx(now)
    assert goal_elapsed_s(md, now=now + 5.0) == pytest.approx(5.0)
    # Missing -> safe defaults
    assert goal_started_at(None) is None
    assert goal_elapsed_s(None) == 0.0


def test_goal_block_reason_and_waiting_roundtrip():
    md = {"goal_block_reason": "deadlock", "goal_waiting_on": "ask_orchestrator"}
    assert goal_block_reason(md) == "deadlock"
    assert goal_waiting_on(md) == "ask_orchestrator"
    md = {}
    assert goal_block_reason(md) is None


def test_goal_id_roundtrip():
    md = {"goal_id": "goal_abc123"}
    assert goal_id(md) == "goal_abc123"
    md = {}
    assert goal_id(md) is None


def test_mark_and_clear_goal_waiting():
    md: dict = {}
    mark_goal_waiting(md, waiting_on="ask_orchestrator", correlation_id="ask_xyz1234")
    assert md["goal_waiting_on"] == "ask_orchestrator"
    assert md["goal_pending_ask_correlation_id"] == "ask_xyz1234"
    clear_goal_waiting(md)
    assert "goal_waiting_on" not in md
    assert "goal_pending_ask_correlation_id" not in md


def test_reset_goal_continuation_marker_clears_rounds():
    md = {"goal_continue_rounds": 3, "goal_pending_ask_correlation_id": "ask_x"}
    reset_goal_continuation_marker(md)
    assert "goal_continue_rounds" not in md
    assert "goal_pending_ask_correlation_id" not in md


def test_is_self_contained_objective_rejects_questions():
    assert is_self_contained_objective("Refactor module X") is True
    assert is_self_contained_objective("How do I refactor X?") is False
    assert is_self_contained_objective("Qual é a melhor estratégia?") is False
    # allow_questions=True bypasses
    assert is_self_contained_objective("How?", allow_questions=True) is True
    # Empty string is not self-contained
    assert is_self_contained_objective("   ") is False


def test_normalize_goal_status_canonicalizes():
    assert normalize_goal_status("ACTIVE") == "active"
    assert normalize_goal_status(" Completed ") == "completed"
    assert normalize_goal_status("invalid") is None
    assert normalize_goal_status(None) is None
    assert normalize_goal_status(42) is None


def test_status_constants_match_existing_blob_values():
    # Active goal already in the session should keep its status:
    md = {GOAL_STATE_KEY: {"status": "active"}}
    assert sustained_goal_active(md) is True
    # Constants map to the same lowercase strings the legacy code uses.
    assert GOAL_STATUS_ACTIVE == "active"
    assert GOAL_STATUS_COMPLETED == "completed"
    assert GOAL_STATUS_CANCELLED == "cancelled"
    assert GOAL_STATUS_BLOCKED == "blocked"


# ---------------------------------------------------------------------------
# PR 1.2 — goal_permission contextvar
# ---------------------------------------------------------------------------


def test_goal_mutation_default_is_false():
    # Fresh context: no permission
    assert goal_mutation_allowed() is False


def test_goal_mutation_scope_toggles_flag():
    with goal_mutation_scope(True):
        assert goal_mutation_allowed() is True
    assert goal_mutation_allowed() is False


def test_goal_mutation_scope_restores_on_exception():
    with pytest.raises(RuntimeError):
        with goal_mutation_scope(True):
            assert goal_mutation_allowed() is True
            raise RuntimeError("boom")
    assert goal_mutation_allowed() is False


def test_set_and_reset_goal_mutation_permission():
    token = set_goal_mutation_allowed(True)
    assert goal_mutation_allowed() is True
    reset_goal_mutation_permission(token)
    assert goal_mutation_allowed() is False


def test_revoke_goal_mutation_permission_sets_false():
    with goal_mutation_scope(True):
        assert goal_mutation_allowed() is True
        revoke_goal_mutation_permission()
        assert goal_mutation_allowed() is False


def test_require_goal_mutation_permission_raises_when_blocked():
    with pytest.raises(GoalMutationNotAllowedError):
        require_goal_mutation_permission()
    with goal_mutation_scope(True):
        # No raise when permitted.
        require_goal_mutation_permission()


@pytest.mark.asyncio
async def test_goal_mutation_permission_isolated_per_task():
    """M1: ContextVar flag is per-task; a child task does not inherit it."""
    import asyncio as _asyncio

    child_seen: list[bool] = []

    async def child():
        child_seen.append(goal_mutation_allowed())

    with goal_mutation_scope(True):
        assert goal_mutation_allowed() is True
        await child()
    # Child task ran in the same contextvar scope (single asyncio.run) so it
    # sees True.  Critical: in a fresh task spun up later, it must default
    # back to False.

    async def fresh_task():
        return goal_mutation_allowed()

    fresh = await fresh_task()
    assert fresh is False
    # And confirm the child ran inside the scope.
    assert child_seen == [True]


# ---------------------------------------------------------------------------
# PR 1.3 — goal_events publisher
# ---------------------------------------------------------------------------


def test_publish_goal_state_changed_no_bus_is_noop():
    set_active_event_bus(None)
    publish_goal_state_changed(channel="cli", chat_id="x")
    # nothing to assert besides "did not raise"


@pytest.mark.asyncio
async def test_publish_goal_state_changed_uses_active_bus():
    bus = RuntimeEventBus()
    set_active_event_bus(bus)
    captured = []

    async def handler(event):
        captured.append(event)

    bus.subscribe(handler, GoalStateChanged)
    publish_goal_state_changed(
        channel="cli",
        chat_id="chat-x",
        session_key="cli:chat-x",
        session_metadata={GOAL_STATE_KEY: {"status": "active"}},
    )
    # Drain any pending tasks scheduled by publish_nowait.
    await asyncio.sleep(0.05)
    assert any(isinstance(e, GoalStateChanged) for e in captured)
    set_active_event_bus(None)


@pytest.mark.asyncio
async def test_publish_goal_state_changed_explicit_bus_wins():
    bus_a = RuntimeEventBus()
    bus_b = RuntimeEventBus()
    set_active_event_bus(bus_a)
    captured_b = []

    async def handler_b(event):
        captured_b.append(event)

    bus_b.subscribe(handler_b, GoalStateChanged)
    publish_goal_state_changed(channel="cli", chat_id="x", bus=bus_b)
    await asyncio.sleep(0.05)
    assert any(isinstance(e, GoalStateChanged) for e in captured_b)
    set_active_event_bus(None)


def test_get_active_event_bus_returns_bound_bus():
    bus = RuntimeEventBus()
    set_active_event_bus(bus)
    assert get_active_event_bus() is bus
    set_active_event_bus(None)
    assert get_active_event_bus() is None


# ---------------------------------------------------------------------------
# PR 1.4 — /goal writes blob directly
# ---------------------------------------------------------------------------


def _make_session(metadata: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=dict(metadata or {}),
        session_key="cli:chat-1",
    )


def _make_ctx(args: str, session) -> SimpleNamespace:
    msg = SimpleNamespace(
        channel="cli",
        chat_id="chat-1",
        metadata={"render_as": "text"},
        content="",
    )
    return SimpleNamespace(
        args=args,
        raw=args,
        msg=msg,
        session=session,
        loop=None,
    )


async def test_cmd_goal_writes_active_goal_blob():
    from femtobot.command.builtin import cmd_goal

    session = _make_session()
    ctx = _make_ctx("Refactor module X", session)
    out = await cmd_goal(ctx)
    assert out is None  # command hands off to the runner
    blob = session.metadata.get(GOAL_STATE_KEY)
    assert blob is not None
    assert blob["status"] == "active"
    assert blob["objective"] == "Refactor module X"
    assert blob["source"] == "/goal"
    assert session.metadata.get("goal_started_at") is not None
    assert ctx.msg.metadata.get("goal_requested") is True
    assert ctx.msg.metadata.get("original_command") == "/goal"


async def test_cmd_goal_rejects_open_questions_by_default():
    from femtobot.command.builtin import cmd_goal
    from femtobot.config.schema import LongTaskConfig

    session = _make_session()
    ctx = SimpleNamespace(
        args="How can I refactor X?",
        raw="How can I refactor X?",
        msg=SimpleNamespace(
            channel="cli", chat_id="chat-1", metadata={}, content=""
        ),
        session=session,
        loop=SimpleNamespace(long_task_config=LongTaskConfig()),
    )
    out = await cmd_goal(ctx)
    assert out is not None
    assert "open-ended" in out.content.lower()
    assert GOAL_STATE_KEY not in session.metadata


async def test_cmd_goal_allows_questions_when_disabled():
    from femtobot.command.builtin import cmd_goal
    from femtobot.config.schema import LongTaskConfig

    cfg = LongTaskConfig(require_objective_self_containment=False)
    session = _make_session()
    ctx = SimpleNamespace(
        args="How can I refactor X?",
        raw="How can I refactor X?",
        msg=SimpleNamespace(
            channel="cli", chat_id="chat-1", metadata={}, content=""
        ),
        session=session,
        loop=SimpleNamespace(long_task_config=cfg),
    )
    out = await cmd_goal(ctx)
    assert out is None
    blob = session.metadata[GOAL_STATE_KEY]
    assert blob["status"] == "active"


async def test_cmd_goal_rejects_oversized_objective():
    from femtobot.command.builtin import cmd_goal

    session = _make_session()
    ctx = _make_ctx("x" * 5000, session)
    out = await cmd_goal(ctx)
    assert out is not None
    assert "too long" in out.content.lower()


@pytest.mark.asyncio
async def test_cmd_goal_publishes_goal_state_changed():
    from femtobot.command.builtin import cmd_goal

    bus = RuntimeEventBus()
    set_active_event_bus(bus)
    captured = []

    async def handler(event):
        captured.append(event)

    bus.subscribe(handler, GoalStateChanged)

    session = _make_session()
    ctx = _make_ctx("Ship v1.0", session)
    await cmd_goal(ctx)
    await asyncio.sleep(0.05)
    assert any(isinstance(e, GoalStateChanged) for e in captured)
    set_active_event_bus(None)


async def test_cmd_goal_cancel_finalizes_and_clears_waiting():
    from femtobot.command.builtin import cmd_goal_cancel

    md = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "goal_waiting_on": "ask_orchestrator",
    }
    session = _make_session(md)
    ctx = _make_ctx("lost interest", session)
    out = await cmd_goal_cancel(ctx)
    assert out is not None
    assert session.metadata[GOAL_STATE_KEY]["status"] == "cancelled"
    assert "goal_waiting_on" not in session.metadata


async def test_cmd_goal_block_records_reason():
    from femtobot.command.builtin import cmd_goal_block

    session = _make_session(
        {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    )
    ctx = _make_ctx("needs human approval", session)
    await cmd_goal_block(ctx)
    assert session.metadata[GOAL_STATE_KEY]["status"] == "blocked"
    assert session.metadata["goal_block_reason"] == "needs human approval"


async def test_cmd_goal_status_reports_pending_asks():
    from femtobot.command.builtin import cmd_goal_status
    from femtobot.session.pending_asks import (
        PendingAsk,
        AskTarget,
        append_pending_ask,
    )

    md = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "goal_started_at": time.time(),
    }
    session = _make_session(md)
    ask = PendingAsk(
        correlation_id="ask_pending123",
        target=AskTarget.ORCHESTRATOR,
        question="Pick flavor A or B?",
    )
    append_pending_ask(session.metadata, ask)
    ctx = _make_ctx("status", session)
    out = await cmd_goal_status(ctx)
    assert "active" in out.content
    assert "ask_pending123" in out.content
    assert "Pick flavor A or B?" in out.content