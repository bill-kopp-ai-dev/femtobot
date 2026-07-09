"""WebSocketChannel critical regression tests.

Regression guard for the historical bug where the ``gateway`` parameter
was *consumed* in ``WebSocketChannel.__init__`` but never assigned to
``self.gateway``.  ``_maybe_push_active_goal_state`` (and a few
similar helpers) read ``self.gateway.session_manager`` directly, so
any caller that passed a non-None ``gateway`` triggered an
``AttributeError`` at runtime.

We pin the public attribute contract here so the bug can't
regress silently.
"""

from __future__ import annotations

from femtobot.bus.queue import MessageBus
from femtobot.channels.websocket import (
    DummyMedia,
    DummyTokens,
    DummyWorkspaces,
    GatewayServices,
    WebSocketChannel,
    WebSocketConfig,
)

# ``asyncio_mode = "auto"`` in pyproject.toml makes every ``async def``
# test an asyncio test automatically.  Sync tests don't need any mark.


def _build_channel(**kwargs) -> WebSocketChannel:
    """Build a ``WebSocketChannel`` with minimal config.

    Avoids touching the actual server (no ``start()`` is called).
    """
    cfg = WebSocketConfig(host="127.0.0.1", port=0)  # port=0 → ephemeral, no listen
    return WebSocketChannel(cfg, MessageBus(), **kwargs)


def test_gateway_default_is_none() -> None:
    """WS: with no ``gateway=`` arg, ``self.gateway is None`` (WS).

    ``self.gateway`` must always be a real attribute, not a slot
    that triggers ``AttributeError`` on read.  The default value is
    ``None`` and downstream code must short-circuit on that.
    """
    ch = _build_channel()
    assert ch.gateway is None


def test_gateway_is_assigned_when_provided() -> None:
    """WS (CRITICAL): ``gateway=...`` is assigned to ``self.gateway`` (WS).

    This is the historical fix: the parameter was previously
    consumed but never stored, so ``self.gateway.session_manager``
    raised ``AttributeError`` on every read.
    """
    sentinel = GatewayServices()
    ch = _build_channel(gateway=sentinel)
    assert ch.gateway is sentinel


async def test_maybe_push_active_goal_state_returns_when_gateway_none() -> None:
    """WS: ``_maybe_push_active_goal_state`` short-circuits when gateway is None (WS).

    The method must not raise ``AttributeError`` on ``self.gateway``
    when the channel was constructed without a gateway.  This pins
    the safe-default behavior of the helper.
    """
    ch = _build_channel()
    # Should return early; no exception, no work.
    await ch._maybe_push_active_goal_state("chat-x")
    await ch._maybe_push_active_goal_state("chat-y")


def test_dummy_stubs_are_present_for_fallback_path() -> None:
    """WS: when no gateway, the per-channel service stand-ins are real (WS).

    ``_tokens`` / ``_media`` / ``_workspaces`` are still used as
    fallbacks when ``self.gateway`` is None.  They must be the
    ``Dummy*`` instances so the public protocol is consistent.
    """
    ch = _build_channel()
    assert isinstance(ch._tokens, DummyTokens)
    assert isinstance(ch._media, DummyMedia)
    assert isinstance(ch._workspaces, DummyWorkspaces)


def test_channel_idempotent_construction() -> None:
    """WS: ``WebSocketChannel`` can be constructed twice without cross-talk (WS).

    Smoke test that ``__init__`` doesn't leak state across instances.
    """
    ch1 = _build_channel()
    ch2 = _build_channel()
    assert ch1 is not ch2
    assert ch1._subs is not ch2._subs
    assert ch1.gateway is ch2.gateway  # both default to None
