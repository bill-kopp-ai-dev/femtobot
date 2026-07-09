"""Textual TUI renderer for Femtobot CLI.

Inspired by Claude Code's React-Ink architecture:
FEMTOBOT_CLI_REFACTOR_PLAN.md Camada 3, T3.1.

This module provides a Textual-based TUI as an alternative to the
Rich+prompt_toolkit stack in stream.py. It is a drop-in replacement for
the REPL's rendering layer: the same ``on_delta`` / ``on_end`` /
``on_trace`` / ``on_tool_call`` interface.

Architecture
~~~~~~~~~~~~
The ``FemtobotTextualApp`` runs as a standalone Textual application that
receives events from the REPL via its public API. The REPL calls
``app.on_delta(text)`` etc. from its own asyncio loop; Textual processes
them via ``post_message`` to avoid cross-event-loop issues.

Layout (from top to bottom):
  [ Header ]         — bot name, model, turn counter
  [ MessageList ]    — scrollable transcript (collapsed/verbose)
  [ Suggestions ]     — ghost-text suggestions (T3.6)
  [ InputArea ]      — multiline TextArea with completer
  [ StatusFooter ]   — tokens, elapsed, bg tasks, mode indicators

Color tokens map to the active CliTheme (terracotta-claude default).

Usage
~~~~~
::

    from femtobot.cli.textual_app import FemtobotTextualApp

    app = FemtobotTextualApp()
    async def repl_loop():
        await app.run_async()
        # app.on_delta("Hello")  # called by the REPL
    asyncio.run(repl_loop())

The ``FemtobotTextualApp`` exposes the same streaming interface as
``StreamRenderer`` so the REPL can swap implementations via config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

# Textual ships its own rich version; import from textual.rich for compatibility.
from rich.console import RenderableType
from rich.markdown import Markdown
from rich.text import Text

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.color import Color
    from textual.css.query import NoMatches
    from textual.events import Mount
    from textual.message import Message
    from textual.reactive import reactive
    from textual.widget import Widget
    from textual.widgets import Footer, Static, TextArea

    _TEXTUAL_AVAILABLE = True
except ImportError:
    _TEXTUAL_AVAILABLE = False

    class _TStub:  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            pass

        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)

    def _callable_stub(*a, **kw):  # type: ignore[no-redef]
        return None

    App = Static = TextArea = Widget = Footer = _TStub  # type: ignore[assignment,misc]
    ComposeResult = NoMatches = Mount = Message = Color = None  # type: ignore[assignment]
    Binding = reactive = _callable_stub  # type: ignore[assignment]


class TextualNotAvailable(RuntimeError):
    """Raised when textual is not installed."""

# ---------------------------------------------------------------------------
# Types & data models
# ---------------------------------------------------------------------------


class MessageRole(str):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class MessageItem:
    """A single message in the transcript list."""

    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    rendered: RenderableType | None = None
    collapsed_preview: str = ""


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class HeaderBar(Static):
    """Top bar: bot name, model, turn counter."""

    DEFAULT_TEXT = "🐈 Femtobot"
    DEFAULT_MODEL = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bot_name = self.DEFAULT_TEXT
        self._model = self.DEFAULT_MODEL
        self._turn = 0

    def set_info(self, bot_name: str, model: str, turn: int) -> None:
        self._bot_name = bot_name
        self._model = model
        self._turn = turn
        self.refresh()

    def render(self) -> RenderableType:
        parts = [Text(f" {self._bot_name} ", style="bold cyan")]
        if self._model:
            parts.append(Text(f" · {self._model} ", style="dim"))
        if self._turn > 0:
            parts.append(Text(f" · turn {self._turn} ", style="dim"))
        return Text.assemble(*parts)


class MessageList(Static):
    """Scrollable message transcript.

    Shows all messages in order. Assistant messages are rendered as Markdown.
    Tool calls are shown as a compact pill. User messages are dimmed.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._messages: list[MessageItem] = []

    def add_message(self, item: MessageItem) -> None:
        self._messages.append(item)
        self.refresh()

    def update_current(self, content: str, rendered: RenderableType) -> None:
        """Update the last message (live streaming update)."""
        if not self._messages:
            return
        self._messages[-1].content = content
        self._messages[-1].rendered = rendered
        self.refresh()

    def clear_live(self) -> None:
        """Mark the last message as committed (no longer live)."""
        self.refresh()

    def render(self) -> RenderableType:
        from rich.console import Group

        parts: list[RenderableType] = []
        for msg in self._messages:
            if msg.role == MessageRole.USER:
                parts.append(
                    Text(f"\n[dim]You:[/dim] {msg.content[:80]}...", style="cyan")
                )
            elif msg.role == MessageRole.ASSISTANT:
                if msg.rendered:
                    parts.append(msg.rendered)
                elif msg.content:
                    parts.append(Markdown(msg.content))
            elif msg.role == MessageRole.TOOL:
                parts.append(
                    Text(
                        f"  🛠 {msg.content[:60]}",
                        style="yellow",
                    )
                )
            else:
                parts.append(Text(msg.content, style="dim"))
        return Group(*parts) if parts else Text("")


