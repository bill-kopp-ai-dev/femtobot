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
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Column, Table
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
        bullets = tuple(
            b.group(1).strip() for b in _CHANGELOG_BULLET_RE.finditer(section)[:max_bullets]
            if b.group(1).strip()
        ) if False else []  # type: ignore[func-returns-value]
        # The walrus-free version (avoids the weird `if False` branch):
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

    def __rich_console__(self, console: Console, options: Any) -> None:  # noqa: D401
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
    if state == "propagating":
        if tokens is not None and tokens > 0:
            text.append(f"  ·  ↓ {tokens} tokens", style="dim")
        text.append(")", style="dim")
    text.append("  ·  esc to interrupt", style="dim")
    if state == "idle":
        text.append("  ·  ", style="dim")
        text.append("←", style="dim")
        text.append(" for agents", style="dim")
    return text


# ---------------------------------------------------------------------------
# Input pill
# ---------------------------------------------------------------------------


def render_input_pill(*, prompt: str = ">", placeholder: str = "", theme: CliTheme | None = None) -> RenderableType:
    """Render the input area with a top border line and the prompt glyph.

    The plan (D9) prefers ``>`` in ``compat`` mode (vs the legacy ``❯``).
    Callers wire this to ``prompt_toolkit`` for actual key handling; the
    pill here is just the visual frame that goes above the input box.
    """
    th = theme or get_theme("terracotta-claude")
    accent = th.accent
    bar = Text("─" * max(8, len(prompt) + len(placeholder) + 4), style=f"bold {accent}")
    text = Text()
    text.append(f"{prompt} ", style=f"bold {accent}")
    text.append(placeholder, style="")
    return Group(bar, text, bar)
