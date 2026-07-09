"""``WebSocketChannel.stop`` graceful close tests (v0.0.8 third-pass C6).

Audit C6: the previous ``stop()`` method just cleared the
subscription dicts and let the server die, which closed all
active WebSocket connections abruptly.  Clients saw a TCP
RST/EOF and logged "connection reset" instead of the polite
"server shutdown".  We now send a WS close frame (code 1001,
"going away") to each open client before tearing the dicts
down.

We pin:

* ``stop()`` calls ``close(code=1001)`` on each connected
  client,
* clients that fail to receive the close frame are tolerated
  (the helper is best-effort),
* the dicts are still cleared after the close attempt.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from femtobot.bus.queue import MessageBus
from femtobot.channels.websocket import WebSocketChannel, WebSocketConfig


def _channel() -> WebSocketChannel:
    return WebSocketChannel(
        WebSocketConfig(host="127.0.0.1", port=0), MessageBus()
    )


async def test_stop_sends_close_to_each_client() -> None:
    """C6: ``stop()`` calls ``close(code=1001)`` on each open client (C6)."""
    ch = _channel()
    ch._running = True

    # Two mock clients connected.
    conn_a = MagicMock()
    conn_b = MagicMock()
    ch._conn_default = {conn_a: "chat-a", conn_b: "chat-b"}
    ch._conn_chats = {conn_a: {"chat-a"}, conn_b: {"chat-b"}}
    ch._subs = {"chat-a": {conn_a}, "chat-b": {conn_b}}
    ch._server_task = None
    ch._stop_event = MagicMock()
    ch._stop_event.set = MagicMock()  # already set is fine

    await ch.stop()

    # Both clients received a graceful close with code 1001.
    assert conn_a.close.called
    assert conn_b.close.called
    args, kwargs = conn_a.close.call_args
    assert kwargs.get("code") == 1001
    args, kwargs = conn_b.close.call_args
    assert kwargs.get("code") == 1001

    # And the dicts are still cleared.
    assert ch._subs == {}
    assert ch._conn_chats == {}
    assert ch._conn_default == {}


async def test_stop_handles_close_failure() -> None:
    """C6: a client that fails to close does not crash the loop (C6)."""
    ch = _channel()
    ch._running = True

    # First client fails; second succeeds.
    conn_fail = MagicMock()
    conn_fail.close.side_effect = OSError("broken pipe")
    conn_ok = MagicMock()
    ch._conn_default = {conn_fail: "c1", conn_ok: "c2"}
    ch._conn_chats = {conn_fail: {"c1"}, conn_ok: {"c2"}}
    ch._subs = {"c1": {conn_fail}, "c2": {conn_ok}}
    ch._server_task = None
    ch._stop_event = MagicMock()

    # Should not raise — failures are logged at debug.
    await ch.stop()

    assert conn_fail.close.called
    assert conn_ok.close.called
    # Dict cleared despite the failure.
    assert ch._conn_default == {}


async def test_stop_no_clients_is_a_noop_for_close() -> None:
    """C6: ``stop()`` with no clients doesn't crash (C6)."""
    ch = _channel()
    ch._running = True
    ch._conn_default = {}
    ch._conn_chats = {}
    ch._subs = {}
    ch._server_task = None
    ch._stop_event = MagicMock()

    await ch.stop()
    assert ch._subs == {}
