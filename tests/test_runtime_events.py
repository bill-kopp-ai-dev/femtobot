"""Tests for the runtime event bus — covers PR 4.3 (ReasoningCompleted)
and PR 7.1 (RuntimeMetric)."""

from __future__ import annotations

import asyncio

from femtobot.bus.runtime_events import (
    ReasoningCompleted,
    RuntimeEventBus,
    RuntimeEventPublisher,
    RuntimeMetric,
)


def _run(coro):  # noqa: ANN001
    return asyncio.new_event_loop().run_until_complete(coro)


def test_reasoning_completed_event_fires():
    bus = RuntimeEventBus()
    captured: list[ReasoningCompleted] = []
    bus.subscribe(
        lambda event: captured.append(event),
        event_type=ReasoningCompleted,
    )

    publisher = RuntimeEventPublisher(bus)
    _run(
        publisher.reasoning_completed(
            channel="cli",
            chat_id="direct",
            session_key="cli:direct",
            metadata={"_reasoning": True},
            duration_s=4.2,
            token_estimate=512,
        )
    )

    assert len(captured) == 1
    ev = captured[0]
    assert isinstance(ev, ReasoningCompleted)
    assert ev.duration_s == 4.2
    assert ev.token_estimate == 512
    assert ev.context.session_key == "cli:direct"


def test_other_events_are_filtered_out():
    """Subscribers to ``ReasoningCompleted`` must not receive other events."""
    from femtobot.bus.runtime_events import RuntimeModelChanged

    bus = RuntimeEventBus()
    captured: list[ReasoningCompleted] = []
    bus.subscribe(
        lambda event: captured.append(event),
        event_type=ReasoningCompleted,
    )
    publisher = RuntimeEventPublisher(bus)
    publisher.runtime_model_changed("gpt-5", None)
    assert captured == []


def test_publish_awaits_async_handlers():
    """``publish`` must await async handlers so subscribers can rely on
    ordering."""

    bus = RuntimeEventBus()
    order: list[str] = []

    async def handler(event):  # noqa: ANN001
        order.append("start")
        await asyncio.sleep(0.01)
        order.append("end")

    bus.subscribe(handler, event_type=ReasoningCompleted)
    publisher = RuntimeEventPublisher(bus)
    _run(
        publisher.reasoning_completed(
            channel="cli",
            chat_id="direct",
            session_key="k",
            metadata={},
            duration_s=1.0,
        )
    )
    assert order == ["start", "end"]


def test_emit_metric_publishes_payload():
    bus = RuntimeEventBus()
    captured: list[RuntimeMetric] = []
    bus.subscribe(lambda event: captured.append(event), event_type=RuntimeMetric)
    publisher = RuntimeEventPublisher(bus)
    _run(
        publisher.emit_metric(
            "tool_use_guard_triggered",
            payload={"iteration": 3, "user_keywords": ["test"]},
        )
    )
    assert len(captured) == 1
    assert captured[0].name == "tool_use_guard_triggered"
    assert captured[0].payload == {"iteration": 3, "user_keywords": ["test"]}
