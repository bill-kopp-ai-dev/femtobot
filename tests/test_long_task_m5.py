"""Tests for M5 — async_goal HTTP contract."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from femtobot.api.goal_handlers import GoalRegistry, register_goal_routes
from femtobot.api.goal_runtime import GoalEvent, GoalEventKind, GoalJobStatus
from femtobot.api.goal_routing import resolve_async_mode, should_async_goal
from femtobot.api.goal_schemas import (
    AsyncGoalAccepted,
    AsyncGoalAnswerRequest,
    AsyncGoalRequest,
    AsyncGoalStatus,
    chunked,
    is_valid_session_id,
)
from femtobot.config.schema import LongTaskApiMode, LongTaskConfig


# ---------------------------------------------------------------------------
# PR 5.1 — schemas
# ---------------------------------------------------------------------------


def test_async_goal_request_validate_requires_session_id():
    req = AsyncGoalRequest(messages=[{"role": "user", "content": "hi"}])
    err = req.validate()
    assert err is not None and "session_id" in err


def test_async_goal_request_validate_rejects_invalid_session_id():
    req = AsyncGoalRequest(
        session_id="bad session id!", messages=[{"role": "user", "content": "hi"}]
    )
    err = req.validate()
    assert err is not None and "session_id" in err


def test_async_goal_request_validate_requires_messages_or_objective():
    req = AsyncGoalRequest(session_id="valid-id")
    err = req.validate()
    assert err is not None and "messages" in err.lower()


def test_async_goal_request_validate_rejects_oversized_objective():
    req = AsyncGoalRequest(session_id="valid-id", objective="x" * 5000)
    err = req.validate()
    assert err is not None and "exceeds" in err


def test_async_goal_request_validate_accepts_valid_payload():
    req = AsyncGoalRequest(
        session_id="worker-1",
        messages=[{"role": "user", "content": "Ship v1"}],
    )
    err = req.validate()
    assert err is None


def test_is_valid_session_id():
    assert is_valid_session_id("abc.def_ghi-jkl")
    assert is_valid_session_id("a" * 128)
    assert not is_valid_session_id("")
    assert not is_valid_session_id("with spaces")
    assert not is_valid_session_id("with/slash")
    assert not is_valid_session_id("a" * 200)


def test_async_goal_accepted_to_dict():
    payload = AsyncGoalAccepted(
        session_id="x",
        goal_id="goal_yyyy",
        poll_url="https://x/v1/goals/goal_yyyy",
        events_url="https://x/v1/goals/goal_yyyy/events",
        answer_url="https://x/v1/goals/goal_yyyy/answer",
        accepted_at="2026-07-13T00:00:00Z",
    )
    d = payload.to_dict()
    assert d["status"] == "accepted"
    assert d["goal_id"] == "goal_yyyy"
    assert d["session_id"] == "x"


def test_async_goal_status_to_dict_omits_none_fields():
    payload = AsyncGoalStatus(
        status="running",
        session_id="x",
        goal_id="g",
        elapsed_s=3.5,
    )
    d = payload.to_dict()
    assert "objective" not in d
    assert "final_content" not in d
    assert d["elapsed_s"] == 3.5


def test_async_goal_answer_request_validate_requires_response():
    payload = AsyncGoalAnswerRequest(response="")
    err = payload.validate()
    assert err is not None and "response" in err


def test_chunked_splits_correctly():
    out = chunked([1, 2, 3, 4, 5], size=2)
    assert out == [[1, 2], [3, 4], [5]]


# ---------------------------------------------------------------------------
# PR 5.2 — routing helper
# ---------------------------------------------------------------------------


def test_resolve_async_mode_defaults_to_sync():
    assert resolve_async_mode(None) is LongTaskApiMode.SYNC
    cfg = SimpleNamespace()  # no api_mode attribute
    assert resolve_async_mode(cfg) is LongTaskApiMode.SYNC


def test_resolve_async_mode_reads_config():
    cfg = LongTaskConfig(api_mode=LongTaskApiMode.ASYNC_GOAL)
    assert resolve_async_mode(cfg) is LongTaskApiMode.ASYNC_GOAL


def test_should_async_goal_sync_mode_never_admits():
    cfg = LongTaskConfig(api_mode=LongTaskApiMode.SYNC)
    assert (
        should_async_goal({"session_id": "x", "messages": []}, long_task_config=cfg, has_active_goal=False)
        is False
    )


def test_should_async_goal_async_mode_always_admits():
    cfg = LongTaskConfig(api_mode=LongTaskApiMode.ASYNC_GOAL)
    assert should_async_goal({}, long_task_config=cfg, has_active_goal=False) is True


def test_should_async_goal_auto_admits_when_session_id_present():
    cfg = LongTaskConfig(api_mode=LongTaskApiMode.AUTO)
    assert (
        should_async_goal(
            {"session_id": "abc"},
            long_task_config=cfg,
            has_active_goal=False,
        )
        is True
    )


def test_should_async_goal_auto_admits_when_objective_present():
    cfg = LongTaskConfig(api_mode=LongTaskApiMode.AUTO)
    assert (
        should_async_goal(
            {"objective": "Ship v1"},
            long_task_config=cfg,
            has_active_goal=False,
        )
        is True
    )


def test_should_async_goal_auto_admits_when_active_goal_exists():
    cfg = LongTaskConfig(api_mode=LongTaskApiMode.AUTO)
    assert (
        should_async_goal(
            {"messages": [{"role": "user", "content": "continue"}]},
            long_task_config=cfg,
            has_active_goal=True,
        )
        is True
    )


def test_should_async_goal_auto_rejects_trivial_request():
    cfg = LongTaskConfig(api_mode=LongTaskApiMode.AUTO)
    assert (
        should_async_goal(
            {"messages": [{"role": "user", "content": "hi"}]},
            long_task_config=cfg,
            has_active_goal=False,
        )
        is False
    )


# ---------------------------------------------------------------------------
# PR 5.3 — GoalRegistry
# ---------------------------------------------------------------------------


def test_goal_registry_create_assigns_id_and_emits_created_event():
    reg = GoalRegistry()
    job = reg.create(session_key="api:worker-1", objective="Ship v1")
    assert job.goal_id.startswith("goal_")
    assert job.session_key == "api:worker-1"
    assert job.status is GoalJobStatus.ACCEPTED
    assert any(e.kind is GoalEventKind.CREATED for e in job.events)


def test_goal_registry_get_returns_none_for_missing():
    reg = GoalRegistry()
    assert reg.get("goal_doesnotexist1234") is None


def test_goal_registry_update_status_emits_event():
    reg = GoalRegistry()
    job = reg.create(session_key="api:w")
    reg.update_status(job.goal_id, GoalJobStatus.RUNNING)
    updated = reg.get(job.goal_id)
    assert updated is not None
    assert updated.status is GoalJobStatus.RUNNING
    statuses = [e.data.get("status") for e in updated.events if e.kind is GoalEventKind.STATUS_CHANGED]
    assert "running" in statuses


def test_goal_registry_trims_long_event_log():
    reg = GoalRegistry()
    job = reg.create(session_key="api:w")
    # Push 1100 events, expect trim.
    for _ in range(1100):
        reg.publish(
            job.goal_id,
            GoalEvent.new(goal_id=job.goal_id, kind=GoalEventKind.LOG),
        )
    final = reg.get(job.goal_id)
    assert final is not None
    assert len(final.events) <= 1024


# ---------------------------------------------------------------------------
# PR 5.4 — route registration
# ---------------------------------------------------------------------------


def test_register_goal_routes_mounts_routes():
    from aiohttp import web

    app = web.Application()
    register_goal_routes(app)
    paths = {r.method + " " + r.resource.canonical for r in app.router.routes()}
    assert "POST /v1/goals" in paths
    assert "GET /v1/goals/{goal_id}" in paths
    assert "GET /v1/goals/{goal_id}/events" in paths
    assert "POST /v1/goals/{goal_id}/answer" in paths


@pytest.mark.asyncio
async def test_handle_create_goal_returns_202_with_urls():
    """End-to-end: admit a long-task job and inspect the 202 payload."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.post(
            "/v1/goals",
            json={
                "session_id": "worker-1",
                "messages": [{"role": "user", "content": "Refactor X"}],
            },
        )
        assert resp.status == 202
        body = await resp.json()
        assert body["status"] == "accepted"
        assert body["session_id"] == "worker-1"
        assert body["goal_id"].startswith("goal_")
        assert body["poll_url"].endswith(body["goal_id"])
        assert body["events_url"].endswith(body["goal_id"] + "/events")
        assert body["answer_url"].endswith(body["goal_id"] + "/answer")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_create_goal_rejects_invalid_payload():
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.post("/v1/goals", json={"session_id": "x"})
        # missing messages
        assert resp.status == 400
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_get_goal_404_for_missing():
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.get("/v1/goals/goal_nope1234")
        assert resp.status == 404
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_handle_get_goal_returns_status():
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    app = web.Application()
    register_goal_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        create = await client.post(
            "/v1/goals",
            json={
                "session_id": "worker-2",
                "objective": "ship",
            },
        )
        body = await create.json()
        goal_id = body["goal_id"]
        resp = await client.get(f"/v1/goals/{goal_id}")
        assert resp.status == 200
        status = await resp.json()
        assert status["goal_id"] == goal_id
        assert status["status"] in {"accepted", "running"}
        assert status["objective"] == "ship"
    finally:
        await client.close()