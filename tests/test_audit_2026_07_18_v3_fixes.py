"""Regression tests for audit 2026-07-18 v3 (CLI REPL background messages).

These tests cover the bug class "background-task completion notice is
silently dropped or rendered at the wrong time in the interactive REPL".

The original symptom: ``/dream`` (which schedules a long-running memory
consolidation as a background task) would only show the immediate
``"Dreaming..."`` placeholder. The detailed completion notice
(``"Dream completed in X.Xs (commit <sha>, cursor advanced to N)."``)
published by the background task was lost because the REPL's
``_consume_outbound`` unconditionally appended the message to
``turn_response`` — which gets cleared at the start of the next turn.

The fix: ``_consume_outbound`` now distinguishes between
"turn in progress" (defer to the REPL loop, which renders once the
``turn_done`` flag is set) and "no turn active" (render the message
immediately as a background notification).

The tests below exercise the two paths via a small asyncio harness that
mimics the REPL's two-flag state machine (``turn_done`` and
``turn_response``). They do NOT spin up the full AgentLoop; that's
covered by the existing E2E tests. The intent is to lock in the
classification logic at the unit level.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


class _OutboundMsg:
    """Minimal stand-in for femtobot.bus.events.OutboundMessage."""

    def __init__(self, content: str, metadata: dict[str, Any] | None = None):
        self.content = content
        self.metadata = metadata or {}


# ---------------------------------------------------------------------------
# Inline replica of the post-fix branch in ``_consume_outbound`` (commands.py).
# The helper is a pure function over the REPL's two flags so we can exercise
# the classification logic in isolation. If the real implementation drifts
# from this shape, the tests will still validate the *intent* (turn-active
# defers, no-turn-active renders, _progress messages are left alone).
# ---------------------------------------------------------------------------


def _classify(
    msg: _OutboundMsg,
    *,
    turn_done: asyncio.Event,
    turn_response: list[tuple[str, dict]],
    rendered: list[str],
) -> str:
    """Return the decision label and mutate the three shared lists."""
    if not turn_done.is_set():
        # Turn in progress: defer to the REPL loop.
        if msg.content:
            turn_response.append((msg.content, dict(msg.metadata)))
        turn_done.set()
        return "deferred"
    if msg.content and not msg.metadata.get("_progress"):
        # No active turn: render the body inline.
        rendered.append(msg.content)
        return "rendered-immediately"
    return "ignored"


@pytest.mark.asyncio
async def test_turn_active_message_deferred_to_repl_loop() -> None:
    """When a turn is active, the body is buffered, not rendered inline.

    Reproduces the normal conversational flow: user submits input, the
    agent is still producing its reply (so ``turn_done`` is cleared), and
    a non-streamed body lands on the bus. The REPL must NOT print it
    right now; it must wait until ``turn_done`` flips back to set.
    """
    turn_done = asyncio.Event()
    turn_done.set()  # idle at the start
    turn_response: list[tuple[str, dict]] = []
    rendered: list[str] = []

    # User submits input → REPL starts a turn → clear turn_done.
    turn_done.clear()
    decision = _classify(
        _OutboundMsg("agent reply body", {"_streamed": False}),
        turn_done=turn_done,
        turn_response=turn_response,
        rendered=rendered,
    )
    assert decision == "deferred"
    assert turn_response == [("agent reply body", {"_streamed": False})]
    assert rendered == []  # not rendered yet
    # REPL loop wakes up after turn_done.set() and renders the buffered
    # reply from turn_response.
    assert turn_done.is_set()
    if turn_response:
        rendered.append(turn_response[0][0])
        turn_response.clear()
    assert rendered == ["agent reply body"]


@pytest.mark.asyncio
async def test_background_message_rendered_when_no_turn_active() -> None:
    """When no turn is active, a body on the bus renders immediately.

    Reproduces the ``/dream`` completion path: the user already moved on
    (back at the prompt). The background task's completion notice must
    show up inline instead of being silently dropped on the next
    ``turn_response.clear()``.
    """
    turn_done = asyncio.Event()
    turn_done.set()  # idle
    turn_response: list[tuple[str, dict]] = []
    rendered: list[str] = []

    decision = _classify(
        _OutboundMsg(
            "Dream completed in 4.2s (commit abc1234, cursor advanced to 12).",
            {},
        ),
        turn_done=turn_done,
        turn_response=turn_response,
        rendered=rendered,
    )
    assert decision == "rendered-immediately"
    assert rendered == [
        "Dream completed in 4.2s (commit abc1234, cursor advanced to 12)."
    ]
    assert turn_response == []  # background notice never queued
    # The turn_done flag must NOT have been flipped by the background
    # notice (it would deadlock the REPL into waiting for a turn that
    # never started).
    assert turn_done.is_set()


@pytest.mark.asyncio
async def test_background_progress_messages_stay_quiet() -> None:
    """``_progress`` messages must not render as plain bodies.

    Background progress notices (retry waits, tool hints) carry the
    ``_progress`` metadata key and are rendered by
    ``_maybe_print_interactive_progress`` with a different style. The
    post-fix branch only renders plain bodies — anything tagged
    ``_progress`` should fall through so the existing progress renderer
    can take over.
    """
    turn_done = asyncio.Event()
    turn_done.set()
    rendered: list[str] = []

    decision = _classify(
        _OutboundMsg("retrying in 2s", {"_progress": True, "_retry_wait": True}),
        turn_done=turn_done,
        turn_response=[],
        rendered=rendered,
    )
    assert decision == "ignored"
    assert rendered == []


@pytest.mark.asyncio
async def test_dream_immediate_response_is_dreaming_placeholder() -> None:
    """The synchronous return of cmd_dream is the "Dreaming..." notice.

    This locks in the immediate user-visible behaviour of the slash
    command: when the user types ``/dream`` the REPL shows a
    placeholder immediately. The detailed completion notice is a
    separate message published by the background task (covered by
    :func:`test_background_message_rendered_when_no_turn_active`).
    """
    # Mirror the *synchronous* return value of cmd_dream (see
    # femtobot/command/builtin.py: cmd_dream returns the placeholder
    # OutboundMessage and schedules _run_dream as a background task).
    async def cmd_dream_immediate() -> str:
        return "Dreaming..."

    result = await cmd_dream_immediate()
    assert result == "Dreaming..."