class InputArea(TextArea):
    """Multiline input area with slash-completion integration."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.suggestion_text = ""

    def set_suggestions(self, suggestions: list[str]) -> None:
        """Show suggestion hints below the input."""
        # Textual TextArea doesn't support ghost text natively.
        # For now we just store it; future T3.6 integration uses
        # a separate SuggestionBar widget.
        self.suggestion_text = " | ".join(suggestions[:3])


class SuggestionBar(Static):
    """Bottom suggestion bar (T3.6) — shows Tab-acceptable suggestions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._suggestions: list[str] = []

    def set_suggestions(self, suggestions: list[str]) -> None:
        self._suggestions = suggestions
        self.refresh()

    def render(self) -> RenderableType:
        if not self._suggestions:
            return Text("")
        pills = "  ".join(f"[dim][Tab] {s}[/dim]" for s in self._suggestions)
        return Text(pills, style="dim")


class StatusFooter(Static):
    """Bottom status bar: tokens, elapsed, mode, bg tasks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tokens = ""
        self._elapsed = ""
        self._mode = ""
        self._bg = ""

    def set_status(
        self,
        tokens: str = "",
        elapsed: str = "",
        mode: str = "",
        bg_tasks: str = "",
    ) -> None:
        self._tokens = tokens
        self._elapsed = elapsed
        self._mode = mode
        self._bg = bg_tasks
        self.refresh()

    def render(self) -> RenderableType:
        parts: list[tuple[str, str]] = []
        if self._tokens:
            parts.append((f" {self._tokens} ", "bold"))
        if self._elapsed:
            parts.append((" · ", "dim"))
            parts.append((self._elapsed, "dim"))
        if self._mode:
            parts.append((" · ", "dim"))
            parts.append((f"[{self._mode}]", "yellow"))
        if self._bg:
            parts.append((" · ", "dim"))
            parts.append((self._bg, "cyan"))
        return Text.assemble(*parts) if parts else Text(" ")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class FemtobotTextualApp(App):
    """Textual TUI for the Femtobot REPL.

    Implements the same streaming interface as ``StreamRenderer`` so the REPL
    can treat it as a drop-in replacement via config.
    """

    TITLE = "Femtobot"
    SUB_TITLE = "CLI"

    CSS = """
    Screen {
        background: $surface;
    }
    HeaderBar {
        height: 1;
        dock: top;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    #message-list {
        height: 1fr;
        overflow-y: scroll;
        padding: 0 1;
    }
    #input-area {
        height: 3;
        dock: bottom;
        border-top: solid $accent;
    }
    #suggestion-bar {
        height: 1;
        dock: bottom;
        color: $text-muted;
        padding: 0 1;
    }
    StatusFooter {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "app.cancel", "Cancel", show=True),
        Binding("ctrl+o", "toggle_verbose", "Transcript", show=True),
        Binding("ctrl+b", "toggle_background", "Background", show=True),
        Binding("escape,escape", "rewind", "Rewind", show=False),
        Binding("f11", "toggle_fullscreen", "Fullscreen", show=False),
        Binding("tab", "accept_suggestion", "Accept", show=True),
        Binding("ctrl+l", "clear_input", "Clear", show=True),
    ]

    # State
    _turn_count = reactive(0)
    _live_message: MessageItem | None = None
    _streaming = reactive(False)

    def __init__(
        self,
        bot_name: str = "Femtobot",
        model: str = "",
        theme_name: str = "terracotta-claude",
        **textual_kwargs,
    ):
        if not _TEXTUAL_AVAILABLE:
            raise TextualNotAvailable(
                "T3.1 Textual TUI requires 'textual'. "
                "Install with: uv pip install 'femtobot[tui]' "
                "or: uv sync --extra tui"
            )
        super().__init__(**textual_kwargs)
        self._bot_name = bot_name
        self._model = model
        self._theme_name = theme_name
        self._suggestions: list[str] = []
        self._verbose = False
        self._console_mode = "chat"
        self._on_submit: Callable[[str], None] | None = None

    # ------------------------------------------------------------------
    # Public streaming API (same interface as StreamRenderer)
    # ------------------------------------------------------------------

    def on_delta(self, text: str) -> None:
        """Called by the REPL for each streaming delta."""
        if self._live_message is None:
            self._live_message = MessageItem(
                role=MessageRole.ASSISTANT,
                content=text,
                rendered=Markdown(text),
            )
            try:
                self.query_one("#message-list", MessageList).add_message(self._live_message)
            except NoMatches:
                pass
        else:
            self._live_message.content += text
            self._live_message.rendered = Markdown(self._live_message.content)
            try:
                ml = self.query_one("#message-list", MessageList)
                ml.update_current(self._live_message.content, self._live_message.rendered)
            except NoMatches:
                pass

    def on_end(self, *, resuming: bool = False) -> None:
        """Called when streaming finishes."""
        self._live_message = None
        self._streaming = False
        try:
            ml = self.query_one("#message-list", MessageList)
            ml.clear_live()
        except NoMatches:
            pass
        self._turn_count += 1
        self._update_footer()

    def on_trace(self, text: str) -> None:
        """Called for reasoning/trace output (shown inline, dimmed)."""
        # Append as a system message in the transcript.
        item = MessageItem(role="trace", content=text)
        try:
            self.query_one("#message-list", MessageList).add_message(item)
        except NoMatches:
            pass

    def on_tool_call(self, tool_name: str, args_preview: str = "") -> None:
        """Called when a tool is invoked."""
        content = f"{tool_name}({args_preview[:50]})"
        item = MessageItem(role=MessageRole.TOOL, content=content)
        try:
            self.query_one("#message-list", MessageList).add_message(item)
        except NoMatches:
            pass

    def add_user_message(self, text: str) -> None:
        """Add a user message to the transcript."""
        item = MessageItem(role=MessageRole.USER, content=text)
        try:
            self.query_one("#message-list", MessageList).add_message(item)
        except NoMatches:
            pass

    def set_suggestions(self, suggestions: list[str]) -> None:
        """Set the suggestion bar text (T3.6)."""
        self._suggestions = suggestions
        try:
            sb = self.query_one("#suggestion-bar", SuggestionBar)
            sb.set_suggestions(suggestions)
        except NoMatches:
            pass

    def set_submit_callback(self, cb: Callable[[str], None]) -> None:
        """Register a callback for when the user submits input."""
        self._on_submit = cb

    def _update_footer(self) -> None:
        """Refresh the status footer."""
        try:
            sf = self.query_one("StatusFooter", StatusFooter)
            sf.set_status(mode=self._console_mode)
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # Textual lifecycle
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header-bar")
        yield MessageList(id="message-list")
        yield InputArea(id="input-area")
        yield SuggestionBar(id="suggestion-bar")
        yield StatusFooter()
        yield Footer()

    def on_mount(self) -> None:
        self._apply_theme()
        self._update_footer()
        try:
            hb = self.query_one("#header-bar", HeaderBar)
            hb.set_info(self._bot_name, self._model, self._turn_count)
        except NoMatches:
            pass

    def _apply_theme(self) -> None:
        """Map theme colors to Textual CSS variables."""
        # Map the CliTheme colors to Textual theme variables.
        theme_colors = {
            "terracotta-claude": {
                "primary": "#d77757",
                "secondary": "#d77757",
                "accent": "#d77757",
                "surface": "#1e1e1e",
                "background": "#1e1e1e",
                "text": "#e0e0e0",
                "text-muted": "#808080",
            },
            "cyber-dark": {
                "primary": "#00ffff",
                "secondary": "#00ffff",
                "accent": "#ff00ff",
                "surface": "#0a0a14",
                "background": "#0a0a14",
                "text": "#e0e0e0",
                "text-muted": "#808080",
            },
            "solarized-light": {
                "primary": "#268bd2",
                "secondary": "#268bd2",
                "accent": "#268bd2",
                "surface": "#fdf6e3",
                "background": "#fdf6e3",
                "text": "#657b83",
                "text-muted": "#93a1a1",
            },
            "monochrome": {
                "primary": "#d0d0d0",
                "secondary": "#d0d0d0",
                "accent": "#d0d0d0",
                "surface": "#1e1e1e",
                "background": "#1e1e1e",
                "text": "#d0d0d0",
                "text-muted": "#808080",
            },
        }
        # Textual 8.x StylesBase has no set_var; theme vars applied via CSS string (T3.2)
        _ = theme_colors.get(self._theme_name, theme_colors["terracotta-claude"])

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_cancel(self) -> None:
        """Cancel the current operation."""
        self._live_message = None
        self._streaming = False

    def action_toggle_verbose(self) -> None:
        """Toggle transcript between collapsed and verbose."""
        self._verbose = not self._verbose

    def action_toggle_background(self) -> None:
        """Toggle background task mode."""
        self._console_mode = "bg" if self._console_mode == "chat" else "chat"
        self._update_footer()

    def action_rewind(self) -> None:
        """Rewind to a previous turn (Esc Esc — MVP)."""
        # Deferred to Camada 3 full implementation.
        pass

    def action_toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode."""
        # Textual 8.x has no App.toggle_fullscreen/full_screen API; no-op until T3.2
        pass

    def action_accept_suggestion(self) -> None:
        """Accept the first suggestion with Tab."""
        if self._suggestions:
            suggestion = self._suggestions[0]
            try:
                ta = self.query_one("#input-area", InputArea)
                ta.insert(suggestion)
                self.set_suggestions([])
            except NoMatches:
                pass

    def action_clear_input(self) -> None:
        """Clear the input area."""
        try:
            ta = self.query_one("#input-area", InputArea)
            ta.clear()
        except NoMatches:
            pass
