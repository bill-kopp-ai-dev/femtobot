"""Regression tests for audit 2026-07-18 v3 (unknown slash command notice).

The AgentLoop used to fall through to the LLM builder whenever the
command router returned ``None`` for an input that started with ``/``.
That meant ``/tools``, ``/foo``, ``/asdf`` etc. were forwarded to the
LLM, which happily invented an answer ("here are the tools I have…").
Confusing and a potential prompt-injection surface.

Fix: ``AgentLoop._state_command`` now detects the case
``raw.startswith("/")`` and dispatches ``AgentLoop._reply_unknown_command``
which lists the registered slash commands. This locks in the new
behaviour with focused unit tests.
"""

from __future__ import annotations

import pytest

from femtobot.agent.loop import AgentLoop
from femtobot.bus.events import OutboundMessage


# ---------------------------------------------------------------------------
# _reply_unknown_command
# ---------------------------------------------------------------------------


def test_reply_unknown_command_lists_first_token() -> None:
    """The 'Unknown command' line quotes the first token verbatim."""
    msg = AgentLoop._reply_unknown_command("cli", "direct", "/nopenope")
    assert isinstance(msg, OutboundMessage)
    assert msg.channel == "cli"
    assert msg.chat_id == "direct"
    assert "Unknown command: `/nopenope`." in msg.content
    assert msg.metadata.get("_unknown_command") == "/nopenope"


def test_reply_unknown_command_handles_arguments() -> None:
    """Extra arguments are stripped — only the first token matters."""
    msg = AgentLoop._reply_unknown_command("cli", "direct", "/foo bar baz")
    assert "Unknown command: `/foo`" in msg.content


def test_reply_unknown_command_handles_empty_input() -> None:
    """Defensive: empty string does not crash and still produces output."""
    msg = AgentLoop._reply_unknown_command("cli", "direct", "")
    assert "Unknown command: `(empty)`" in msg.content


def test_reply_unknown_command_lists_palette() -> None:
    """The reply enumerates registered slash commands."""
    msg = AgentLoop._reply_unknown_command("cli", "direct", "/nope")
    # Spot-check a few well-known commands.
    for expected in ("/new", "/help", "/status", "/mcp", "/history", "/dream"):
        assert expected in msg.content, f"missing {expected!r} in palette"


def test_reply_unknown_command_caps_listing() -> None:
    """The reply never grows past the documented cap (20 entries)."""
    from femtobot.command.builtin import BUILTIN_COMMAND_SPECS

    msg = AgentLoop._reply_unknown_command("cli", "direct", "/nope")
    # Count occurrences of the bullet marker; each palette line emits one.
    bullets = msg.content.count("•")
    assert bullets <= 20
    if len(BUILTIN_COMMAND_SPECS) > 20:
        # The overflow notice should be present.
        assert "more (use `/help`)" in msg.content
