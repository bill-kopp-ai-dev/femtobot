"""Tests for the 3-tier slash completer."""

from __future__ import annotations

import pytest

from femtobot.cli.completer import (
    CommandHit,
    SlashCompleter,
    rank_commands,
)
from femtobot.command.builtin import BUILTIN_COMMAND_SPECS


def test_empty_text_returns_no_hits() -> None:
    assert rank_commands("", BUILTIN_COMMAND_SPECS) == []


def test_text_without_slash_returns_no_hits() -> None:
    assert rank_commands("hello", BUILTIN_COMMAND_SPECS) == []


def test_slash_alone_returns_all_within_max() -> None:
    hits = rank_commands("/", BUILTIN_COMMAND_SPECS, max_results=100)
    assert len(hits) == len(BUILTIN_COMMAND_SPECS)
    # All at tier 2 or 3 (no exact since body is empty)
    assert all(h.tier in (2, 3) for h in hits)


def test_exact_match_wins_over_fuzzy() -> None:
    """A typo that happens to substring-match must NOT beat an exact hit."""
    # '/clear' is not a real command, but '/status' is. We use a real example:
    # '/status' must be tier 1.
    hits = rank_commands("/status", BUILTIN_COMMAND_SPECS)
    assert hits
    assert hits[0].command == "/status"
    assert hits[0].tier == 1


def test_prefix_wins_over_substring() -> None:
    """``/mode`` is a prefix of ``/model`` so it must come first."""
    hits = rank_commands("/mode", BUILTIN_COMMAND_SPECS)
    assert hits[0].command == "/model"
    assert hits[0].tier == 2


def test_max_results_caps_output() -> None:
    hits = rank_commands("/h", BUILTIN_COMMAND_SPECS, max_results=2)
    assert len(hits) <= 2


def test_case_insensitive() -> None:
    hits = rank_commands("/STATUS", BUILTIN_COMMAND_SPECS)
    assert hits[0].command.lower() == "/status"


def test_substring_tier_is_used_last() -> None:
    """A needle that is a substring of a longer command lands at tier 3."""
    # `/dream` body 'dream' is a prefix of `/dream-log` and `/dream-restore`,
    # so `/dre` must be tier 2 (prefix). For tier 3 we need a needle that
    # is a substring (not prefix) — e.g. `eam` lives inside `dream` and
    # `dream-log` but is not a prefix of any body.
    hits = rank_commands("/eam", BUILTIN_COMMAND_SPECS)
    assert hits
    assert all(h.tier == 3 for h in hits)
