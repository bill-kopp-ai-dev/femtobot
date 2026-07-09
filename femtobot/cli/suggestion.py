"""Prompt suggestion engine.

Camada 3 (T3.6). After each turn, generates 3-5 short follow-up
suggestions via a lightweight LLM. Suggestions are shown as ghost text
in the input area; Tab accepts, Esc discards.

MVP features:
- Static suggestions: hand-curated common follow-ups per intent
- Dynamic suggestions: optional LLM call (Haiku-class) for context-aware
- Cooldown: at most one suggestion per 3 turns (avoid spam)
- All-disabled mode: opt-out via config
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from rich.text import Text

# Static suggestions per intent (cheap, no LLM)
STATIC_SUGGESTIONS: dict[str, list[str]] = {
    "code-review": [
        "Add tests for the changes",
        "Check for security implications",
        "Suggest documentation updates",
    ],
    "implement": [
        "Write tests for the new feature",
        "Add docstrings to public APIs",
        "Update the CHANGELOG",
    ],
    "debug": [
        "Add logging at the failure point",
        "Write a regression test",
        "Search for similar issues in the codebase",
    ],
    "explain": [
        "Show me a code example",
        "What are the trade-offs?",
        "Where is this used in the codebase?",
    ],
    "default": [
        "Continue",
        "What else?",
        "Show details",
    ],
}


@dataclass
class SuggestionState:
    """Tracks the suggestion engine state."""
    last_turn_at: float = 0.0
    last_turn_suggested: int = 0
    current_turn: int = 0
    enabled: bool = True

    def should_suggest(self) -> bool:
        if not self.enabled:
            return False
        if self.current_turn - self.last_turn_suggested < 3:
            return False
        return True


@dataclass
class Suggestion:
    """A single prompt suggestion."""
    text: str
    source: str = "static"  # 'static' | 'llm' | 'history'
    confidence: float = 1.0


class SuggestionEngine:
    """Generates follow-up prompt suggestions.

    Two modes:
    - 'static': hand-curated suggestions (no LLM)
    - 'llm': calls a lightweight LLM (Haiku-class) for context-aware
    - 'hybrid': static first, then LLM if static was empty
    """

    def __init__(
        self,
        mode: str = "static",
        llm_callback: Callable[[str, str], Awaitable[str]] | None = None,
        cooldown_turns: int = 3,
    ):
        self.mode = mode  # 'static' | 'llm' | 'hybrid'
        self.llm_callback = llm_callback
        self.cooldown_turns = cooldown_turns
        self.state = SuggestionState()

    def on_turn_complete(self) -> None:
        """Update state after a turn finishes."""
        self.state.current_turn += 1
        self.state.last_turn_at = time.monotonic()

    async def suggest(
        self, intent: str = "default", last_assistant_text: str = ""
    ) -> list[Suggestion]:
        """Generate suggestions for the current turn.

        Returns 0-5 suggestions based on the mode and cooldown.
        """
        if not self.state.should_suggest():
            return []

        suggestions: list[Suggestion] = []

        if self.mode in ("static", "hybrid"):
            static = STATIC_SUGGESTIONS.get(intent, STATIC_SUGGESTIONS["default"])
            suggestions.extend(Suggestion(text=s, source="static") for s in static[:3])

        if self.mode in ("llm", "hybrid") and self.llm_callback and last_assistant_text:
            try:
                llm_suggestion = await asyncio.wait_for(
                    self.llm_callback(intent, last_assistant_text),
                    timeout=5.0,
                )
                if llm_suggestion:
                    suggestions.append(
                        Suggestion(text=llm_suggestion, source="llm", confidence=0.7)
                    )
            except (asyncio.TimeoutError, Exception):
                pass  # graceful fallback

        # Limit to 5
        suggestions = suggestions[:5]
        if suggestions:
            self.state.last_turn_suggested = self.state.current_turn
        return suggestions


def render_ghost_text(suggestion: Suggestion) -> Text:
    """Render a suggestion as ghost text (dim, italic)."""
    return Text(suggestion.text, style="dim italic")


async def default_llm_callback(intent: str, last_text: str) -> str:
    """Stub LLM callback (no actual LLM call)."""
    return ""
