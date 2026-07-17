"""Runtime event bus for agent state notifications.

This bus is separate from :mod:`femtobot.bus.queue`: message bus events are
user delivery, while runtime events are in-process state notifications
that optional subscribers such as the CLI UI may render.

TODO(A2A): Bridge these runtime events to Server-Sent Events (SSE) for HTTP A2A.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from femtobot.bus.events import InboundMessage


@dataclass(frozen=True)
class RuntimeEventContext:
    """Routing context common to turn-scoped runtime events."""

    channel: str
    chat_id: str
    session_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionTurnStarted:
    """A user/system turn has loaded its session and is about to build context."""

    context: RuntimeEventContext


@dataclass(frozen=True)
class TurnRunStatusChanged:
    """Visible run status changed for a turn."""

    context: RuntimeEventContext
    status: str
    started_at: float | None = None


@dataclass(frozen=True)
class TurnCompleted:
    """A turn has delivered its final user-visible response."""

    context: RuntimeEventContext
    latency_ms: int | None = None
    runtime: Any | None = None


@dataclass(frozen=True)
class GoalStateChanged:
    """A session's sustained-goal state changed."""

    context: RuntimeEventContext
    session_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeModelChanged:
    """The active runtime model/preset changed."""

    model: str
    model_preset: str | None


@dataclass(frozen=True)
class ReasoningCompleted:
    """Reasoning stream finished for a turn (PR 4.3 of the longlogs plan).

    Emitted after ``hook.emit_reasoning_end`` so subscribers can render
    a ``thought for Xs`` footer or aggregate metrics without parsing
    the reasoning stream themselves.
    """

    context: RuntimeEventContext
    duration_s: float | None = None
    token_estimate: int | None = None


@dataclass(frozen=True)
class RuntimeMetric:
    """Generic runtime metric emitted by the longlogs remediation hooks.

    PR 7.1 introduces a small set of well-known ``name`` values:

    - ``tool_use_guard_triggered`` — ``ToolUseGuardHook`` injected a nudge.
    - ``mcp_missing_warning_emitted`` — ``_connect_mcp`` warned about a
      referenced-but-not-configured server.
    - ``live_race_detected`` — ``_clear_live_block`` saw a multi-row
      block on a non-TTY consumer (B4 catch-net).

    ``payload`` is intentionally open-ended so future metrics can
    attach structured data without churning the event schema.
    """

    context: RuntimeEventContext
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


RuntimeEvent = (
    SessionTurnStarted
    | TurnRunStatusChanged
    | TurnCompleted
    | GoalStateChanged
    | RuntimeModelChanged
    | ReasoningCompleted
    | RuntimeMetric
)
RuntimeEventType = (
    type[SessionTurnStarted]
    | type[TurnRunStatusChanged]
    | type[TurnCompleted]
    | type[GoalStateChanged]
    | type[RuntimeModelChanged]
    | type[ReasoningCompleted]
    | type[RuntimeMetric]
)
RuntimeEventHandler = Callable[[Any], Awaitable[None] | None]
_HandlerEntry = tuple[RuntimeEventType | None, RuntimeEventHandler]


