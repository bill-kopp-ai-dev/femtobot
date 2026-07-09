"""Streaming renderer for CLI output.

Uses Rich Live with ``transient=True`` for in-place markdown updates during
streaming.  After the live display stops, a final clean render is printed
so the content persists on screen.  ``transient=True`` ensures the live
area is erased before ``stop()`` returns, avoiding the duplication bug
that plagued earlier approaches.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager, nullcontext

from rich.console import Console, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from femtobot.cli.role_renderer import TurnSpacingRenderer
from femtobot.cli.whimsy import pick_verb, resolve_spinner


def _clear_current_line(console: Console) -> None:
    """Erase a transient status line before printing persistent output."""
    file = console.file
    isatty = getattr(file, "isatty", lambda: False)
    if not isatty():
        return
    file.write("\r\x1b[2K")
    file.flush()


def _make_console() -> Console:
    """Create a Console that emits plain text when stdout is not a TTY.

    Rich's spinner, Live render, and cursor-visibility escape codes all
    key off ``Console.is_terminal``. Forcing ``force_terminal=True`` overrode
    the ``isatty()`` check and caused control sequences (``\\x1b[?25l``,
    braille spinner frames) to pollute programmatic consumers such as
    ``docker exec -i`` or pipes, even with ``NO_COLOR`` or ``TERM=dumb``.
    Deferring to ``isatty()`` keeps Rich output in interactive terminals
    and plain text everywhere else (#3265).
    """
    return Console(file=sys.stdout, force_terminal=sys.stdout.isatty())


class ThinkingSpinner:
    """Spinner that shows '<bot_name> is thinking...' with pause support.

    When ``verbs_enabled`` is True (Camada 1 default), the spinner message
    uses a randomly-picked verb (e.g. "Femtobot is cogitating...") instead
    of the literal "thinking". Pass ``verb`` to force a specific one, or
    ``spinner_style`` to pick a non-default Rich spinner.
    """

    def __init__(
        self,
        console: Console | None = None,
        bot_name: str = "Femtobot",
        verb: str | None = None,
        spinner_style: str | None = None,
        verbs_enabled: bool = True,
        seed: int | None = None,
    ):
        c = console or _make_console()
        self._console = c
        self._bot_name = bot_name
        self._verbs_enabled = verbs_enabled
        self._verb = verb or pick_verb(seed)
        text = self._render_text()
        spinner_name = resolve_spinner(spinner_style, seed=seed)
        self._spinner_name = spinner_name
        self._spinner = c.status(text, spinner=spinner_name)
        self._active = False

    def _render_text(self) -> str:
        if self._verbs_enabled and self._verb:
            return f"[dim]{self._bot_name} is {self._verb.lower()}...[/dim]"
        return f"[dim]{self._bot_name} is thinking...[/dim]"

    @property
    def verb(self) -> str | None:
        """The currently-displayed verb (None if whimsy is disabled)."""
        return self._verb if self._verbs_enabled else None

    @property
    def spinner_name(self) -> str:
        """The Rich spinner style currently in use."""
        return self._spinner_name

    def __enter__(self):
        self._spinner.start()
        self._active = True
        return self

    def __exit__(self, *exc):
        self._active = False
        self._spinner.stop()
        _clear_current_line(self._console)
        return False

    def pause(self):
        """Context manager: temporarily stop spinner for clean output."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            if self._spinner and self._active:
                self._spinner.stop()
                _clear_current_line(self._console)
            try:
                yield
            finally:
                if self._spinner and self._active:
                    self._spinner.start()

        return _ctx()


class StreamRenderer:
    """Streaming renderer with Rich Live for in-place updates.

    During streaming: updates content in-place via Rich Live.
    On end: stops Live (transient=True erases it), then prints final render.

    Flow per round:
      spinner -> first delta -> header + Live updates ->
      on_end -> stop Live + final render
    """

    def __init__(
        self,
        render_markdown: bool = True,
        show_spinner: bool = True,
        bot_name: str = "Femtobot",
        bot_icon: str = "🐈",
        spacing_renderer: "TurnSpacingRenderer | None" = None,
    ):
        self._md = render_markdown
        self._show_spinner = show_spinner
        self._bot_name = bot_name
        self._bot_icon = bot_icon
        self._buf = ""
        self.streamed = False
        self._console = _make_console()
        self._live: Live | None = None
        self._spinner: ThinkingSpinner | None = None
        self._header_printed = False
        # Camada 4 — turn-spacing aesthetics. Default to legacy behaviour
        # (no extra spacing) when no renderer is supplied, so callers that
        # haven't migrated still see the original UX.
        self._spacing = spacing_renderer
        self._start_spinner()

    def _renderable(self):
        """Create a renderable from the current buffer.

        Camada 5 — when a spacing renderer is wired in with margin_x > 0,
        the rendered Markdown is wrapped in a Padding so the agent's reply
        doesn't sit flush against the terminal edges.
        """
        if self._md and self._buf:
            inner: RenderableType = Markdown(self._buf)
        else:
            inner = Text(self._buf or "")
        if self._spacing is not None and self._spacing.margin_x > 0:
            from rich.padding import Padding

            inner = Padding(inner, pad=(0, self._spacing.margin_x))
        return inner

    def _render_str(self) -> str:
        """Render current buffer to a plain string via Rich."""
        with self._console.capture() as cap:
            self._console.print(self._renderable())
        return cap.get()

    def _start_spinner(self) -> None:
        if self._show_spinner:
            self._spinner = ThinkingSpinner(bot_name=self._bot_name)
            self._spinner.__enter__()

    def _stop_spinner(self) -> None:
        if self._spinner:
            self._spinner.__exit__(None, None, None)
            self._spinner = None

    @property
    def console(self) -> Console:
        """Expose the Live's console so external print functions can use it."""
        return self._console

    @property
    def header_printed(self) -> bool:
        """Whether this turn has already opened the assistant output block."""
        return self._header_printed

    def ensure_header(self) -> None:
        """Stop transient status and print the assistant header once."""
        # A turn can print trace rows before the final answer, then restart the
        # spinner while tools run. The next answer delta still needs to stop
        # that spinner even though the header was already printed.
        self._stop_spinner()
        if self._header_printed:
            return
        self._console.print()
        # Camada 4 — when a spacing renderer is wired in, prefer its
        # role_header (colored bar) and the user-separator above the bar
        # so the agent's reply is visually framed against the previous
        # user input. Otherwise fall back to the legacy single-line header.
        if self._spacing is not None:
            self._spacing.print_user_separator(self._console)
            self._spacing.print_role_header(self._console)
        else:
            header = (
                f"{self._bot_icon} {self._bot_name}"
                if self._bot_icon
                else self._bot_name
            )
            self._console.print(f"[cyan]{header}[/cyan]")
        self._header_printed = True

    def pause_spinner(self):
        """Context manager: temporarily stop transient output for clean trace lines."""

        @contextmanager
        def _pause():
            live_was_active = self._live is not None
            if self._live:
                # Trace/reasoning can arrive after answer streaming has started.
                # Stop the transient Live view first so it does not leak a raw
                # partial markdown frame before the trace line.
                self._live.stop()
                self._live = None
            with self._spinner.pause() if self._spinner else nullcontext():
                yield
            # If more answer deltas arrive after the trace, on_delta() will
            # create a fresh Live using the existing buffer. If no deltas arrive,
            # on_end() prints the final buffered answer once.
            if live_was_active:
                return

        return _pause()

    def print_input_gap(self) -> None:
        """Print blank lines before the user input prompt (Camada 5 P2 fix).

        No-op when no spacing renderer is configured (legacy behaviour).
        """
        if self._spacing is not None:
            self._spacing.print_input_gap(self._console)

    def print_user_box(self) -> None:
        """Print the user-turn box (Camada 5 P3 fix).

        Called by the REPL just before reading user input, replacing the
        legacy plain "You:" prompt when ``turn_box=True``.
        """
        if self._spacing is not None:
            self._spacing.print_user_box(self._console)

    async def on_delta(self, delta: str) -> None:
        self.streamed = True
        self._buf += delta
        if self._live is None:
            if not self._buf.strip():
                return
            self.ensure_header()
            self._live = Live(
                self._renderable(),
                console=self._console,
                auto_refresh=False,
                transient=True,
            )
            self._live.start()
        else:
            self._live.update(self._renderable())
        self._live.refresh()

    async def on_end(self, *, resuming: bool = False) -> None:
        if self._live:
            # Double-refresh to sync _shape before stop() calls refresh().
            self._live.refresh()
            self._live.update(self._renderable())
            self._live.refresh()
            self._live.stop()
            self._live = None
        self._stop_spinner()
        if self._buf.strip():
            # Print final rendered content (persists after Live is gone).
            out = sys.stdout
            out.write(self._render_str())
            out.flush()
            # Camada 4 — print N blank lines after the completed turn so the
            # next ``You:`` prompt has room to breathe (issue UX-1).
            if self._spacing is not None:
                self._spacing.print_turn_gap(self._console)
        if resuming:
            self._buf = ""
            self._start_spinner()

    def stop_for_input(self) -> None:
        """Stop spinner before user input to avoid prompt_toolkit conflicts."""
        self._stop_spinner()

    def pause(self):
        """Context manager: pause spinner for external output. No-op once streaming has started."""
        if self._spinner:
            return self._spinner.pause()
        return nullcontext()

    async def close(self) -> None:
        """Stop spinner/live without rendering a final streamed round."""
        if self._live:
            self._live.stop()
            self._live = None
        self._stop_spinner()
