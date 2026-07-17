"""Tests for the reasoning buffer CLI plumbing (PR 4.2).

The runtime split between ``_reasoning_delta`` and ``_reasoning``
metadata (introduced together with the ``emit_reasoning`` /
``emit_reasoning_end`` hook surface) and the CLI's ``_ReasoningBuffer``
is the user-visible side of B5 (reasoning content leaking into the
visible stream). These tests assert:

- ``_ReasoningBuffer.add`` accumulates until a flush trigger fires.
- ``_ReasoningBuffer.flush`` returns the accumulated text and resets.
- ``_ReasoningBuffer.clear`` discards the buffer (used when the user
  has ``channels_config.show_reasoning = False``).
- When ``show_reasoning`` is False, ``_maybe_print_interactive_progress``
  discards incoming reasoning chunks instead of forwarding them to the
  CLI's print path.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from femtobot.cli.commands import _ReasoningBuffer, _maybe_print_interactive_progress


def _run(coro):  # noqa: ANN001
    return asyncio.new_event_loop().run_until_complete(coro)


def test_buffer_accumulates_until_flush():
    buf = _ReasoningBuffer()
    # First add without flush trigger returns None.
    assert buf.add("Let me ") is None
    # Newline forces a flush, so the accumulated text is returned.
    flushed = buf.add("think about this.\n")
    assert flushed is not None
    assert "Let me think about this." in flushed


def test_buffer_flush_returns_stripped_text():
    buf = _ReasoningBuffer()
    buf.add("Reasoning: ")
    # No flush trigger — still buffered (no newline / sentence-end,
    # and well under the 60-char threshold).
    assert buf.add("no MCP servers here") is None
    flushed = buf.flush()
    assert flushed is not None
    assert "Reasoning:" in flushed
    assert "here" in flushed
    # Second flush returns None.
    assert buf.flush() is None


def test_buffer_clear_drops_text():
    buf = _ReasoningBuffer()
    buf.add("internal note")
    buf.clear()
    assert buf.flush() is None


async def _maybe_print_async(msg, channels_config):
    """Call ``_maybe_print_interactive_progress`` as a coroutine."""
    return await _maybe_print_interactive_progress(
        msg=msg,
        thinking=None,
        channels_config=channels_config,
        renderer=None,
        reasoning_buffer=_ReasoningBuffer(),
    )


def test_show_reasoning_false_discards_reasoning_chunks(capsys):
    """When ``show_reasoning=False``, the CLI must not print any reasoning
    text even if the upstream emits ``_reasoning`` chunks."""
    cfg = SimpleNamespace(show_reasoning=False, send_tool_hints=True, send_progress=True)
    msg = SimpleNamespace(
        content="The user wants me to test resilience.",
        metadata={"_progress": True, "_reasoning": True},
    )
    handled = _run(_maybe_print_async(msg, cfg))
    assert handled is True
    captured = capsys.readouterr()
    assert "resilience" not in captured.out


def test_show_reasoning_true_prints_reasoning(capsys):
    cfg = SimpleNamespace(show_reasoning=True, send_tool_hints=True, send_progress=True)
    msg = SimpleNamespace(
        content="The user wants me to test resilience.\n",
        metadata={"_progress": True, "_reasoning": True},
    )
    handled = _run(_maybe_print_async(msg, cfg))
    assert handled is True
    captured = capsys.readouterr()
    assert "resilience" in captured.out
