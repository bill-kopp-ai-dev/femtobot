"""``MessageBus`` queue size cap tests (v0.0.7 second-pass).

Audit item 23: ``asyncio.Queue()`` without ``maxsize`` grows
without bound when a consumer is stuck.  We added a default cap
(1024 inbound, 4096 outbound) plus env-var overrides.

We pin:

* the default constructor uses the documented cap,
* the explicit ``inbound_maxsize=`` / ``outbound_maxsize=`` args
  take precedence over the env var,
* ``maxsize=0`` is the documented escape hatch and falls back to
  unbounded (matching the historical behavior),
* the cap actually blocks a producer (natural backpressure).
"""

from __future__ import annotations

import asyncio

import pytest

from femtobot.bus.events import InboundMessage
from femtobot.bus.queue import (
    DEFAULT_INBOUND_MAXSIZE,
    DEFAULT_OUTBOUND_MAXSIZE,
    MessageBus,
)

pytestmark = pytest.mark.asyncio


def _msg(text: str = "x") -> InboundMessage:
    return InboundMessage(
        content=text,
        channel="test",
        sender_id="tester",
        chat_id="c",
    )


async def test_default_caps_are_documented_values() -> None:
    """Bounded: default caps are the published constants."""
    bus = MessageBus()
    assert bus.inbound_maxsize == DEFAULT_INBOUND_MAXSIZE
    assert bus.outbound_maxsize == DEFAULT_OUTBOUND_MAXSIZE
    # The queues themselves report the cap via ``maxsize``.
    assert bus.inbound.maxsize == DEFAULT_INBOUND_MAXSIZE
    assert bus.outbound.maxsize == DEFAULT_OUTBOUND_MAXSIZE


async def test_explicit_arg_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bounded: explicit constructor args win over env vars."""
    monkeypatch.setenv("FEMTOBOT_BUS_INBOUND_MAXSIZE", "99999")
    bus = MessageBus(inbound_maxsize=8)
    assert bus.inbound_maxsize == 8
    assert bus.inbound.maxsize == 8


async def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bounded: env var takes effect when no explicit arg is passed."""
    monkeypatch.setenv("FEMTOBOT_BUS_INBOUND_MAXSIZE", "16")
    bus = MessageBus()
    assert bus.inbound_maxsize == 16


async def test_maxsize_zero_is_unbounded_escape_hatch() -> None:
    """Bounded: ``maxsize=0`` falls back to unbounded (asyncio convention)."""
    bus = MessageBus(inbound_maxsize=0, outbound_maxsize=0)
    # asyncio.Queue with maxsize=0 is unbounded (the asyncio API
    # doesn't distinguish "0" from "unlimited").
    assert bus.inbound.maxsize == 0
    assert bus.outbound.maxsize == 0


async def test_inbound_cap_blocks_producer() -> None:
    """Bounded: a full inbound queue blocks the producer (backpressure)."""
    bus = MessageBus(inbound_maxsize=2, outbound_maxsize=2)
    # Two messages fill the queue; the third must block.
    await bus.publish_inbound(_msg("a"))
    await bus.publish_inbound(_msg("b"))
    assert bus.inbound_size == 2

    started = asyncio.Event()

    async def _slow_consumer() -> None:
        # Don't actually consume — we just want the producer to be
        # blocked, then we cancel the task to free the producer.
        started.set()
        await asyncio.sleep(10)

    consumer_task = asyncio.create_task(_slow_consumer())
    await started.wait()

    try:
        # The next publish would block forever; race against a short
        # timeout to confirm the backpressure exists.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bus.publish_inbound(_msg("c")), timeout=0.05)
    finally:
        consumer_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer_task


async def test_consume_frees_a_slot() -> None:
    """Bounded: ``get`` frees a slot, so the next ``put`` proceeds."""
    bus = MessageBus(inbound_maxsize=1, outbound_maxsize=1)
    await bus.publish_inbound(_msg("a"))
    assert bus.inbound_size == 1
    # Schedule a consumer that fires after a short delay.
    async def _consume() -> InboundMessage:
        await asyncio.sleep(0.01)
        return await bus.consume_inbound()
    consumer = asyncio.create_task(_consume())
    # This second publish must complete once the consumer frees the slot.
    await asyncio.wait_for(bus.publish_inbound(_msg("b")), timeout=0.5)
    msg = await consumer
    assert msg.content == "a"
