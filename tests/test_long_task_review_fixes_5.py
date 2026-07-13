"""Regression tests for the *fifth* code-review pass."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from femtobot.api.goal_handlers import (
    GoalRegistry,
    handle_create_goal,
    register_goal_routes,
)
from femtobot.api.goal_runtime import GoalJobStatus
from femtobot.runtime_context import ask_pending_block, goal_blocked_block
from femtobot.session.goal_state import GOAL_STATE_KEY, goal_waiting_on


# ---------------------------------------------------------------------------
# Fix D+F — GoalRegistry.cleanup_terminal bounds memory
# ---------------------------------------------------------------------------


def test_goal_registry_cleanup_terminal_keeps_recent():
    """``cleanup_terminal(keep_recent=2)`` retains the two most recently
    transitioned jobs and drops the rest."""
    import time

    reg = GoalRegistry()
    job_ids = []
    for i in range(5):
        job = reg.create(session_key="api:w", objective=f"obj-{i}")
        reg.update_status(job.goal_id, GoalJobStatus.RUNNING)
        # Sleep to guarantee unique ``updated_at`` timestamps — the
        # ``milliseconds`` precision can collapse transitions done in
        # the same wall-clock millisecond.
        time.sleep(0.002)
        reg.update_status(job.goal_id, GoalJobStatus.COMPLETE)
        time.sleep(0.002)
        job_ids.append(job.goal_id)
    # Five terminal jobs; keep the 2 newest.
    removed = reg.cleanup_terminal(keep_recent=2)
    assert removed == 3
    # The first three (oldest transitions) are gone.
    for gone_id in job_ids[:3]:
        assert reg.get(gone_id) is None
    # The last two (most recent transitions) remain.
    for kept_id in job_ids[3:]:
        assert reg.get(kept_id) is not None


def test_goal_registry_cleanup_terminal_keeps_running_jobs():
    """Non-terminal jobs must NEVER be cleaned up, regardless of age."""
    reg = GoalRegistry()
    job = reg.create(session_key="api:w", objective="in-flight")
    reg.update_status(job.goal_id, GoalJobStatus.RUNNING)
    removed = reg.cleanup_terminal(keep_recent=0)
    assert removed == 0
    assert reg.get(job.goal_id) is not None


def test_goal_registry_cleanup_terminal_rejects_negative():
    reg = GoalRegistry()
    with pytest.raises(ValueError):
        reg.cleanup_terminal(keep_recent=-1)


def test_goal_registry_cleanup_terminal_clears_locks_and_queues():
    """Cleanup must drop the lock and queue too — otherwise the GC can
    never reclaim them."""
    reg = GoalRegistry()
    job = reg.create(session_key="api:w")
    reg.update_status(job.goal_id, GoalJobStatus.COMPLETE)
    # Pre-condition: lock + queue exist.
    assert job.goal_id in reg._locks
    assert job.goal_id in reg._events
    reg.cleanup_terminal(keep_recent=0)
    assert job.goal_id not in reg._locks
    assert job.goal_id not in reg._events


# ---------------------------------------------------------------------------
# Fix E — _accepted_response URL is robust to path prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accepted_response_url_uses_request_host(tmp_path):
    """``poll_url`` / ``events_url`` / ``answer_url`` must be built from
    ``request.scheme://request.host`` — not from a fragile string split
    on ``/v1/``."""
    from aiohttp.test_utils import TestClient, TestServer

    app = __import__("aiohttp").web.Application()
    register_goal_routes(app)

    captured: list = []

    async def _capture(msg):
        captured.append(msg)

    class _LoopStub:
        bus = SimpleNamespace(publish_inbound=_capture)

        @property
        def sessions(self):
            from femtobot.session.manager import SessionManager

            return SessionManager(tmp_path)

    app["agent_loop"] = _LoopStub()

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.post(
            "/v1/goals",
            json={"session_id": "w", "objective": "ship"},
        ) as resp:
            assert resp.status == 202
            body = await resp.json()
        # Scheme is http + host derived from the test server.
        assert body["poll_url"].startswith("http://")
        assert "/v1/goals/" in body["poll_url"]
        assert body["events_url"].endswith("/events")
        assert body["answer_url"].endswith("/answer")
        assert body["poll_url"] == (
            body["answer_url"].rsplit("/", 1)[0]
        )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Fix H+K — runtime_context imports are at module level
# ---------------------------------------------------------------------------


def test_runtime_context_datetime_imports_at_module_level():
    """``runtime_context`` must import ``datetime`` at module load time
    so the inner function doesn't have to re-import on every call."""
    import femtobot.runtime_context as rc

    # The module must expose ``datetime`` (the class) and ``timezone``
    # (the class) at module level — proof that ``from datetime import
    # …`` is at the top of the file, not inside a function.
    from datetime import datetime as _dt_class, timezone as _tz_class

    assert hasattr(rc, "datetime")
    assert rc.datetime is _dt_class
    assert hasattr(rc, "timezone")
    assert rc.timezone is _tz_class


# ---------------------------------------------------------------------------
# Fix I — ask_pending_block uses isinstance with AskTarget
# ---------------------------------------------------------------------------


def test_ask_pending_block_renders_asktarget_value():
    """The helper must render the canonical ``AskTarget`` enum value
    (e.g. ``orchestrator`` or ``human``) in the output block."""
    from femtobot.session.pending_asks import (
        AskTarget,
        append_pending_ask,
        PendingAsk,
    )

    md: dict = {}
    append_pending_ask(
        md,
        PendingAsk(
            correlation_id="ask_typestest01",
            target=AskTarget.HUMAN,  # valid enum value
            question="human review?",
        ),
    )
    text = ask_pending_block(md).to_text()
    assert "ask_typestest01" in text
    assert "target=human" in text


