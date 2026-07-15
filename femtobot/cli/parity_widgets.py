"""Reusable Rich renderables for the v0.1.0-ui.0+ parity layer.

This module collects the small "primitives" used by
:mod:`femtobot.cli.parity_stream` and by the future Textual TUI (RC):

  * :class:`HeaderBar`         — first-screen header (logo + name + model + workspace)
  * :class:`WelcomeCard`       — first-turn tips / what's-new card
  * :class:`WhatsNewCard`      — release-notes card parsed from CHANGELOG.md
  * :class:`ToolCard`          — collapsed / expanded tool-call card
  * :class:`SpinnerWithElapsed`— spinner + elapsed-time + tokens
  * :class:`StatusFooterParity`— bottom-of-screen footer (manual / propagating / cooked)
  * :class:`InputPill`         — input area with a border-top accent line

All renderables are pure: they take the data they need as constructor
arguments and produce a Rich ``Renderable`` on demand. No I/O, no
console-state coupling, no global flags. This makes them trivially
snapshot-testable and keeps :mod:`parity_stream` slim.

Plan references: §3 (visual specification), §4 (Camada 6 widgets),
§5 D3 (welcome after 1 turn), §5 D7 (logo wordmark), §5 D8 (tool
cards with first-line heuristic), §5 D5 (spinner elapsed).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rich.box import ROUNDED
from rich.console import Console, ConsoleOptions, RenderableType
from rich.panel import Panel
from rich.text import Text

from femtobot import __logo__
from femtobot.cli.theme import CliTheme, get_theme
from femtobot.cli.whimsy import pick_verb

# ---------------------------------------------------------------------------
# User-name resolution
# ---------------------------------------------------------------------------

_USER_NAME_PLACEHOLDER = "<your-name>"


def resolve_user_name(configured: str | None) -> str:
    """Resolve the human's display name for the parity header / welcome.

    Lookup chain (per plan Q2):

      1. ``configured`` (from ``config.agents.user.name``)
         — unless it's empty / the ``<your-name>`` placeholder.
      2. ``os.getlogin()`` — best effort, returns ``""`` on failure.
      3. The ``USER`` / ``LOGNAME`` environment variable.
      4. The literal string ``"there"`` as a last-resort friendly fallback.
    """
    if configured and configured.strip() and configured.strip() != _USER_NAME_PLACEHOLDER:
        return configured.strip()
    for getter in (os.getlogin, lambda: os.environ.get("USER") or os.environ.get("LOGNAME") or ""):
        try:
            candidate = (getter() or "").strip()
        except Exception:
            candidate = ""
        if candidate:
            return candidate
    return "there"


# ---------------------------------------------------------------------------
# CHANGELOG.md parsing (Q6)
# ---------------------------------------------------------------------------

_CHANGELOG_HEADING_RE = re.compile(r"^##\s*\[?([\w.\-+]+)\]?", re.MULTILINE)
# Bullets in a CHANGELOG are written as ``- <text>`` and almost never look
# like dates. Require the bullet marker to NOT be followed by 4 digits
# and a dash (the common date format ``- 2026-07-15`` that appears as a
# "Releases" subsection in some Markdown styles).
_CHANGELOG_BULLET_RE = re.compile(
    r"^[\s]*[-*]\s+(?![\d]{4}-[\d]{2}-[\d]{2})(.+?)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ChangelogEntry:
    """One section of ``CHANGELOG.md`` (between two ``##`` headings)."""

    version: str
    bullets: tuple[str, ...]


def parse_changelog(path: str | Path, *, max_entries: int = 1, max_bullets: int = 4) -> list[ChangelogEntry]:
    """Return the top-N entries of a CHANGELOG.md-style file.

    The parser is intentionally lenient: it splits on ``## [vX.Y.Z]`` or
    ``## vX.Y.Z`` headings and harvests the first ``max_bullets`` bullet
    lines of each. Anything that does not look like bullets is dropped
    silently — the caller can fall back to the raw text if it needs to.

    Returns an empty list if the file is missing or unparseable; never
    raises (callers depend on this for a graceful "no what's-new" path).
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # Find all heading positions in one pass.
    matches = list(_CHANGELOG_HEADING_RE.finditer(text))
    if not matches:
        return []

    out: list[ChangelogEntry] = []
    for i, m in enumerate(matches):
        if len(out) >= max_entries:
            break
        version = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]
        raw_bullets = list(_CHANGELOG_BULLET_RE.finditer(section))[:max_bullets]
        bullets = tuple(b.group(1).strip() for b in raw_bullets if b.group(1).strip())
        out.append(ChangelogEntry(version=version, bullets=bullets))
    return out


# ---------------------------------------------------------------------------
# Header bar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeaderBar:
    """First-screen header (logo wordmark + identity + workspace).

    The plan calls for the ``__logo__`` ASCII wordmark (Q1) plus a
    one-line identity ("Sonnet 5 · preset · workspace"). HeaderBar is
    intended to be printed **once** at the top of the welcome screen —
    not between turns (Camada 4 spacing still rules there).
    """

    bot_name: str
    bot_icon: str
    model_display: str
    user_name: str
    workspace: str
    theme: CliTheme

    def render(self) -> RenderableType:
        accent = self.theme.primary
        bar = Text()
        bar.append("─ ", style=f"bold {accent}")
        bar.append(self.bot_name, style="bold")
        bar.append(" ─", style=f"bold {accent}")
        bar.append("\n")
        bar.append("  Welcome back ", style="")
        bar.append(self.user_name, style=f"bold {accent}")
        bar.append("!\n")
        bar.append(Text(self.__logo_str(), style="dim"))
        bar.append("\n")
        bar.append(f"  {self.model_display}  ·  {self.workspace}\n", style="dim")
        return bar

    @staticmethod
    def __logo_str() -> str:
        # ``__logo__`` is the multi-line ASCII wordmark from
        # ``femtobot/__init__.py:29-36``. Returned as-is; the dim style
        # in ``render()`` de-emphasises it without losing the shape.
        return __logo__.rstrip("\n")


# ---------------------------------------------------------------------------
# Welcome card (Q3 — only on first turn, hide after, /welcome brings back)
# ---------------------------------------------------------------------------


def render_welcome_card(
    *,
    tips: Iterable[str],
    whats_new: Iterable[str] | None = None,
    theme: CliTheme | None = None,
    show_whats_new: bool = True,
) -> RenderableType:
    """Render the Tips + (optional) What's new card.

    ``tips`` — the bullet lines for "Tips for getting started".
    ``whats_new`` — bullet lines for "What's new in vX.Y.Z" (if
        ``show_whats_new`` is True and the list is non-empty).
    ``theme`` — the active :class:`CliTheme` (defaults to
        ``terracotta-claude``).
    """
    th = theme or get_theme("terracotta-claude")
    accent = th.welcome_border or th.primary

    body = Text()
    for tip in tips:
        body.append("• ", style=f"bold {accent}")
        body.append(f"{tip}\n", style="")
    if show_whats_new and whats_new:
        body.append("\n", style="")
        body.append("What's new\n", style=f"bold {accent}")
        for line in whats_new:
            body.append("• ", style=f"bold {accent}")
            body.append(f"{line}\n", style="")
    return Panel(
        body,
        title="Tips for getting started",
        title_align="left",
        border_style=accent,
        box=ROUNDED,
        padding=(0, 1),
    )


# ---------------------------------------------------------------------------
# Tool call card (D8 — collapsed by default, first-line heuristic preview)
# ---------------------------------------------------------------------------


def summarize_tool_result(result: Any, *, max_chars: int = 120) -> str:
    """Heuristic first-line summary for a tool result (Q7).

    Returns the first non-empty, non-trivial line of ``result``, trimmed
    of common JSON / bullet / markdown prefixes, capped at ``max_chars``.
    Falls back to ``"(no output)"`` when ``result`` is empty.
    """
    if result is None:
        return "(no output)"
    if not isinstance(result, str):
        result = str(result)
    result = result.replace("\r\n", "\n")
    for raw in result.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Strip common prefixes that pollute previews.
        for prefix in ("{", "[", '"', "  - ", "  * ", "  > "):
            if line.startswith(prefix):
                line = line[len(prefix):].lstrip()
        if not line:
            continue
        if len(line) > max_chars:
            return line[: max_chars - 1] + "…"
        return line
    return "(no output)"


def render_tool_card(
    *,
    tool_name: str,
    args_preview: str,
    result_summary: str | None = None,
    success: bool = True,
    collapsed: bool = True,
    elapsed_s: float | None = None,
    theme: CliTheme | None = None,
) -> RenderableType:
    """Render a single tool call card (Claude Code v2.1.x aesthetic).

    Collapsed (default): one-line ``● <name>(<args>)``.
    Expanded:            two-line ``● <name>(<args>)`` / ``  ⎿ <summary>``.

    ``result_summary`` — if provided AND ``collapsed`` is False, shown on
    the second line with a dim colour.
    """
    th = theme or get_theme("terracotta-claude")
    border = th.tool_card_border or th.primary
    bullet_color = th.success if success else th.error
    elapsed_str = f" · {elapsed_s:.1f}s" if elapsed_s is not None and elapsed_s >= 0.5 else ""

    head = Text()
    head.append("● ", style=f"bold {bullet_color}")
    head.append(_humanize_tool_name(tool_name), style="bold")
    head.append("(", style="dim")
    head.append(args_preview or "", style="")
    head.append(")", style="dim")
    if collapsed:
        head.append(elapsed_str, style="dim")
        return head

    out = Text()
    out.append(head)
    if result_summary is not None:
        out.append("\n")
        out.append("  ⎿ ", style=f"bold {border}")
        out.append(result_summary, style="dim")
        if elapsed_str:
            out.append(elapsed_str, style="dim")
    return out


def _humanize_tool_name(name: str) -> str:
    """``web_search`` → ``Web Search``, ``read_file`` → ``Read File``."""
    if not name:
        return name
    return " ".join(part.capitalize() for part in name.replace("-", "_").split("_") if part)


# ---------------------------------------------------------------------------
# Spinner with elapsed time (D5 — uses Rich auto-refresh; no extra thread)
# ---------------------------------------------------------------------------


@dataclass
class SpinnerWithElapsed:
    """A renderable that pairs a whimsical verb with elapsed seconds.

    The renderable is **stateless** from the caller's perspective: it
    reads the current time at every ``__rich_console__`` call. Callers
    that wire it into a ``Live``/``Status`` get the auto-refresh that
    the underlying Live already runs for spinner animation — no extra
    thread is needed (rev. F5 of the plan).
    """

    bot_name: str
    verb: str | None = None
    start_time: float | None = None
    tokens: int | None = None
    thoughts_s: float | None = None
    theme: CliTheme | None = None

    def __post_init__(self) -> None:
        if self.verb is None:
            self.verb = pick_verb()
        if self.start_time is None:
            self.start_time = time.monotonic()
        if self.theme is None:
            self.theme = get_theme("terracotta-claude")

    def elapsed_s(self) -> float:
        return max(0.0, time.monotonic() - (self.start_time or time.monotonic()))

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> None:  # noqa: D401
        # We are a renderable, not a drawable — but the call signature
        # lets the Live poll us cheaply per frame.
        accent = self.theme.success if self.theme else "green"
        text = Text()
        text.append("✻ ", style=f"bold {accent}")
        text.append(f"{self.bot_name} is {self.verb}", style="")
        text.append(f"  ({self.elapsed_s():.0f}s", style="dim")
        if self.tokens is not None and self.tokens > 0:
            text.append(f"  ·  ↓ {self.tokens} tokens", style="dim")
        if self.thoughts_s is not None and self.thoughts_s >= 0.5:
            text.append(f"  ·  thought for {self.thoughts_s:.0f}s", style="dim")
        text.append(")", style="dim")
        console.print(text, end="")


# ---------------------------------------------------------------------------
# Status footer (Camada 6 — replaces the current empty footer)
# ---------------------------------------------------------------------------


def render_status_footer(
    *,
    mode: str = "manual",
    state: str = "idle",
    elapsed_s: float | None = None,
    tokens: int | None = None,
    theme: CliTheme | None = None,
) -> RenderableType:
    """Render the bottom-of-screen status footer.

    ``state``     — ``"idle"`` (between turns) | ``"propagating"`` |
                    ``"cooked"`` (turn complete).
    ``mode``      — ``"manual"`` (current Femtobot default).
    """
    th = theme or get_theme("terracotta-claude")
    accent = th.success
    if state == "propagating":
        glyph = "*"
        glyph_style = f"bold {accent}"
    elif state == "cooked":
        glyph = "✻"
        glyph_style = f"bold {accent}"
    else:
        glyph = "⏸"
        glyph_style = "dim"

    text = Text()
    text.append(f"{glyph} ", style=glyph_style)
    label = {
        "propagating": f"Propagating… ({elapsed_s:.0f}s" if elapsed_s is not None else "Propagating…",
        "cooked": f"Cooked for {elapsed_s:.0f}s" if elapsed_s is not None else "Cooked",
        "idle": f"{mode} mode on",
    }.get(state, f"{mode} mode on")
    text.append(label, style=glyph_style if state != "idle" else "dim")
    if state == "propagating" and elapsed_s is not None:
        # Only close the paren we actually opened above — without the
        # ``elapsed_s is not None`` guard this appended a dangling ``)``
        # whenever propagating was rendered with no elapsed time yet.
        if tokens is not None and tokens > 0:
            text.append(f"  ·  ↓ {tokens} tokens", style="dim")
        text.append(")", style="dim")
    text.append("  ·  esc to interrupt", style="dim")
    if state == "idle":
        text.append("  ·  ", style="dim")
        text.append("←", style="dim")
        text.append(" for agents", style="dim")
    return text


def render_status_footer_idle(*, mode: str = "manual", theme: CliTheme | None = None) -> RenderableType:
    """Render the bottom-of-screen "manual mode on" footer.

    Plan §3 D9 (T4): the Claude-Code-style input pill bar replaces the
    legacy idle footer under ``ui_parity=compat``. This helper is the
    pure renderable, gated by ``renderer.print_input_bar`` callers (see
    :meth:`ParityStreamRenderer.print_input_bar`); if ``print_input_bar``
    is suppressed, this remains the fallback so legacy callers still
    see a status row.
    """
    return render_status_footer(mode=mode, state="idle", theme=theme)


# ---------------------------------------------------------------------------
# Input pill bar (Claude Code v2.1.x parity, plan §3 D9)
# ---------------------------------------------------------------------------
#
# The Claude Code REPL frames its input with a thin horizontal accent rule
# above *and* below the prompt glyph. Implementing it as a single Rich
# renderable is convenient, but the bottom bar has to redraw on every
# keypress — prompt_toolkit owns the input redraw and only honors plain
# ANSI/HTML markup it can render itself. We therefore expose two
# helpers:
#
#   :func:`render_input_bar_top`           — full-width ``Rule`` rendered
#     just above the prompt (printed *before* ``patch_stdout()``).
#   :func:`render_input_bar_bottom_markup` — bottom rule + bold ``>`` glyph
#     in the same logical row as the prompt, returned as prompt_toolkit
#     ``HTML`` markup so the toolkit re-draws it cleanly on every key
#     event.
#
# Color is sourced from ``theme.welcome_border`` so the bar visually
# matches the Welcome card / What's-new box (visual coherence).
#
# ``width`` — terminal width to render against (defaults to ``80`` so the
#     pure helpers are unit-testable without a real console).
# ``margin_x`` — horizontal margin (Camada 5) subtracted from ``width``
#     so the bar sits flush with the agent reply's padding.

from prompt_toolkit.formatted_text import HTML

_INPUT_BAR_MIN_WIDTH = 24
_INPUT_BAR_RULE_CHAR = "─"

# Hex colors that the prompt_toolkit default toolbar style ("reverse")
# produces a saturated full-background fill for. We soften the rule to
# keep the bar readable against the terminal background while staying
# on-theme.
_HEAVY_BORDER_HEX = {"#d77757", "#cf6a4c", "#ff6b80", "#ffaa00"}
_HEAVY_BORDER_SOFTEN_MAP = {
    "#d77757": "#8a5a4b",
    "#cf6a4c": "#8a5a4b",
    "#ff6b80": "#a05a64",
    "#ffaa00": "#a07a3c",
}


def _softer_border_color(theme: "CliTheme | None") -> str:
    """Pick the bar color, slightly desaturating if the theme is loud.

    Welcome/welcome_border accent (used for the bar) is intentionally
    quieter than the agent reply accent so the input area doesn't
    compete with the chat content. ``#d77757`` is the project default;
    we map it and a couple of loud neighbours to a muted rose.
    """
    th = theme or get_theme("terracotta-claude")
    border = th.welcome_border or th.primary
    if border.lower() in _HEAVY_BORDER_HEX:
        return _HEAVY_BORDER_SOFTEN_MAP.get(border.lower(), border)
    return border


def _resolve_width(*, width: int | None, margin_x: int | None = 0) -> int:
    """Return the bar width, clamped to ``[_INPUT_BAR_MIN_WIDTH, width]``."""
    if width is None:
        width = 80
    mx = max(0, margin_x or 0)
    inner = max(_INPUT_BAR_MIN_WIDTH, width - 2 * mx)
    return inner


def render_input_bar_top(
    *,
    width: int | None = None,
    margin_x: int | None = 0,
    theme: CliTheme | None = None,
) -> RenderableType:
    """Return a thin horizontal accent ``Rule`` printed above the prompt row.

    The bar spans the full available width minus the lateral margin used
    by Camada 5 spacing so it lines up with the agent reply's padding.
    Returns an empty ``Text`` when ``width`` is so narrow that the bar
    would lose visual meaning — callers should never invoke this in that
    regime (the factory gates the bar on TTY width ≥ 40 already).
    """
    th = theme or get_theme("terracotta-claude")
    accent = _softer_border_color(th)
    bar_width = _resolve_width(width=width, margin_x=margin_x)
    rule = Text(_INPUT_BAR_RULE_CHAR * bar_width, style=f"bold {accent}")
    return rule


def render_input_bar_bottom_markup(
    *,
    width: int | None = None,
    margin_x: int | None = 0,
    prompt: str = ">",
    placeholder: str = "",
    theme: CliTheme | None = None,
    cursor: str = "▌",
) -> str:
    """Return the prompt row markup for the Claude-style input box.

    prompt_toolkit re-renders this string on every key event. We use
    ``HTML`` (not a Rich renderable) because prompt_toolkit cannot
    consume ``Text``/``Rule`` directly; ANSI control characters would
    leak into the editable buffer otherwise.

    Layout (matches Claude Code v2.1.x)::

        ❯  Nova mensagem▌                                 (empty buffer)
        ❯  typed input                                    (typing)

    The ``cursor`` glyph sits inline next to the placeholder to mimic
    Claude's pulsing cursor (the terminal renders it visibly). When
    the user starts typing, prompt_toolkit swaps the placeholder for
    their actual buffer content; we always emit the empty-state markup
    here and let the toolkit do the rest.

    The top border of the box is rendered separately by
    :func:`render_input_bar_top`; the bottom border + footer live in
    :func:`render_input_toolbar_markup`.
    """
    th = theme or get_theme("terracotta-claude")
    accent = _softer_border_color(th)
    _resolve_width(width=width, margin_x=margin_x)
    # HTML escaping: the placeholder /
    # prompt / cursor are user-controlled strings so we escape ``<>&``
    # to keep prompt_toolkit's HTML parser happy.
    escaped_prompt = _html_escape(prompt)
    escaped_cursor = _html_escape(cursor)
    escaped_placeholder = _html_escape(placeholder) if placeholder else ""
    # Two-space gap between glyph and placeholder so they never sit
    # glued together — fixes the visual "❯Nova mensagem" seen in the
    # v0.1.0-ui.1 preview build (Bug D).
    if placeholder:
        body = (
            f"<prompt><b><style fg='{accent}'>{escaped_prompt}</style></b></prompt>  "
            f"<placeholder><style fg='ansibrightblack'>{escaped_placeholder}</style></placeholder>"
            f"<cursor><style fg='{accent}'>{escaped_cursor}</style></cursor>"
        )
    else:
        body = (
            f"<prompt><b><style fg='{accent}'>{escaped_prompt}</style></b></prompt>  "
            f"<cursor><style fg='{accent}'>{escaped_cursor}</style></cursor>"
        )
    return HTML(body)


def render_input_toolbar_markup(
    *,
    width: int | None = None,
    margin_x: int | None = 0,
    mode: str = "manual",
    theme: CliTheme | None = None,
) -> str:
    """Return the bottom border + footer text under the input box.

    This is rendered via ``PromptSession.prompt_async(bottom_toolbar=...)``.
    The first line closes the input box, the second line is the subtle
    separator text between the prompt area and the bottom of the
    terminal, matching Claude Code's layout:

    ``────────────────────``
    ``▌ manual mode on``
    """
    th = theme or get_theme("terracotta-claude")
    accent = _softer_border_color(th)
    footer_color = th.primary
    bar_width = _resolve_width(width=width, margin_x=margin_x)
    rule = _INPUT_BAR_RULE_CHAR * bar_width
    escaped_rule = rule
    escaped_mode = _html_escape(mode)
    body = (
        f"<rule><style fg='{accent}'>{escaped_rule}</style></rule>\n"
        f"<footer><style fg='{footer_color}'>▌ {escaped_mode} mode on</style></footer>"
    )
    return HTML(body)


def _html_escape(text: str) -> str:
    """Escape characters that prompt_toolkit's HTML formatter would interpret.

    ``<`` / ``>`` / ``&`` are the only ones that matter for our placeholders
    / prompts (we never embed user input here, so this is defensive).
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# Backwards-compatible alias — older callers (and the existing test suite)
# referenced ``render_input_pill`` even though it was never wired in. Keep a
# thin re-export so nothing breaks during the rename.
def render_input_pill(*, prompt: str = ">", placeholder: str = "", theme: CliTheme | None = None) -> RenderableType:
    """Deprecated alias. Use :func:`render_input_bar_top` instead.

    Kept so the import in any legacy test / module doesn't break. The
    contents have been adapted to the new bar-only shape (a single
    accent rule); the two-piece split lives in
    :func:`render_input_bar_top` + :func:`render_input_bar_bottom_markup`.
    """
    return render_input_bar_top(theme=theme)
