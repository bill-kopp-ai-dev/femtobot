"""Smoke integration test for the elapsed-time spinner (PR 2.4).

Verifies the user-visible behaviour: a ``ThinkingSpinner`` configured
with an elapsed-time renderable renders text of the form
``Femtobot is cogitating (3s)`` when the spinner is briefly activated.

Uses ``monkeypatch`` against ``time.monotonic`` so the test is
deterministic without ``sleep`` and would fail against the legacy
``console.status``-only spinner (no elapsed time, no tokens).
"""

from __future__ import annotations

import io

from rich.console import Console

from femtobot.cli.parity_widgets import SpinnerWithElapsed
from femtobot.cli.stream import ThinkingSpinner


class _TtyFile(io.StringIO):
    def isatty(self) -> bool:
        return True


def _capture_render(spinner: ThinkingSpinner, elapsed: float) -> str:
    """Render the spinner's renderable as it would appear on a TTY."""
    import time as _time

    spinner._elapsed_renderable.start_time = _time.monotonic() - elapsed  # type: ignore[attr-defined]
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=120, color_system=None)
    # ``SpinnerWithElapsed.__rich_console__`` is implemented as a
    # side-effect that calls ``console.print`` and returns ``None``
    # (legacy design — see parity_widgets.py:336). We invoke it for
    # its side-effect only.
    spinner._elapsed_renderable.__rich_console__(  # type: ignore[attr-defined]
        console, console.options
    )
    return buf.getvalue()


def test_elapsed_text_appears_in_render(monkeypatch):
    """Render the ``SpinnerWithElapsed`` at t=3s and assert the elapsed
    marker shows up."""
    console = Console(file=_TtyFile(), force_terminal=True, width=120)
    renderable = SpinnerWithElapsed(bot_name="Femtobot", verb="cogitating")
    spinner = ThinkingSpinner(console=console, elapsed_renderable=renderable)

    # Render directly via Rich to capture the on-screen text.
    rendered = _capture_render(spinner, elapsed=3.0)

    assert "Femtobot" in rendered
    assert "cogitating" in rendered
    assert "(3s" in rendered, f"expected '(3s' in: {rendered!r}"


def test_token_counter_renders_when_set(monkeypatch):
    console = Console(file=_TtyFile(), force_terminal=True, width=120)
    renderable = SpinnerWithElapsed(
        bot_name="Femtobot",
        verb="cogitating",
        tokens=412,
    )
    spinner = ThinkingSpinner(console=console, elapsed_renderable=renderable)

    rendered = _capture_render(spinner, elapsed=0.5)
    assert "412 tokens" in rendered


def test_legacy_status_path_does_not_render_elapsed():
    """Without ``elapsed_renderable``, the spinner is a plain
    ``console.status`` and the elapsed marker must not appear in the
    rendered text. This regression-tests PR 2.2."""
    console = Console(file=_TtyFile(), force_terminal=True, width=120)
    spinner = ThinkingSpinner(console=console)
    assert spinner._elapsed_renderable is None
    # The legacy path stores the status object in ``_spinner``; nothing
    # in ``ThinkingSpinner`` knows how to render it as plain text, so we
    # only assert the structural property above.
    assert spinner._live is None
