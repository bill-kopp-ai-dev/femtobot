"""Tests for ``ThinkingSpinner`` elapsed-time wiring (PR 2.2).

The ``ThinkingSpinner`` historically used ``console.status(...)`` which
renders a static "Femtobot is cogitating..." line. PR 2.2 wires
``SpinnerWithElapsed`` (a renderable from ``cli.parity_widgets``) into a
Rich ``Live`` so the elapsed time / token counter refreshes per frame
when the parity layer supplies an ``elapsed_renderable``.

Defaults remain byte-identical: passing nothing keeps the legacy
``console.status`` path.
"""

from __future__ import annotations

from rich.live import Live

from femtobot.cli.parity_widgets import SpinnerWithElapsed
from femtobot.cli.stream import ThinkingSpinner


class _FakeConsole:
    """Minimal stand-in for ``rich.console.Console.status``.

    Records ``start`` / ``stop`` calls so the test can assert that the
    legacy path is used when no ``elapsed_renderable`` is provided.
    """

    class _NullFile:
        """A non-TTY file the spinner can write to without leaking output."""

        def isatty(self) -> bool:
            return False

        def write(self, _data: str) -> None:
            return None

        def flush(self) -> None:
            return None

    def __init__(self) -> None:
        self.status_calls = 0
        self.live_started = False
        self.live_stopped = False
        # The spinner path calls ``console.file`` to flush its
        # ``_clear_current_line`` helper, so a stub file is required.
        self.file = self._NullFile()

    def status(self, text, *, spinner):  # noqa: ANN001
        self.status_calls += 1

        class _Ctx:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def start(self_inner):
                return None

            def stop(self_inner):
                return None

        return _Ctx()


def test_default_uses_console_status() -> None:
    console = _FakeConsole()
    spinner = ThinkingSpinner(console=console)
    assert console.status_calls == 1
    # No ``elapsed_renderable`` → the spinner is still a Status context.
    assert spinner._spinner is not None
    assert spinner._live is None


def test_elapsed_renderable_uses_live() -> None:
    console = _FakeConsole()
    renderable = SpinnerWithElapsed(bot_name="Femtobot", verb="cogitating")
    spinner = ThinkingSpinner(
        console=console, elapsed_renderable=renderable
    )
    # ``console.status`` must NOT have been called when an
    # ``elapsed_renderable`` is supplied.
    assert console.status_calls == 0
    assert spinner._spinner is None
    assert isinstance(spinner._live, Live)
    # Renderable is preserved verbatim so the Live can refresh it.
    assert spinner._elapsed_renderable is renderable


def test_start_stop_uses_live_path() -> None:
    console = _FakeConsole()
    renderable = SpinnerWithElapsed(bot_name="Femtobot", verb="cogitating")
    spinner = ThinkingSpinner(
        console=console, elapsed_renderable=renderable
    )

    class _LiveSpy:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    spy = _LiveSpy()
    spinner._live = spy  # replace with spy for assertions
    with spinner:
        assert spy.started is True
    assert spy.stopped is True


def test_legacy_path_keeps_status_object() -> None:
    """Regression: callers that read ``spinner._spinner`` keep working."""
    console = _FakeConsole()
    spinner = ThinkingSpinner(console=console)
    assert spinner._spinner is not None
    # The ``pause()`` context manager still drives the legacy path.
    with spinner.pause():
        pass
