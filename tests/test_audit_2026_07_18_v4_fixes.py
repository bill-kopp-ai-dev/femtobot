"""Regression tests for audit 2026-07-18 v4 (matched-slash-context-rewriting).

Background. Two slash commands — ``/goal`` and ``/btw`` — are documented
as "context-rewriting" shortcuts: they mutate ``ctx.msg`` in place and
return ``None`` so the state machine keeps processing the turn as a
normal model call. The previous fix for unknown slash commands
("if result is None and raw startswith /, surface a help notice") was
too aggressive: it caught these legitimate matches and told the user
"Unknown command: /goal" even though the router had matched the
command.

Fix: ``_state_command`` now consults the router's exact+prefix tables
to decide whether ``raw`` was a *matched* slash command. If it was,
``result is None`` means "rewriting shortcut, continue", not
"unknown command".

These tests exercise the classification logic at the unit level
without spinning up a full AgentLoop.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from femtobot.agent.loop import AgentLoop
from femtobot.command.builtin import register_builtin_commands
from femtobot.command.router import CommandRouter


@pytest.fixture
def router() -> CommandRouter:
    r = CommandRouter()
    register_builtin_commands(r)
    return r


def _classify(raw: str, router: CommandRouter) -> str:
    """Mirror of the classification branch in ``_state_command``.

    Returns one of: ``"unknown"`` (raw was a slash command but no handler
    matched), ``"matched-shortcut"`` (a handler was registered and would
    be invoked), or ``"plain"`` (raw does not start with ``/``).

    Audit 2026-07-18 v5: priority commands (e.g. /restart, /stop) now
    also count as matched-shortcut so the offline ``-m`` path does not
    treat them as unknown.
    """
    if not raw.startswith("/"):
        return "plain"
    raw_norm = raw.lower()
    if raw_norm in router._exact:
        return "matched-shortcut"
    if raw_norm in router._priority:
        return "matched-shortcut"
    if any(raw_norm.startswith(pfx) for pfx, _ in router._prefix):
        return "matched-shortcut"
    return "unknown"


def test_classify_plain_text_is_not_slash(router: CommandRouter) -> None:
    """Free-form user text is never a slash command."""
    assert _classify("hello world", router) == "plain"
    assert _classify("oi", router) == "plain"


def test_classify_unknown_slash_command(router: CommandRouter) -> None:
    """``/foo`` is not in the router — should be flagged as unknown."""
    assert _classify("/foo", router) == "unknown"
    assert _classify("/nopenope", router) == "unknown"


def test_classify_exact_slash_command(router: CommandRouter) -> None:
    """Exact-match commands are matched-shortcut even with no args."""
    assert _classify("/new", router) == "matched-shortcut"
    assert _classify("/help", router) == "matched-shortcut"
    assert _classify("/status", router) == "matched-shortcut"
    assert _classify("/dream", router) == "matched-shortcut"


def test_classify_prefix_slash_command(router: CommandRouter) -> None:
    """Prefix-match commands are matched-shortcut for any arg shape.

    Regression: the previous fix broke ``/goal <task>`` because the
    handler returns None (rewriting shortcut) and the unknown-command
    notice fired. ``/goal Crie um arquivo`` is a legitimate match.
    """
    assert _classify("/goal Crie um arquivo", router) == "matched-shortcut"
    assert _classify("/goal status", router) == "matched-shortcut"
    assert _classify("/model opus", router) == "matched-shortcut"
    assert _classify("/history 5", router) == "matched-shortcut"


def test_classify_known_command_with_no_match_args(router: CommandRouter) -> None:
    """Args after a known command still count as matched-shortcut.

    ``/mcp tools percival-osm`` should be matched (prefix ``/mcp ``
    plus the per-subcommand handler in cmd_mcp). Even when the sub
    command is malformed, the outer router still knows the input is a
    slash command.
    """
    assert _classify("/mcp tools percival-osm", router) == "matched-shortcut"
    assert _classify("/mcp tools", router) == "matched-shortcut"


def test_classify_priority_command(router: CommandRouter) -> None:
    """Priority commands (e.g. /restart, /stop) must also classify as
    matched-shortcut so the offline ``-m`` path does not treat them
    as unknown."""
    assert _classify("/restart", router) == "matched-shortcut"
    assert _classify("/stop", router) == "matched-shortcut"


def test_reply_unknown_command_message_shape() -> None:
    """Sanity: the help notice still has the right shape after the v4 fix."""
    msg = AgentLoop._reply_unknown_command("cli", "direct", "/foo")
    assert "Unknown command: `/foo`." in msg.content
    # Lists the palette so the user can self-correct.
    assert "Available commands:" in msg.content
    assert "/help" in msg.content
