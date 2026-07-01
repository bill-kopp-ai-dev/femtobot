"""3-tier slash-command completer for prompt_toolkit.

Camada 1 (1.2) do ``FEMTOBOT_CLI_REFACTOR_PLAN.md``.

Ranking order (matters — see anthropics/claude-code #20537):
  1. EXACT match — text == command
  2. PREFIX match — text is a prefix of command
  3. SUBSTRING match — text appears anywhere in command

When any match is found at tier 1, tiers 2 and 3 are skipped entirely.
This is the safe default: an exact user input must always win, never a
fuzzy or substring guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from prompt_toolkit.completion import Completer, Completion

from femtobot.command.builtin import BUILTIN_COMMAND_SPECS


@dataclass(frozen=True)
class CommandHit:
    """A single command match produced by :func:`rank_commands`."""

    command: str
    icon: str
    description: str
    tier: int  # 1 = exact, 2 = prefix, 3 = substring


def rank_commands(
    text: str,
    specs: Sequence,
    max_results: int = 10,
) -> list[CommandHit]:
    """Return up to ``max_results`` commands matching ``text``.

    ``text`` should start with ``/`` and is matched case-insensitively.
    Returns at most one match per command name, ordered by tier.
    """
    if not text or not text.startswith("/"):
        return []
    needle = text.lower()
    needle_body = needle[1:]

    exact, prefix, substring = [], [], []
    for spec in specs:
        cmd = spec.command.lower()
        body = cmd[1:]
        if body == needle_body:
            exact.append(spec)
        elif body.startswith(needle_body):
            prefix.append(spec)
        elif needle_body and needle_body in body:
            substring.append(spec)

    hits: list[CommandHit] = []
    for spec in exact:
        hits.append(CommandHit(spec.command, spec.icon, spec.description, tier=1))
        if len(hits) >= max_results:
            return hits
    for spec in prefix:
        hits.append(CommandHit(spec.command, spec.icon, spec.description, tier=2))
        if len(hits) >= max_results:
            return hits
    for spec in substring:
        hits.append(CommandHit(spec.command, spec.icon, spec.description, tier=3))
        if len(hits) >= max_results:
            return hits
    return hits


class SlashCompleter(Completer):
    """prompt_toolkit completer for slash commands."""

    def __init__(self, specs=None, max_results: int = 10):
        self._specs = specs or BUILTIN_COMMAND_SPECS
        self._max_results = max_results

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        hits = rank_commands(text, self._specs, max_results=self._max_results)
        for hit in hits:
            yield Completion(
                hit.command,
                start_position=-len(text),
                display=hit.command,
                display_meta=f"{hit.icon} {hit.description}" if hit.icon else hit.description,
            )
