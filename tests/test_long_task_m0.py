"""Smoke tests for M0 of the long-task-by-default refactor.

These tests only validate that the new code paths load without breaking
the existing behavior.  ``byDefault`` defaults to ``False`` so the
legacy suite keeps passing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from femtobot.api.goal_runtime import (
    GoalEvent,
    GoalEventKind,
    GoalJob,
    GoalJobStatus,
    TERMINAL_STATUSES,
    create_goal_job,
    generate_event_id,
    generate_goal_id,
    serialize_goal_event,
    terminal_status,
)
from femtobot.config.schema import AgentDefaults, LongTaskApiMode, LongTaskConfig
from femtobot.session.pending_asks import (
    PENDING_ASKS_KEY,
    AskStatus,
    AskTarget,
    PendingAsk,
    append_pending_ask,
    count_pending_asks,
    deadline_iso,
    expire_pending_asks,
    find_pending_ask,
    generate_correlation_id,
    is_valid_correlation_id,
    list_pending_asks,
    update_pending_ask,
    validate_question_payload,
)


# ---------------------------------------------------------------------------
# PR 0.1 — LongTaskConfig schema
# ---------------------------------------------------------------------------


def test_long_task_config_defaults_match_plan_v2():
    cfg = LongTaskConfig()
    assert cfg.by_default is False
    assert cfg.max_goal_rounds == 12
    assert cfg.max_goal_runtime_s == 14400.0
    assert cfg.max_goal_wall_idle_s == 1800.0
    assert cfg.max_goal_ask_attempts == 3
    assert cfg.goal_iteration_extra_budget == 50
    assert cfg.sdk_execution_mode == "goal_aware"
    assert cfg.api_mode is LongTaskApiMode.AUTO
    assert cfg.api_async_accept_timeout_s == 5.0


def test_agent_defaults_exposes_long_task():
    defaults = AgentDefaults()
    assert isinstance(defaults.long_task, LongTaskConfig)
    assert defaults.long_task.by_default is False


def test_long_task_config_validation_low_boundaries():
    with pytest.raises(Exception):
        LongTaskConfig(max_goal_rounds=0)
    with pytest.raises(Exception):
        LongTaskConfig(max_goal_runtime_s=10.0)
    with pytest.raises(Exception):
        LongTaskConfig(api_async_accept_timeout_s=0.1)


# ---------------------------------------------------------------------------
# PR 0.3 — pending_asks
# ---------------------------------------------------------------------------


def test_generate_correlation_id_has_ask_prefix():
    cid = generate_correlation_id()
    assert cid.startswith("ask_")
    assert is_valid_correlation_id(cid)


def test_is_valid_correlation_id_rejects_garbage():
    assert is_valid_correlation_id("ask_short") is False
    assert is_valid_correlation_id("not_an_id") is False
    assert is_valid_correlation_id(None) is False
    assert is_valid_correlation_id(1234) is False


def test_validate_question_payload_rejects_blank_question():
    err = validate_question_payload(question="", context=None, timeout_s=60)
    assert err is not None and "question" in err


def test_validate_question_payload_rejects_out_of_range_timeout():
    err = validate_question_payload(
        question="ok?", context=None, timeout_s=10
    )
    assert err is not None and "timeoutS" in err
    err2 = validate_question_payload(
        question="ok?", context=None, timeout_s=86_401
    )
    assert err2 is not None and "timeoutS" in err2


def test_validate_question_payload_accepts_minimal_payload():
    err = validate_question_payload(question="hi?", context=None, timeout_s=60)
    assert err is None


def test_pending_ask_roundtrip_through_metadata():
    metadata: dict = {}
    ask = PendingAsk(
        correlation_id=generate_correlation_id(),
        target=AskTarget.ORCHESTRATOR,
        question="Pick a strategy",
        options=["A", "B"],
    )
    append_pending_ask(metadata, ask)
    assert PENDING_ASKS_KEY in metadata

    asks = list_pending_asks(metadata)
    assert len(asks) == 1
    assert asks[0].question == "Pick a strategy"
    assert asks[0].target is AskTarget.ORCHESTRATOR
    assert asks[0].status is AskStatus.PENDING

    # round-trip via JSON to mimic session persistence
    encoded = metadata[PENDING_ASKS_KEY]
    rehydrated = list_pending_asks({PENDING_ASKS_KEY: encoded})
    assert rehydrated[0].correlation_id == ask.correlation_id
    assert rehydrated[0].options == ["A", "B"]


def test_update_pending_ask_only_pending_transitions():
    metadata: dict = {}
    ask = PendingAsk(
        correlation_id="ask_abcdef123456",
        target=AskTarget.ORCHESTRATOR,
        question="…",
    )
    append_pending_ask(metadata, ask)

    assert update_pending_ask(
        metadata, ask.correlation_id, status=AskStatus.ANSWERED, response="go with A"
    )
    asks = list_pending_asks(metadata)
    assert asks[0].status is AskStatus.ANSWERED
    assert asks[0].response == "go with A"
    assert asks[0].answered_at is not None

    # second transition is a no-op (already terminal)
    assert not update_pending_ask(
        metadata, ask.correlation_id, status=AskStatus.CANCELLED
    )


def test_expire_pending_asks_marks_overdue_only():
    past = datetime.now(timezone.utc) - timedelta(seconds=120)
    metadata: dict = {}
    expired_ask = PendingAsk(
        correlation_id="ask_overdue1234",
        target=AskTarget.ORCHESTRATOR,
        question="…",
        created_at=past.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        deadline_at=deadline_iso(
            created_at=past.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            timeout_s=30,
        ),
    )
    fresh_ask = PendingAsk(
        correlation_id="ask_freshabcd",
        target=AskTarget.ORCHESTRATOR,
        question="…",
        deadline_at=deadline_iso(created_at=_iso_now(), timeout_s=1800),
    )
    append_pending_ask(metadata, expired_ask)
    append_pending_ask(metadata, fresh_ask)

    expired = expire_pending_asks(metadata)
    assert len(expired) == 1
    assert expired[0].correlation_id == expired_ask.correlation_id

    states = {a.correlation_id: a.status for a in list_pending_asks(metadata)}
    assert states[expired_ask.correlation_id] is AskStatus.TIMED_OUT
    assert states[fresh_ask.correlation_id] is AskStatus.PENDING


def test_count_pending_asks_ignores_terminal():
    metadata: dict = {}
    pending = PendingAsk(
        correlation_id="ask_pending123", target=AskTarget.ORCHESTRATOR, question="?"
    )
    done = PendingAsk(
        correlation_id="ask_done123456", target=AskTarget.ORCHESTRATOR, question="?"
    )
    append_pending_ask(metadata, pending)
    append_pending_ask(metadata, done)
    update_pending_ask(metadata, done.correlation_id, status=AskStatus.ANSWERED, response="x")
    assert count_pending_asks(metadata) == 1


def test_find_pending_ask_returns_none_for_missing():
    assert find_pending_ask({}, "ask_zzzzzzzzzzzz") is None


# ---------------------------------------------------------------------------
# PR 0.4 — goal_runtime
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def test_generate_goal_id_prefixed_and_unique():
    a = generate_goal_id()
    b = generate_goal_id()
    assert a.startswith("goal_")
    assert b.startswith("goal_")
    assert a != b


def test_create_goal_job_mints_id_and_emits_event_on_demand():
    job = create_goal_job(session_key="api:default", objective="Refactor X")
    assert job.goal_id.startswith("goal_")
    assert job.session_key == "api:default"
    assert job.objective == "Refactor X"
    assert job.status is GoalJobStatus.ACCEPTED

    evt = GoalEvent.new(goal_id=job.goal_id, kind=GoalEventKind.STATUS_CHANGED,
                        data={"status": "running"})
    job.events.append(evt)

    payload = job.to_dict(include_events=True)
    assert payload["events"][0]["kind"] == "status_changed"
    assert payload["elapsed_s"] >= 0


def test_terminal_status_predicate():
    assert terminal_status(GoalJobStatus.COMPLETE)
    assert terminal_status(GoalJobStatus.CANCELLED)
    assert terminal_status(GoalJobStatus.BLOCKED)
    assert terminal_status(GoalJobStatus.FAILED)
    assert terminal_status("complete")
    assert not terminal_status(GoalJobStatus.RUNNING)
    assert not terminal_status("wat")


def test_serialize_goal_event_is_ndjson_safe():
    evt = GoalEvent.new(
        goal_id="goal_zzzzzzzzzzzz",
        kind=GoalEventKind.LOG,
        data={"text": "hello"},
    )
    line = serialize_goal_event(evt)
    assert "\n" not in line
    import json
    decoded = json.loads(line)
    assert decoded["kind"] == "log"
    assert decoded["data"]["text"] == "hello"


def test_goal_event_id_generator_is_unique():
    a = generate_event_id()
    b = generate_event_id()
    assert a.startswith("evt_")
    assert a != b


def test_terminal_statuses_constant_includes_expected_set():
    assert GoalJobStatus.COMPLETE in TERMINAL_STATUSES
    assert GoalJobStatus.RUNNING not in TERMINAL_STATUSES