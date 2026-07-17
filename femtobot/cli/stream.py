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
from typing import Any

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


def _clear_live_block(console: Console, *, height: int = 1) -> None:
    """Erase an entire ``Live`` block before printing persistent output.

    PR 2.1 (longlogs remediation). The legacy ``_clear_current_line``
    only erases one line — when the ``Live`` spans multiple rows
    (status, hint, footer), the call leaves the leftover lines on
    screen and the next chunk of content interleaves with them
    (visible as fragments of the previous turn appearing as if they
    were part of the current turn).

    Behaviour:

    - When stdout is a TTY: writes ``\\x1b[2J`` (erase entire screen)
      followed by ``\\x1b[H`` (home cursor). Rich's own ``Live`` with
      ``transient=True`` already redraws nothing afterwards, so we
      get a clean screen without flickering.
    - When stdout is not a TTY: writes ``height`` newlines so the
      captured transcript still groups the cleared block as its own
      paragraph (the captured log no longer interleaves fragments).

    ``height`` is the number of rows the ``Live`` was occupying.
    Callers pass the current ``Live.render_height`` when known;
    defaults to 1 for safety.
    """
    file = console.file
    isatty = getattr(file, "isatty", lambda: False)
    if isatty():
        file.write("\x1b[2J\x1b[H")
    else:
        # Non-TTY: do not emit escape sequences (they would leak as
        # literal bytes in ``docker exec -i`` / piped consumers — see
        # ``_make_console`` and #3265). Use newlines instead.
        file.write("\n" * max(1, height))
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

    PR 2.2 (longlogs remediation): when ``elapsed_renderable`` is
    supplied, the spinner drives that renderable (a ``SpinnerWithElapsed``
    from ``cli.parity_widgets``) inside a Rich ``Live`` so the elapsed
    time and token counter refresh every frame instead of being a
    static "Femtobot is cogitating..." line. Defaults remain unchanged
    so the legacy ``ui_parity=off`` path keeps its byte-identical
    behaviour.
    """

    def __init__(
        self,
        console: Console | None = None,
        bot_name: str = "Femtobot",
        verb: str | None = None,
        spinner_style: str | None = None,
        verbs_enabled: bool = True,
        seed: int | None = None,
        elapsed_renderable: RenderableType | None = None,
    ):
        c = console or _make_console()
        self._console = c
        self._bot_name = bot_name
        self._verbs_enabled = verbs_enabled
        self._verb = verb or pick_verb(seed)
        text = self._render_text()
        spinner_name = resolve_spinner(spinner_style, seed=seed)
        self._spinner_name = spinner_name
        self._elapsed_renderable = elapsed_renderable
        # When ``elapsed_renderable`` is supplied, host it in a Live so
        # Rich drives the per-frame refresh of the elapsed text — this
        # is what the dead-code KNOWN GAP comment in parity_stream.py
        # was asking for. Otherwise keep using ``console.status`` so the
        # default path stays identical.
        if elapsed_renderable is not None:
            self._live = Live(
                elapsed_renderable,
                console=c,
                refresh_per_second=8,
                transient=True,
            )
            self._spinner = None
        else:
            self._live = None
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
        if self._live is not None:
            self._live.start()
        else:
            self._spinner.start()
        self._active = True
        return self

    def __exit__(self, *exc):
        self._active = False
        if self._live is not None:
            self._live.stop()
        else:
            self._spinner.stop()
        # PR 2.1 (longlogs remediation): clear the whole Live block,
        # not just one line, so the captured transcript does not leak
        # leftover fragments when stdout is not a TTY.
        _clear_live_block(self._console, height=1)
        return False

    def pause(self):
        """Context manager: temporarily stop spinner for clean output."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            if self._live is not None and self._active:
                self._live.stop()
                _clear_live_block(self._console, height=1)
            elif self._spinner and self._active:
                self._spinner.stop()
                _clear_current_line(self._console)
            try:
                yield
            finally:
                if self._live is not None and self._active:
                    self._live.start()
                elif self._spinner and self._active:
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
        # Set by ``on_end`` after the final render prints; consulted by
        # ``on_delta`` to swallow late chunks that arrive after the
        # stream is closed (race between the trailing body
        # ``OutboundMessage`` and the deltas — see ``longlogs.txt``
        # 2026-07-15 19:47 turn where the Opção 1 block rendered twice).
        self._ended = False
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

    def print_input_bar(self) -> None:
        """Print the parity input pill bar (plan §3 D9, Claude Code parity).

        The legacy ``StreamRenderer`` keeps the unframed ``You:`` prompt
        byte-identical to ``v0.1.0-ui.0`` — no bar is drawn. The parity
        layer overrides this to emit the accent rule via
        :func:`femtobot.cli.parity_widgets.render_input_bar_top`.
        """
        # Legacy profile: no framed input bar. Kept for protocol
        # compatibility so ``RendererLike`` is satisfied.
        return None

    @property
    def input_prompt_markup(self) -> Any:
        """Return the prompt glyph as ``HTML`` markup for ``prompt_async``.

        The legacy profile emits the same ``<b fg='ansiblue'>You:</b>``
        markup that was used prior to the parity bar rewrite. The parity
        layer overrides this with the bottom-rule + glyph markup.
        """
        from prompt_toolkit.formatted_text import HTML

        return HTML("<b fg='ansiblue'>You:</b> ")

    @property
    def input_toolbar_markup(self) -> Any:
        """Return the prompt toolbar markup for ``prompt_async``.

        Legacy profile keeps no extra toolbar under the prompt. The
        Claude-style compat profile overrides this with the box-closing
        rule + subtle ``manual mode on`` footer.
        """
        return None

    def print_cooked_footer(self) -> None:
        """Print the post-turn status footer.

        Bug A fix: the parity layer moved this call out of ``on_end``;
        the legacy profile keeps no-op parity to avoid behavioural drift
        on the v0.1.0-ui.0 byte-identical contract (the legacy REPL
        never printed a "Cooked for Ns" footer in the first place, so
        ``None`` here is correct).
        """
        return None

    def print_idle_footer(self) -> None:
        """Print the idle-time ``▌ manual mode on`` footer.

        v0.1.0-ui.1 polish: the parity profile shows Claude Code's
        two-line idle footer (top rule, prompt row, bottom rule, mode
        line). The legacy profile keeps no-op parity (its REPL has its
        own legacy footer logic in legacy code paths and we don't want
        to introduce churn on the ``off`` path).
        """
        return None

    async def on_delta(self, delta: str) -> None:
        # Defend against duplicate chunks arriving after ``on_end`` has
        # already printed the final render.  The agent loop can publish
        # the trailing body twice (once as a stream delta, once as the
        # ``_streamed`` final body) under race conditions observed in
        # ``longlogs.txt`` 2026-07-15 19:47 — without this guard the
        # entire response renders twice.
        if self._ended:
            return
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
            # ``_ended`` is set *after* the print so subsequent calls to
            # ``on_delta`` that re-emit the same buffer (race between the
            # trailing ``OutboundMessage`` carrying the full body and the
            # delta stream, see ``commands.py:_consume_outbound`` and
            # ``longlogs.txt`` 2026-07-15 19:47 turn where the Opção 1
            # block was rendered twice) no longer cause a second pass.
            # Only latch when this is the *true* end of the turn —
            # ``resuming=True`` means the runner is about to stream more
            # deltas for the same turn (after tool calls / length
            # recovery / intent-only pushback / injections), and those
            # are genuinely new content, not the racing duplicate.
            # Latching unconditionally here silently dropped every
            # post-tool-call answer for the rest of the turn.
            self._ended = not resuming
            out = sys.stdout
            out.write(self._render_str())
            out.flush()
            self._buf = ""
            # Camada 4 — print N blank lines after the completed turn so the
            # next ``You:`` prompt has room to breathe (issue UX-1).
            if self._spacing is not None:
                self._spacing.print_turn_gap(self._console)
        else:
            self._ended = not resuming
        if resuming:
            self._start_spinner()

    def stop_for_input(self) -> None:
        """Stop spinner before user input to avoid prompt_toolkit conflicts.

        Also resets ``_ended`` for the next turn. The REPL calls this once
        per loop iteration, right before it blocks on user input — i.e.
        strictly after the previous turn's final ``on_end`` and strictly
        before the next turn's first ``on_delta`` can fire. ``close()``
        performs the same reset, but on the streamed path it is only
        called when nothing streamed at all (see ``commands.py``'s
        ``elif renderer and not renderer.streamed``), which never fires
        again once a turn has streamed — so ``_ended`` would otherwise
        stay latched for the rest of the session after the first
        streamed turn, silently dropping every subsequent turn's output.
        """
        self._stop_spinner()
        self._ended = False

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
        # Reset ``_ended`` so a follow-up turn can stream again.  The
        # REPL keeps the same renderer across multiple turns; without
        # this the next ``on_delta`` would be silently dropped.
        self._ended = False
        self._buf = ""
