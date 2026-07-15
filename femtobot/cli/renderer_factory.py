"""Renderer factory for the v0.1.0-ui.0+ parity layer (T3).

Chooses between the legacy :class:`femtobot.cli.stream.StreamRenderer`
(``"off"`` profile), the parity Rich Live renderer
(:class:`femtobot.cli.parity_stream.ParityStreamRenderer`, ``"compat"``
profile), and (in the RC only — not the v0.1.0-ui.0 preview) the Textual
TUI (``"full"`` profile, rev. F4 of the plan).

Auto-fallback rules (D2):

  * stdout is **not** a TTY → force ``"off"`` (preserves pipes / docker
    exec / ``tee``).
  * ``NO_COLOR`` is set → force ``"off"`` (Rich loses colour codes
    anyway, and the parity widgets would render with broken styles).
  * ``TERM=dumb`` → force ``"off"``.
  * User requested ``"full"`` but ``ui_parity=full`` is **not available
    in the preview** → emit a clear one-line message and fall back to
    ``"off"`` (the resolver never raises; the agent loop continues
    working with the legacy renderer).

The factory is intentionally a **function** (not a class) — the only
state it owns is the resolver, which is pure.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Protocol, runtime_checkable

from femtobot.cli.stream import StreamRenderer


@runtime_checkable
class RendererLike(Protocol):
    """Protocol matching the surface area a parity / legacy renderer
    must expose to drop into the agent loop.

    The agent loop calls ``on_delta`` / ``on_end`` / ``on_tool_call``
    / ``on_trace`` — see ``femtobot.cli.stream.StreamRenderer``. We
    declare them as ``Any``-returning callables so both async and
    sync implementations satisfy the protocol.
    """

    async def on_delta(self, delta: str) -> Any: ...
    async def on_end(self, *, resuming: bool = ...) -> Any: ...
    def on_tool_call(self, name: str, args_preview: str = "") -> Any: ...
    def on_trace(self, text: str) -> Any: ...
    async def close(self) -> Any: ...
    def stop_for_input(self) -> Any: ...
    def pause(self) -> Any: ...
    @property
    def console(self) -> Any: ...
    @property
    def header_printed(self) -> bool: ...
    def ensure_header(self) -> Any: ...
    def pause_spinner(self) -> Any: ...
    def print_input_gap(self) -> Any: ...
    def print_user_box(self) -> Any: ...
    def print_input_bar(self) -> Any: ...
    def print_cooked_footer(self) -> Any: ...
    def print_idle_footer(self) -> Any: ...
    @property
    def input_prompt_markup(self) -> Any: ...


def _is_color_disabled() -> bool:
    """Return True if the user has asked for no colour."""
    if os.environ.get("NO_COLOR"):
        return True
    if (os.environ.get("TERM") or "").lower() == "dumb":
        return True
    return False


def _resolve_profile(config: Any) -> str:
    """Apply the plan D2 auto-fallback rules to the configured profile.

    Returns one of ``"off"``, ``"compat"``, ``"full"``.

    Order of precedence (highest first):

      1. TTY check (``sys.stdout.isatty()``).
      2. ``NO_COLOR`` / ``TERM=dumb`` → ``"off"``.
      3. The user-configured ``agents.cli.ui_parity.profile`` value.
      4. Unknown values silently map to ``"off"``.
    """
    if not sys.stdout.isatty():
        return "off"
    if _is_color_disabled():
        return "off"
    try:
        requested = config.agents.defaults.cli.ui_parity.profile
    except AttributeError:
        return "off"
    if requested not in ("off", "compat", "full"):
        return "off"
    return requested


def _full_unavailable_message() -> str:
    """Return the message printed when ``ui_parity=full`` is requested
    in a release that has not enabled it yet (rev. F4 — only the RC
    ``v0.1.0-ui.1`` will ship Textual)."""
    return (
        "ui_parity=full (Textual TUI) is not available in this preview "
        "release — it arrives in v0.1.0-ui.1 (RC). Falling back to 'off' "
        "for this session. Try `femtobot agent --ui compat` instead."
    )


def build_renderer(
    config: Any,
    *,
    bot_name: str | None = None,
    bot_icon: str | None = None,
    spacing_renderer: Any = None,
    render_markdown: bool = True,
    show_spinner: bool = True,
) -> RendererLike:
    """Build the active stream renderer.

    Falls back to :class:`StreamRenderer` whenever the requested profile
    is unavailable, the TTY is not a real one, or ``NO_COLOR``/``TERM=dumb``
    is in effect. Never raises.
    """
    bot_name = bot_name or (
        getattr(config.agents.defaults, "bot_name", None) or "Femtobot"
    )
    bot_icon = bot_icon if bot_icon is not None else (
        getattr(config.agents.defaults, "bot_icon", None) or "🐈"
    )

    profile = _resolve_profile(config)

    # Always build the base StreamRenderer — even in compat mode, it is
    # the lower layer the parity renderer composes on top of.
    base = StreamRenderer(
        render_markdown=render_markdown,
        show_spinner=show_spinner,
        bot_name=bot_name,
        bot_icon=bot_icon,
        spacing_renderer=spacing_renderer,
    )

    if profile == "off":
        return base

    if profile == "compat":
        try:
            # Lazy import — the parity renderer pulls in additional
            # modules (parity_widgets + the live renderable machinery),
            # which we only want to pay for when the user opts in.
            from femtobot.cli.parity_stream import ParityStreamRenderer

            return ParityStreamRenderer(
                base_renderer=base,
                config=config,
                bot_name=bot_name,
                bot_icon=bot_icon,
                spacing_renderer=spacing_renderer,
            )
        except Exception as exc:  # pragma: no cover - defensive
            # If anything in the parity renderer blows up at import /
            # construction time, we still want the REPL to come up.
            # Print a one-line notice and fall back to the legacy
            # renderer so the session is not lost.
            try:
                base.console.print(
                    f"[warning]ui_parity=compat failed to initialise: {exc!r}. "
                    "Falling back to off.[/warning]"
                )
            except Exception:
                pass
            return base

    if profile == "full":
        # Plan §5 D1 + rev. F4: ``full`` is NOT available in the
        # preview release. We inform the user, then return the base
        # renderer so the REPL keeps working. The Textual app is wired
        # in v0.1.0-ui.1 (RC) — the wrapper around the factory call in
        # ``cli/commands.py::agent`` will short-circuit before this
        # point once ``ui_parity=full`` becomes usable.
        try:
            base.console.print(f"[warning]{_full_unavailable_message()}[/warning]")
        except Exception:
            print(_full_unavailable_message(), file=sys.stderr)
        return base

    # Defensive: unknown profile ⇒ legacy renderer.
    return base


__all__ = [
    "RendererLike",
    "build_renderer",
]
