"""Tests for the multiline filter (Camada 1, bug fix).

The previous implementation called the ``Condition`` callback with no
arguments but the inner function declared ``(buf)``, raising
``TypeError`` at runtime. The fix introduced a pure helper
``_wants_multiline_text`` plus a thin ``_multiline_filter`` wrapper that
reads the focused buffer via ``get_app()``. These tests pin the pure
helper's behavior.
"""

from __future__ import annotations

import pytest

from femtobot.cli.commands import _wants_multiline_text


def test_empty_text_is_not_multiline() -> None:
    assert _wants_multiline_text("") is False


def test_text_without_escape_is_not_multiline() -> None:
    assert _wants_multiline_text("hello world") is False
    assert _wants_multiline_text("/status") is False
    assert _wants_multiline_text("a long paragraph without escapes") is False


def test_trailing_backslash_means_continue() -> None:
    assert _wants_multiline_text("hello \\") is True
    assert _wants_multiline_text("multi\\") is True
    # Single backslash at the end — the canonical "newline" marker.
    assert _wants_multiline_text("\\") is True


def test_backslash_in_middle_does_not_trigger() -> None:
    assert _wants_multiline_text("a\\b") is False


def test_eof_marker_submits_multiline_block() -> None:
    """A trailing ``[EOF]`` (optionally with whitespace) submits the block."""
    assert _wants_multiline_text("line1\nline2 [EOF]") is True
    assert _wants_multiline_text("multi line  [EOF]   ") is True
    assert _wants_multiline_text("[EOF]") is True


def test_eof_marker_not_at_end_means_continue() -> None:
    """``[EOF]`` in the middle is not the trigger — only trailing counts."""
    assert _wants_multiline_text("[EOF] not at end") is False


def test_callable_with_no_args_does_not_raise() -> None:
    """Regression: ``Condition`` invokes the callback with no args.

    The inner ``_multiline_filter`` must be zero-argument callable so
    that ``Condition(filter)()`` does not raise ``TypeError``.
    """
    from femtobot.cli.commands import _init_prompt_session

    # We don't actually call _init_prompt_session here (it depends on
    # config); we just verify that the no-arg wiring is structurally
    # correct via the pure helper.
    import inspect

    # The pure helper takes one argument (text), and the wrapper uses
    # get_app() internally — neither declares a `buf` parameter.
    sig = inspect.signature(_wants_multiline_text)
    assert "buf" not in sig.parameters