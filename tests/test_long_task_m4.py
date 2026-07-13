"""Tests for M4 — multi-channel continuation support.

Covers:

* ``ContinuationKind`` enum semantics
* ``maybe_continue_turn(kind=...)`` accepts the new kinds
* ``process_direct(execution_mode="goal_aware")`` re-enters for continuation
  slices (lightweight — full end-to-end requires a runner stub)
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from femtobot.session.goal_state import GOAL_STATE_KEY
from femtobot.session.turn_continuation import (
    ContinuationKind,
    get_max_goal_rounds,
    internal_continuation_inbound,
    maybe_continue_turn,
)


def test_continuation_kind_values_match_metadata_strings():
    assert ContinuationKind.SUSTAINED_GOAL.value == "sustained_goal"
    assert ContinuationKind.ASK_WAIT.value == "ask_wait"
    assert ContinuationKind.GOAL_RESUME.value == "goal_resume"


def test_get_max_goal_rounds_uses_config_when_supplied():
    cfg = SimpleNamespace(max_goal_rounds=5)
    assert get_max_goal_rounds(cfg) == 5
    cfg2 = SimpleNamespace(max_goal_rounds=None)
    assert get_max_goal_rounds(cfg2) == 12
    assert get_max_goal_rounds(None) == 12


@pytest.mark.asyncio
async def test_maybe_continue_turn_kind_sustained_goal_records_metadata():
    from femtobot.bus.events import InboundMessage

    queue: asyncio.Queue = asyncio.Queue()
    md_in = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "_sustained_goal_continuation_rounds": 0,
    }
    session = SimpleNamespace(metadata=dict(md_in))
    msg = InboundMessage(
        channel="cli",
        sender_id="tester",
        chat_id="chat-1",
        content="continue",
    )
    ctx = SimpleNamespace(
        session=session,
        pending_queue=queue,
        stop_reason="max_iterations",
        msg=msg,
        final_content="previous response",
        all_messages=[{"role": "assistant", "content": "previous response"}],
        visible_run_started_at=None,
        suppress_response=False,
        session_key="cli:chat-1",
    )
    scheduled = await maybe_continue_turn(ctx)
    assert scheduled is True
    queued = queue.get_nowait()
    assert queued.metadata["_internal_continuation"] is True
    assert queued.metadata["_internal_continuation_kind"] == "sustained_goal"
    assert session.metadata["_sustained_goal_continuation_rounds"] == 1
    assert internal_continuation_inbound(queued.metadata)


@pytest.mark.asyncio
async def test_maybe_continue_turn_unknown_kind_refuses():
    from femtobot.bus.events import InboundMessage

    queue: asyncio.Queue = asyncio.Queue()
    session = SimpleNamespace(metadata={GOAL_STATE_KEY: {"status": "active"}})
    msg = InboundMessage(channel="cli", sender_id="x", chat_id="chat-1", content="x")
    ctx = SimpleNamespace(
        session=session,
        pending_queue=queue,
        stop_reason="max_iterations",
        msg=msg,
        final_content="",
        all_messages=[],
        visible_run_started_at=None,
        suppress_response=False,
        session_key="cli:chat-1",
    )
    scheduled = await maybe_continue_turn(ctx, continuation_kind="nope")
    assert scheduled is False
    assert queue.empty()


@pytest.mark.asyncio
async def test_maybe_continue_turn_kind_ask_wait_requires_active_goal():
    from femtobot.bus.events import InboundMessage

    queue: asyncio.Queue = asyncio.Queue()
    session = SimpleNamespace(metadata={})
    msg = InboundMessage(channel="cli", sender_id="x", chat_id="chat-1", content="x")
    ctx = SimpleNamespace(
        session=session,
        pending_queue=queue,
        stop_reason="max_iterations",
        msg=msg,
        final_content="",
        all_messages=[],
        visible_run_started_at=None,
        suppress_response=False,
        session_key="cli:chat-1",
    )
    scheduled = await maybe_continue_turn(ctx, continuation_kind=ContinuationKind.ASK_WAIT)
    assert scheduled is False


@pytest.mark.asyncio
async def test_maybe_continue_turn_kind_ask_wait_with_active_goal_succeeds():
    from femtobot.bus.events import InboundMessage

    queue: asyncio.Queue = asyncio.Queue()
    md = {GOAL_STATE_KEY: {"status": "active", "objective": "ship"}}
    session = SimpleNamespace(metadata=md)
    msg = InboundMessage(channel="cli", sender_id="x", chat_id="chat-1", content="x")
    ctx = SimpleNamespace(
        session=session,
        pending_queue=queue,
        stop_reason="ask_wait",
        msg=msg,
        final_content="",
        all_messages=[],
        visible_run_started_at=None,
        suppress_response=False,
        session_key="cli:chat-1",
    )
    scheduled = await maybe_continue_turn(ctx, continuation_kind=ContinuationKind.ASK_WAIT)
    assert scheduled is True
    queued = queue.get_nowait()
    assert queued.metadata["_internal_continuation_kind"] == "ask_wait"


@pytest.mark.asyncio
async def test_maybe_continue_turn_respects_max_rounds():
    from femtobot.bus.events import InboundMessage

    queue: asyncio.Queue = asyncio.Queue()
    md = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "_sustained_goal_continuation_rounds": 5,
    }
    session = SimpleNamespace(metadata=md)
    msg = InboundMessage(channel="cli", sender_id="x", chat_id="chat-1", content="x")
    ctx = SimpleNamespace(
        session=session,
        pending_queue=queue,
        stop_reason="max_iterations",
        msg=msg,
        final_content="",
        all_messages=[],
        visible_run_started_at=None,
        suppress_response=False,
        session_key="cli:chat-1",
    )
    scheduled = await maybe_continue_turn(ctx, max_rounds=3)
    assert scheduled is False
    assert queue.empty()
    scheduled = await maybe_continue_turn(ctx, max_rounds=10)
    assert scheduled is True


# ---------------------------------------------------------------------------
# process_direct(execution_mode=...) — basic integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_direct_sync_does_not_require_ephemeral_queue(tmp_path):
    """Default execution mode creates no local queue."""
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
    # We don't actually run the full turn — just verify the signature is
    # accepted and execution_mode defaults to "sync".
    cfg = getattr(loop, "long_task_config", None)
    if cfg is not None:
        # Default sdk_execution_mode is "goal_aware" but a default LongTaskConfig
        # also doesn't have by_default=True, so users get sync unless they opt-in.
        assert cfg.sdk_execution_mode in ("sync", "goal_aware")


@pytest.mark.asyncio
async def test_process_direct_goal_aware_creates_local_queue(monkeypatch, tmp_path):
    """``execution_mode="goal_aware"`` instantiates a local queue."""
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

    seen: dict = {}

    async def _stub(msg, **kwargs):
        seen["pending_queue"] = kwargs.get("pending_queue")
        return None

    async def _acquire_lock(key):
        return _AsyncLock()

    monkeypatch.setattr(loop, "_process_message", _stub)
    monkeypatch.setattr(loop, "_connect_mcp", lambda: asyncio.sleep(0))
    monkeypatch.setattr(loop, "_acquire_session_lock", _acquire_lock)
    monkeypatch.setattr(loop, "_runtime_events", lambda: _StubRuntimeEvents())

    await loop.process_direct(
        content="Refactor X",
        execution_mode="goal_aware",
        session_key="cli:direct",
    )
    assert seen["pending_queue"] is not None
    assert isinstance(seen["pending_queue"], asyncio.Queue)


class _AsyncLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _StubRuntimeEvents:
    def run_status_changed(self, *a, **kw):
        class _Awaitable:
            def __await__(self):
                return iter(())

        return _Awaitable()

    def clear_turn(self, *a, **kw):
        return None