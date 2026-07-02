"""Transcript buffer for the CLI REPL — supports collapsed/verbose tool call rendering.

Inspired by Claude Code's transcript viewer (Ctrl+O toggle):
``FEMTOBOT_CLI_REFACTOR_PLAN.md`` Camada 2, T2.3 and Camada 3, T3.2.

Concept
~~~~~~~
Each completed turn is stored as a :class:`TurnTranscript`.  When a turn
contains tool calls, it is stored in collapsed form: a one-line summary
("3 tool calls used") with an expandable detail buffer.  ``Ctrl+O`` in the
REPL switches between collapsed (default) and verbose (full output) mode.

:class:`TranscriptBuffer` holds the last N completed turns in a deque.
It is updated by the REPL after each turn ends.

Camada 3 (T3.2) — virtual scrolling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Once a turn is committed, it is "frozen" (rendered once via
``console.print`` with newline freeze) and appended to ``self.committed``
as plain text.  Only the *current* turn lives in the live area
(``self._current``).  ``get_visible_window`` returns only the slice of
lines that fits in the viewport, which is what the renderer iterates over
on each frame — never the whole transcript.  This keeps render cost
O(viewport) instead of O(transcript).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from rich.console import Console, RenderableType
    from rich.table import Table
    from rich.text import Text

# Lines stored in the frozen area are plain strings (already rendered).
# Lines stored in the live area may still be Rich renderables that need
# ``.plain`` extraction for the viewport query.
FrozenLine = str
LiveLine = Union[str, "RenderableType"]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ToolCallSummary:
    """One tool call within a turn."""

    tool_name: str
    args_preview: str = ""  # truncated one-liner of the arguments
    result_preview: str = ""  # truncated result
    exit_code: int | None = None
    duration_ms: float | None = None


@dataclass
class TurnTranscript:
    """A single completed turn in the transcript."""

    turn_id: str
    user_input: str  # first line of the user's input
    assistant_content: str = ""
    tool_calls: list[ToolCallSummary] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    collapsed: bool = True  # show brief summary vs full output

    @property
    def has_tools(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def tool_summary(self) -> str:
        if not self.tool_calls:
            return ""
        unique_tools = {tc.tool_name for tc in self.tool_calls}
        if len(unique_tools) == 1:
            name = next(iter(unique_tools))
            return f"{len(self.tool_calls)}× {name}"
        return f"{len(self.tool_calls)} tools: {', '.join(sorted(unique_tools))}"


# ---------------------------------------------------------------------------
# Buffer
# ---------------------------------------------------------------------------

DEFAULT_MAX_TURNS = 20


class TranscriptBuffer:
    """Ring buffer of completed turns with collapsed/verbose toggle."""

    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS):
        self._turns: deque[TurnTranscript] = deque(maxlen=max_turns)
        self._verbose: bool = False
        self._current_turn: TurnTranscript | None = None

    @property
    def verbose(self) -> bool:
        return self._verbose

    def toggle_verbose(self) -> bool:
        """Toggle verbose mode. Returns the new mode."""
        self._verbose = not self._verbose
        return self._verbose

    def start_turn(self, turn_id: str, user_input: str) -> None:
        """Begin a new turn."""
        self._current_turn = TurnTranscript(turn_id=turn_id, user_input=user_input)

    def add_tool(self, tool_name: str, args_preview: str = "", result_preview: str = "") -> None:
        if self._current_turn is None:
            return
        self._current_turn.tool_calls.append(
            ToolCallSummary(
                tool_name=tool_name,
                args_preview=args_preview[:200],
                result_preview=result_preview[:200],
            )
        )

    def set_assistant_content(self, content: str) -> None:
        if self._current_turn:
            self._current_turn.assistant_content = content[:500]

    def commit_turn(self) -> None:
        """Finish the current turn and add it to the buffer."""
        if self._current_turn is not None:
            self._current_turn.collapsed = not self._verbose
            self._turns.append(self._current_turn)
            self._current_turn = None

    def cancel_turn(self) -> None:
        """Discard the current turn without adding it to the buffer."""
        self._current_turn = None

    @property
    def turns(self) -> list[TurnTranscript]:
        return list(self._turns)

    def get_last(self) -> TurnTranscript | None:
        return self._turns[-1] if self._turns else None


# ---------------------------------------------------------------------------
# Rendering helpers (Rich)
# ---------------------------------------------------------------------------


def render_turn_summary(turn: TurnTranscript) -> "Text":
    """Render a one-line summary of a turn for the collapsed transcript."""
    from rich.text import Text

    t = Text()
    t.append(f"[{turn.timestamp.strftime('%H:%M')}] ", style="dim")
    t.append(turn.user_input[:60], style="bold cyan")
    if turn.has_tools:
        t.append(" · ", style="dim")
        t.append(turn.tool_summary, style="yellow")
    return t


def render_turn_verbose(turn: TurnTranscript) -> "Text":
    """Render a verbose turn with all tool calls."""
    from rich.text import Text

    t = Text()
    t.append(f"[{turn.timestamp.strftime('%H:%M')}] ", style="dim")
    t.append(turn.user_input[:60], style="bold cyan")
    t.append("\n")
    for tc in turn.tool_calls:
        t.append(f"  🛠 {tc.tool_name}", style="yellow")
        if tc.args_preview:
            t.append(f"\n    args: {tc.args_preview[:100]}", style="dim")
        if tc.result_preview:
            t.append(f"\n    → {tc.result_preview[:100]}", style="dim")
        if tc.exit_code is not None:
            style = "green" if tc.exit_code == 0 else "red"
            t.append(f" [exit {tc.exit_code}]", style=style)
        t.append("\n")
    return t
