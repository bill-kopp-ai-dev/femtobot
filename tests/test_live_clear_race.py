"""Tests for PR 2.3 — spinner must stop before the live block clears.

The legacy ``ThinkingSpinner`` used to call ``_clear_current_line``
after the spinner's ``stop()``, but the spinner kept drawing for one
extra frame in some TTY setups. PR 2.3 hardens the ordering by:

1. Calling ``self._live.stop()`` (or ``self._spinner.stop()``) BEFORE
   the helper that clears the screen.
2. Asserting the order in tests so a future refactor cannot regress
   back to the race.
"""

from __future__ import annotations

import io

from femtobot.cli.stream import ThinkingSpinner


class _TtyFile(io.StringIO):
    def isatty(self) -> bool:
        return True


class _FakeConsole:
    def __init__(self) -> None:
        self.file = _TtyFile()

    def status(self, text, *, spinner):  # noqa: ANN001
        # Mimics rich.console.Console.status for the legacy path.
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


def test_live_path_stops_before_clear():
    """The ``Live`` must be ``stop()``ed before the clear-screen escape is
    written. We assert the order by recording call timestamps in
    monkey-patched helpers."""
    order: list[str] = []

    console = _FakeConsole()

    class _Live:
        def stop(self_inner) -> None:
            order.append("live.stop")

    class _Renderable:
        def __rich_console__(self_inner, *_args, **_kwargs):
            return iter(())

    spinner = ThinkingSpinner(
        console=console,
        elapsed_renderable=_Renderable(),
    )
    spinner._live = _Live()  # type: ignore[assignment]

    # Monkey-patch the helper to record its call order.
    import femtobot.cli.stream as stream_mod

    original = stream_mod._clear_live_block

    def spy_clear(c, *, height: int = 1) -> None:
        order.append("_clear_live_block")

    stream_mod._clear_live_block = spy_clear
    try:
        spinner.__exit__(None, None, None)
    finally:
        stream_mod._clear_live_block = original

    assert order == ["live.stop", "_clear_live_block"], order


def test_legacy_path_stops_before_clear():
    """Same ordering for the legacy ``console.status`` path."""
    order: list[str] = []
    console = _FakeConsole()

    class _Status:
        def stop(self_inner) -> None:
            order.append("status.stop")

    spinner = ThinkingSpinner(console=console)
    spinner._spinner = _Status()  # type: ignore[assignment]

    import femtobot.cli.stream as stream_mod

    original = stream_mod._clear_live_block

    def spy_clear(c, *, height: int = 1) -> None:
        order.append("_clear_live_block")

    stream_mod._clear_live_block = spy_clear
    try:
        spinner.__exit__(None, None, None)
    finally:
        stream_mod._clear_live_block = original

    assert order == ["status.stop", "_clear_live_block"], order