# ---------------------------------------------------------------------------
# Fix J — goal_blocked_block uses typed helper
# ---------------------------------------------------------------------------


def test_goal_blocked_block_uses_typed_helper_for_non_string_values():
    """If session metadata carries a ``bytes`` value in
    ``goal_waiting_on``, the typed helper must filter it out."""
    md = {
        "goal_waiting_on": b"ask_orchestrator",  # bytes, not str
    }
    # Direct check on the helper:
    assert goal_waiting_on(md) is None
    # Therefore the block must NOT be emitted.
    assert goal_blocked_block(md) is None


# ---------------------------------------------------------------------------
# Fix N+O — _state_command uses one timestamp + only implicit flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_command_uses_single_timestamp(tmp_path):
    """``ctx.msg.metadata.goal_started_at`` and
    ``ctx.session.metadata.goal_started_at`` must carry the *same*
    timestamp — two ``time.time()`` calls would produce different
    values."""
    from femtobot.agent.loop import AgentLoop
    from femtobot.bus.queue import MessageBus
    from femtobot.config.schema import LongTaskConfig

    class _StubProvider:
        generation = SimpleNamespace(max_tokens=8192)

        def get_default_model(self):
            return "stub"

        async def chat(self, *a, **kw):
            return None

        async def chat_stream(self, *a, **kw):
            yield None

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
    )
    loop.long_task_config = LongTaskConfig(
        by_default=True, sdk_execution_mode="goal_aware"
    )

    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    msg = SimpleNamespace(
        channel="cli",
        sender_id="tester",
        chat_id="chat-1",
        content="Refactor X",
        metadata={},
    )
    ctx = SimpleNamespace(
        msg=msg,
        session=session,
        session_key="cli:chat-1",
    )
    await loop._state_command(ctx)
    msg_started = msg.metadata.get("goal_started_at")
    session_started = session.metadata.get("goal_started_at")
    assert msg_started is not None
    assert session_started == msg_started  # Same instant, not two calls.


@pytest.mark.asyncio
async def test_state_command_auto_wrap_only_sets_implicit_flag(tmp_path):
    """The auto-wrap path must NOT stamp ``goal_requested`` (which is
    reserved for explicit ``/goal`` slash commands)."""
    from femtobot.agent.loop import AgentLoop
    from femtobot.bus.queue import MessageBus
    from femtobot.config.schema import LongTaskConfig

    class _StubProvider:
        generation = SimpleNamespace(max_tokens=8192)

        def get_default_model(self):
            return "stub"

        async def chat(self, *a, **kw):
            return None

        async def chat_stream(self, *a, **kw):
            yield None

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
    )
    loop.long_task_config = LongTaskConfig(
        by_default=True, sdk_execution_mode="goal_aware"
    )

    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    msg = SimpleNamespace(
        channel="cli",
        sender_id="tester",
        chat_id="chat-1",
        content="Refactor X",
        metadata={},
    )
    ctx = SimpleNamespace(
        msg=msg,
        session=session,
        session_key="cli:chat-1",
    )
    await loop._state_command(ctx)
    # The bare ``goal_requested`` flag must NOT be set by the auto-wrap.
    assert "goal_requested" not in msg.metadata
    # But the implicit marker must be.
    assert msg.metadata.get("goal_requested_implicitly") is True
    assert session.metadata.get("goal_requested_implicitly") is True


@pytest.mark.asyncio
async def test_state_command_auto_wrap_skips_when_goal_active(tmp_path):
    """When the session already has an active goal, the auto-wrap path
    must not stamp fresh metadata — the existing goal stays put."""
    from femtobot.agent.loop import AgentLoop
    from femtobot.bus.queue import MessageBus
    from femtobot.config.schema import LongTaskConfig

    class _StubProvider:
        generation = SimpleNamespace(max_tokens=8192)

        def get_default_model(self):
            return "stub"

        async def chat(self, *a, **kw):
            return None

        async def chat_stream(self, *a, **kw):
            yield None

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_StubProvider(),
        workspace=tmp_path,
    )
    loop.long_task_config = LongTaskConfig(
        by_default=True, sdk_execution_mode="goal_aware"
    )

    from femtobot.session.manager import SessionManager

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:chat-1")
    # Pre-existing ACTIVE goal.
    session.metadata = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
    }
    msg = SimpleNamespace(
        channel="cli",
        sender_id="tester",
        chat_id="chat-1",
        content="Another message",
        metadata={},
    )
    ctx = SimpleNamespace(
        msg=msg,
        session=session,
        session_key="cli:chat-1",
    )
    await loop._state_command(ctx)
    # The auto-wrap should NOT have stamped session metadata because
    # the goal is already active.
    assert "goal_requested_implicitly" not in session.metadata
    assert "goal_started_at" not in session.metadata


# ---------------------------------------------------------------------------
# Fix M — _iso_now_ms uses module-level imports
# ---------------------------------------------------------------------------


def test_builtin_iso_now_ms_uses_module_level_datetime():
    """The ``_iso_now_ms`` helper must not re-import datetime inside the
    function body — that's a perf and style smell."""
    import femtobot.command.builtin as bl

    # ``from datetime import datetime, timezone`` exposes the *classes*
    # as module attributes, not the ``datetime`` module itself.
    from datetime import datetime as _dt_class, timezone as _tz_class

    assert bl.datetime is _dt_class
    assert bl.timezone is _tz_class


# ---------------------------------------------------------------------------
# Persistence edge case — session.metadata updated but no save call
# ---------------------------------------------------------------------------


def test_goal_active_block_includes_started_at_iso():
    """Regression: ``goal_active_block`` must continue to surface
    ``Started at (UTC): <ISO>`` after the 4th-round refactor."""
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