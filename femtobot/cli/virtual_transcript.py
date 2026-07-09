"""Virtual scrolling transcript for the Femtobot CLI.

Inspired by Claude Code <Static> component and FEMTOBOT_CLI_REFACTOR_PLAN.md
Camada 3, T3.2.

Concept
~~~~~~~
Instead of re-rendering all N messages on every render cycle, we keep a
ring buffer of the last MAX_VISIBLE messages. Older messages are
"committed" to the terminal (printed once) and removed from the live
render tree. Only the committed lines + the current live message are
kept in memory.

This gives O(1) render time regardless of conversation length, matching
the <Static> behaviour of Ink/Claude Code.

Classes
~~~~~~~
:class:`VirtualTranscript` — ring buffer of RenderableType items
:class:`TranscriptRenderer` — produces the renderable for the current view

The existing Camada 2 TranscriptBuffer is extended with a "commit"
operation: when a turn is fully rendered, its renderables are
"committed" (frozen) and the ring buffer slides forward.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console, RenderableType


DEFAULT_MAX_VISIBLE = 20
DEFAULT_MAX_COMMITTED_LINES = 200


class VirtualTranscript:
    """Ring buffer of rendered message lines.

    Committed lines are frozen (printed to terminal, removed from live
    tree). Only the last MAX_VISIBLE uncommitted lines are kept in
    memory for live re-rendering.
    """

    def __init__(
        self,
        max_visible: int = DEFAULT_MAX_VISIBLE,
        max_committed_lines: int = DEFAULT_MAX_COMMITTED_LINES,
    ):
        # Committed lines: a fixed-size deque that holds the last
        # MAX_COMMITTED_LINES lines as plain strings.
        self._committed: deque[str] = deque(maxlen=max_committed_lines)
        # Live buffer: renderables not yet committed.
        self._live: deque[RenderableType] = deque(maxlen=max_visible)
        self._max_visible = max_visible

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def append_live(self, renderable: "RenderableType") -> None:
        """Add a renderable to the live (not-yet-committed) buffer."""
        self._live.append(renderable)

    def clear_live(self) -> None:
        """Clear all live renderables (used on rewind or reset)."""
        self._live.clear()

    def commit(self) -> None:
        """Move all live renderables to the committed buffer.

        Called when a turn is fully rendered and we want to freeze it
        in the terminal. The live buffer is drained into committed lines.
        """
        self._live.clear()

    def commit_line(self, text: str) -> None:
        """Commit a single line of plain text (no Rich renderable)."""
        self._committed.append(text)

    def reset(self) -> None:
        """Clear both committed and live buffers."""
        self._committed.clear()
        self._live.clear()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def live_count(self) -> int:
        return len(self._live)

    @property
    def committed_count(self) -> int:
        return len(self._committed)

    def get_live(self) -> list["RenderableType"]:
        """All live renderables in order (oldest first)."""
        return list(self._live)

    def get_committed(self) -> list[str]:
        """All committed lines in order (oldest first)."""
        return list(self._committed)


class TranscriptRenderer:
    """Renders the virtual transcript to a Rich console.

    Usage:
        renderer = TranscriptRenderer(console)
        renderer.append_live(markdown_renderable)
        # ... later, when turn is done:
        renderer.commit()

    The :meth:`render` method produces the complete renderable for the
    current view (committed + live), suitable for use in a Live display
    or as part of a Textual widget.
    """

    def __init__(
        self,
        console: "Console",
        max_visible: int = DEFAULT_MAX_VISIBLE,
    ):
        self._console = console
        self._vt = VirtualTranscript(max_visible=max_visible)

    @property
    def transcript(self) -> VirtualTranscript:
        return self._vt

    def append_live(self, renderable: "RenderableType") -> None:
        self._vt.append_live(renderable)

    def commit(self) -> None:
        self._vt.commit()

    def render(self) -> "RenderableType":
        """Build a combined renderable of committed + live items.

        Committed items are printed once and returned as plain text.
        Live items are kept as Rich renderables for live updates.
        """
        from rich.console import Group
        from rich.text import Text

        parts: list["RenderableType"] = []

        # Committed lines: already in terminal, represented as dim text.
        if self._vt.committed_count > 0:
            committed_text = "\n".join(self._vt.get_committed())
            parts.append(Text(committed_text, style="dim"))

        # Live items: rendered as-is.
        for item in self._vt.get_live():
            parts.append(item)

        return Group(*parts) if parts else Text("")

    def get_visible_count(self) -> int:
        """Number of items in the live buffer."""
        return self._vt.live_count
