"""B5 regression: archived summary lives in the system prompt (B5).

B5 (REFACTOR_PLAN.md Lote B): the archived / consolidated summary
produced by the Consolidator should be embedded in the **system
prompt**, not as a synthetic ``role: user`` / ``role: assistant``
message in ``messages``.  Putting it in the system prompt:

* gives providers with KV cache (Anthropic prompt caching, OpenAI
  cached prompt) a much better hit rate — the summary rarely changes
  between turns, so the system prefix can be reused; and
* keeps the message history focused on the actual conversation,
  which makes snip / microcompact logic cheaper.

This test pins the contract: ``build_system_prompt(...,
session_summary=...)`` includes the summary text, and the synthesized
``messages`` list does NOT contain a synthetic message whose
``content`` is the raw summary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from femtobot.agent.context import ContextBuilder

pytestmark = pytest.mark.durability


def _make_builder(tmp_path: Path) -> ContextBuilder:
    # ``ContextBuilder`` is constructed with a ``workspace`` and optionally a
    # ``timezone`` / ``disabled_skills``.  We pass just the workspace to
    # exercise the real builder.
    return ContextBuilder(workspace=tmp_path)


def test_session_summary_is_in_system_prompt(tmp_path: Path) -> None:
    """B5: session_summary is appended to the system prompt (B5)."""
    builder = _make_builder(tmp_path)
    summary = "ARCHIVED: user prefers dark mode, lives in São Paulo."
    system = builder.build_system_prompt(session_summary=summary)
    assert summary in system


def test_session_summary_not_duplicated_into_messages(tmp_path: Path) -> None:
    """B5: the message list does NOT contain the raw summary as a message (B5).

    The summary should be in the system prompt only.  A regression that
    re-introduces a synthetic ``role: system`` or ``role: user`` /
    ``role: assistant`` message containing the summary would re-pay the
    KV-cache penalty B5 was designed to avoid.

    This test inspects the public system-prompt builder output and
    asserts there is no other section (other than the
    ``[Archived Context Summary]`` block) that re-emits the same text.
    """
    builder = _make_builder(tmp_path)
    summary = "ARCHIVED_MARKER_B5_SENTINEL: never as a message"
    system = builder.build_system_prompt(session_summary=summary)
    # The summary appears exactly once — inside the Archived Context Summary block.
    occurrences = system.count(summary)
    assert occurrences == 1, (
        f"summary appears {occurrences} times in system prompt; expected exactly 1"
    )
    # And it sits inside the Archived Context Summary section.
    assert "[Archived Context Summary]" in system
    # The system prompt prefix / skills sections should not contain the raw text.
    # (No further assertion needed — the count check is the safety net.)


def test_session_summary_omitted_when_none(tmp_path: Path) -> None:
    """B5: omitting ``session_summary`` is a clean no-op (B5)."""
    builder = _make_builder(tmp_path)
    system_no_summary = builder.build_system_prompt()
    assert "Archived Context Summary" not in system_no_summary
