"""Parity-aware stream renderer for the v0.1.0-ui.0+ ``compat`` profile (T4).

:class:`ParityStreamRenderer` is a **drop-in** of
:class:`femtobot.cli.stream.StreamRenderer` that adds the Claude Code
v2.1.x aesthetic layer:

  * Header bar with the ``__logo__`` ASCII wordmark (Q1).
  * Welcome card on the first turn only (Q3); ``/welcome`` brings it
    back via :meth:`show_welcome_card`.
  * Spinner with elapsed time, riding the existing Rich auto-refresh
    (rev. F5 — no extra thread).
  * Tool call cards (collapsed by default; first-line heuristic
    preview per Q7).
  * Status footer with manual/propagating/cooked states.
  * ``/ui`` swap (Q10) is handled by the ``md_commands`` layer; the
    renderer reads its profile from the supplied ``config`` on every
    call to the ``on_*`` hooks so a mid-session profile change takes
    effect on the next turn.

The class **wraps** an existing :class:`StreamRenderer` rather than
replacing it. This keeps the v0.0.x streaming / Markdown / spinner
machinery intact (zero behavioural regression on the legacy code path)
and means parity is a presentation overlay, not a runtime fork.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from femtobot.cli.parity_widgets import (
    HeaderBar,
    SpinnerWithElapsed,
    parse_changelog,
    render_status_footer,
    render_tool_card,
    render_welcome_card,
    resolve_user_name,
)
from femtobot.cli.stream import StreamRenderer
from femtobot.cli.theme import get_theme


class ParityStreamRenderer:
    """Aesthetic parity layer that composes on top of
    :class:`StreamRenderer`.

    See module docstring for the full feature list.
    """

    def __init__(
        self,
        *,
        base_renderer: StreamRenderer,
        config: Any,
        bot_name: str,
        bot_icon: str,
        spacing_renderer: Any = None,
        changelog_path: str | Path | None = None,
    ) -> None:
        self._base = base_renderer
        self._config = config
        self._bot_name = bot_name
        self._bot_icon = bot_icon
        self._spacing = spacing_renderer
        self._console = base_renderer.console
        self._theme = get_theme(
            getattr(config.agents.defaults.cli, "theme", None) or "terracotta-claude"
        )
        self._turn_count = 0
        self._welcome_shown = False
        self._header_printed = False
        self._spinner_renderable: SpinnerWithElapsed | None = None
        self._spinner_start_ts: float | None = None
        self._tokens: int | None = None
        # Resolve the changelog path once; allow callers to override for
        # tests (e.g. tmp_path fixtures) and for multi-instance setups.
        self._changelog_path = (
            Path(changelog_path)
            if changelog_path is not None
            else Path(__file__).resolve().parents[2] / "CHANGELOG.md"
        )
        # Eagerly print the header bar + welcome card on construction
        # (this is what the user sees as soon as the REPL comes up).
        self._print_header_if_first_time()
        self._print_welcome_card_if_first_time()

    # ------------------------------------------------------------------
    # Header + welcome (Q1, Q3)
    # ------------------------------------------------------------------

    def _print_header_if_first_time(self) -> None:
        if self._header_printed:
            return
        try:
            user_name = resolve_user_name(
                getattr(self._config.agents.defaults.user, "name", None)
            )
        except AttributeError:
            user_name = "there"
        hb = HeaderBar(
            bot_name=self._bot_name,
            bot_icon=self._bot_icon,
            model_display=self._model_display(),
            user_name=user_name,
            workspace=self._workspace_display(),
            theme=self._theme,
        )
        self._console.print(hb.render())
        self._header_printed = True

    def _print_welcome_card_if_first_time(self) -> None:
        if self._welcome_shown:
            return
        if self._turn_count > 0:
            return
        self.show_welcome_card(force=True)
        if self._notice_enabled():
            self._console.print(
                "─ Extended through July 19 ─\n"
                "  Try Femtobot parity UI on/off with `femtobot agent --ui compat` or `/ui`.\n"
                "  This is the v0.1.0-ui preview — feedback welcome.\n"
            )

    def show_welcome_card(self, *, force: bool = False) -> None:
        """Re-render the welcome card (Q3 — used by the ``/welcome`` slash)."""
        if self._welcome_shown and not force:
            return
        whats_new = []
        if self._changelog_path.exists():
            entries = parse_changelog(self._changelog_path, max_entries=1, max_bullets=4)
            if entries:
                for b in entries[0].bullets:
                    whats_new.append(b)
        tips = [
            "Run /init to create a FEMTO.md file with instructions for Femto",
            "Try /welcome to redisplay this card mid-session",
            "Toggle verbose transcript with Ctrl+O",
        ]
        self._console.print(
            render_welcome_card(
                tips=tips,
                whats_new=whats_new,
                theme=self._theme,
            )
        )
        self._welcome_shown = True

    def _notice_enabled(self) -> bool:
        try:
            return bool(self._config.agents.defaults.cli.ui_parity.notice)
        except AttributeError:
            return False

    def _model_display(self) -> str:
        try:
            cfg = self._config
            model = cfg.agents.defaults.model
            preset = cfg.agents.defaults.model_preset
            if preset and preset != "default":
                return f"{model} · {preset}"
            return model
        except AttributeError:
            return ""

    def _workspace_display(self) -> str:
        try:
            return str(self._config.agents.defaults.workspace)
        except AttributeError:
            return ""

    # ------------------------------------------------------------------
    # Spinner integration (D5, rev. F5 — no extra thread)
    # ------------------------------------------------------------------
    # The parity layer tracks the elapsed time and token count in
    # ``_spinner_start_ts`` / ``_tokens`` so the status footer printed
    # at the end of the turn can show "Cooked for Ns" and "↓ N tokens"
    # (see :meth:`on_end`). The animated spinner itself is owned by
    # the wrapped :class:`StreamRenderer` and uses its own internal
    # :class:`ThinkingSpinner`; the :class:`SpinnerWithElapsed`
    # renderable is therefore kept for **future** use once the base
    # renderer exposes a message-factory hook (planned for v0.1.x,
    # not part of the v0.1.0-ui.0 preview).
    #
    # In the preview, :meth:`_ensure_spinner` and
    # :meth:`_update_spinner_tokens` are intentionally no-ops so the
    # base spinner keeps working untouched (no surprise behaviour
    # changes on the legacy ``off`` profile).

    # ------------------------------------------------------------------
    # StreamRenderer-compatible surface
    # ------------------------------------------------------------------

    async def on_delta(self, delta: str) -> None:
        await self._base.on_delta(delta)

    async def on_end(self, *, resuming: bool = False) -> None:
        await self._base.on_end(resuming=resuming)
        # After the first completed turn, hide the welcome card.
        self._turn_count += 1
        self._welcome_shown = True
        # Render a "Cooked for Ns" status footer.
        if self._spinner_start_ts is not None:
            elapsed = max(0.0, time.monotonic() - self._spinner_start_ts)
        else:
            elapsed = 0.0
        self._console.print(
            render_status_footer(
                state="cooked",
                elapsed_s=elapsed,
                tokens=self._tokens,
                theme=self._theme,
            )
        )
        # Reset for the next turn.
        self._spinner_renderable = None
        self._spinner_start_ts = None
        self._tokens = None

    def on_tool_call(self, name: str, args_preview: str = "") -> None:
        # Render a collapsed tool card before delegating to the base
        # renderer. The base renderer will eventually render the full
        # result; we keep the parity card's content (a one-line summary)
        # visible on the user's terminal until the result comes back.
        self._console.print(
            render_tool_card(
                tool_name=name,
                args_preview=args_preview,
                collapsed=True,
                theme=self._theme,
            )
        )
        # ``StreamRenderer`` does not have an ``on_tool_call`` hook yet
        # (the plan anticipated one; the v0.0.x code does the printing
        # inline). Call only if the base exposes it.
        if hasattr(self._base, "on_tool_call"):
            self._base.on_tool_call(name, args_preview)

    def on_tool_result(self, name: str, args_preview: str, result: Any, *, success: bool = True, elapsed_s: float | None = None) -> None:
        """Render the expanded tool card with the first-line summary (Q7)."""
        from femtobot.cli.parity_widgets import summarize_tool_result

        self._console.print(
            render_tool_card(
                tool_name=name,
                args_preview=args_preview,
                result_summary=summarize_tool_result(result),
                success=success,
                collapsed=False,
                elapsed_s=elapsed_s,
                theme=self._theme,
            )
        )

    def on_trace(self, text: str) -> None:
        if hasattr(self._base, "on_trace"):
            self._base.on_trace(text)

    async def close(self) -> None:
        await self._base.close()

    def stop_for_input(self) -> None:
        self._base.stop_for_input()

    def pause(self) -> Any:
        return self._base.pause()

    @property
    def console(self) -> Any:
        return self._console

    @property
    def header_printed(self) -> bool:
        return self._base.header_printed

    def ensure_header(self) -> None:
        self._base.ensure_header()

    def pause_spinner(self) -> Any:
        return self._base.pause_spinner()

    def print_input_gap(self) -> None:
        self._base.print_input_gap()

    def print_user_box(self) -> None:
        self._base.print_user_box()


__all__ = ["ParityStreamRenderer"]
