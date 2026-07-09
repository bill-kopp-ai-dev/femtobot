"""Async message queue for decoupled channel-agent communication."""

from __future__ import annotations

import asyncio
import os

from loguru import logger

from femtobot.bus.events import InboundMessage, OutboundMessage


def _env_int(name: str, default: int) -> int:
    """Read a positive int from the environment, falling back to *default*."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Audit (item 23 of the v0.0.7 second-pass review): the bus used to
# be ``asyncio.Queue()`` without a ``maxsize``, so a stuck consumer
# (e.g. agent loop deadlock) let the queue grow without bound.  We
# now read a soft cap from ``FEMTOBOT_BUS_QUEUE_MAXSIZE`` (default
# 1024 for inbound, 4096 for outbound — outbound is larger because
# a single LLM turn can fan out to many progress events).
DEFAULT_INBOUND_MAXSIZE = 1024
DEFAULT_OUTBOUND_MAXSIZE = 4096


class MessageBus:
    """
    Async message bus that decouples the CLI/A2A from the agent core.

    TODO(A2A): For true multi-agent setups, this local queue will be bypassed
    or wrapped by the A2A HTTP client/server to route messages over the Docker network.
    """

    def __init__(
        self,
        *,
        inbound_maxsize: int | None = None,
        outbound_maxsize: int | None = None,
    ) -> None:
        # Cap the queues so a stuck consumer doesn't cause unbounded
        # memory growth.  The cap is configurable so tests can opt
        # out (set to 0 explicitly) and operators can tune for their
        # workload.
        # asyncio.Queue with ``maxsize=0`` is **unbounded** (the
        # historical behavior) — we preserve that as a documented
        # escape hatch but log a warning so operators notice.
        self.inbound_maxsize: int = (
            inbound_maxsize
            if inbound_maxsize is not None
            else _env_int("FEMTOBOT_BUS_INBOUND_MAXSIZE", DEFAULT_INBOUND_MAXSIZE)
        )
        self.outbound_maxsize: int = (
            outbound_maxsize
            if outbound_maxsize is not None
            else _env_int("FEMTOBOT_BUS_OUTBOUND_MAXSIZE", DEFAULT_OUTBOUND_MAXSIZE)
        )
        if self.inbound_maxsize == 0 or self.outbound_maxsize == 0:
            logger.warning(
                "MessageBus: one of the queue caps is 0 (FEMTOBOT_BUS_*_MAXSIZE)."
                " Falling back to unbounded; this can cause memory pressure if a"
                " consumer is stuck."
            )
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(
            maxsize=self.inbound_maxsize
        )
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(
            maxsize=self.outbound_maxsize
        )

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent.

        With a bounded queue, ``put`` blocks when the cap is hit,
        which provides natural backpressure to the producer.
        """
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels.

        With a bounded queue, ``put`` blocks when the cap is hit.
        """
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