class RuntimeEventBus:
    """Small in-process pub/sub bus for runtime state.

    Subscribers run in registration order. ``publish`` awaits async handlers so
    callers can preserve ordering when a runtime event must follow a user
    message. ``publish_nowait`` is available for synchronous call sites.
    """

    def __init__(self) -> None:
        self._handlers: list[_HandlerEntry] = []

    def subscribe(
        self,
        handler: RuntimeEventHandler,
        event_type: RuntimeEventType | None = None,
    ) -> Callable[[], None]:
        entry = (event_type, handler)
        self._handlers.append(entry)

        def _unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._handlers.remove(entry)

        return _unsubscribe

    async def publish(self, event: RuntimeEvent) -> None:
        for event_type, handler in list(self._handlers):
            if event_type is not None and not isinstance(event, event_type):
                continue
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("runtime event handler failed for {}", type(event).__name__)

    def publish_nowait(self, event: RuntimeEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("dropping runtime event without a running loop: {}", type(event).__name__)
            return
        loop.create_task(self.publish(event))


class RuntimeEventPublisher:
    """Convenience publisher for turn-scoped runtime events.

    Agent code should decide when state transitions happen; this helper owns
    the mechanics of building event contexts and carrying per-turn metadata.
    """

    def __init__(self, bus: RuntimeEventBus | None = None) -> None:
        self.bus = bus or RuntimeEventBus()
        self._turn_latency_ms: dict[str, int] = {}
        self._turn_runtime: dict[str, Any] = {}

    @staticmethod
    def _context(
        *,
        channel: str,
        chat_id: str,
        session_key: str,
        metadata: dict[str, Any] | None,
    ) -> RuntimeEventContext:
        return RuntimeEventContext(
            channel=channel,
            chat_id=chat_id,
            session_key=session_key,
            metadata=dict(metadata or {}),
        )

    def record_turn_runtime(self, session_key: str, runtime: Any) -> None:
        self._turn_runtime[session_key] = runtime

    def record_turn_latency(self, session_key: str, latency_ms: int | None) -> None:
        if latency_ms is not None:
            self._turn_latency_ms[session_key] = int(latency_ms)

    def clear_turn(self, session_key: str) -> None:
        self._turn_latency_ms.pop(session_key, None)
        self._turn_runtime.pop(session_key, None)

    async def session_turn_started(
        self,
        msg: InboundMessage,
        session_key: str,
    ) -> None:
        await self.bus.publish(
            SessionTurnStarted(
                context=self._context(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    session_key=session_key,
                    metadata=msg.metadata,
                )
            )
        )

    async def run_status_changed(
        self,
        msg: InboundMessage,
        session_key: str,
        status: str,
        *,
        started_at: float | None = None,
    ) -> None:
        await self.bus.publish(
            TurnRunStatusChanged(
                context=self._context(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    session_key=session_key,
                    metadata=msg.metadata,
                ),
                status=status,
                started_at=started_at,
            )
        )

    async def turn_completed(
        self,
        *,
        channel: str,
        chat_id: str,
        session_key: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        await self.bus.publish(
            TurnCompleted(
                context=self._context(
                    channel=channel,
                    chat_id=chat_id,
                    session_key=session_key,
                    metadata=metadata,
                ),
                latency_ms=self._turn_latency_ms.pop(session_key, None),
                runtime=self._turn_runtime.pop(session_key, None),
            )
        )

    def runtime_model_changed(self, model: str, model_preset: str | None) -> None:
        self.bus.publish_nowait(RuntimeModelChanged(model=model, model_preset=model_preset))

    async def reasoning_completed(
        self,
        *,
        channel: str,
        chat_id: str,
        session_key: str,
        metadata: dict[str, Any] | None,
        duration_s: float | None = None,
        token_estimate: int | None = None,
    ) -> None:
        """PR 4.3 (longlogs remediation): emit ``ReasoningCompleted``.

        Called by the runner after ``hook.emit_reasoning_end`` so the
        CLI's ``SpinnerWithElapsed`` (PR 2.2) can read ``duration_s``
        for the ``thought for Xs`` footer.
        """
        await self.bus.publish(
            ReasoningCompleted(
                context=self._context(
                    channel=channel,
                    chat_id=chat_id,
                    session_key=session_key,
                    metadata=metadata,
                ),
                duration_s=duration_s,
                token_estimate=token_estimate,
            )
        )

    async def emit_metric(
        self,
        name: str,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        session_key: str = "cli:direct",
        metadata: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """PR 7.1 (longlogs remediation): publish a runtime metric.

        Subscribers (Prometheus exporters, the ``femtobot doctor``
        scorecard) can ``bus.subscribe(handler, event_type=RuntimeMetric)``
        and filter on ``event.name`` to roll up the longlogs
        remediation counters.
        """
        await self.bus.publish(
            RuntimeMetric(
                context=self._context(
                    channel=channel,
                    chat_id=chat_id,
                    session_key=session_key,
                    metadata=metadata,
                ),
                name=name,
                payload=dict(payload or {}),
            )
        )


def ensure_runtime_event_publisher(owner: Any) -> RuntimeEventPublisher:
    """Return an owner's runtime publisher, creating missing state lazily."""
    publisher = getattr(owner, "runtime_event_publisher", None)
    if isinstance(publisher, RuntimeEventPublisher):
        return publisher

    bus = getattr(owner, "runtime_events", None)
    if not isinstance(bus, RuntimeEventBus):
        bus = RuntimeEventBus()
        owner.runtime_events = bus

    publisher = RuntimeEventPublisher(bus)
    owner.runtime_event_publisher = publisher
    return publisher
