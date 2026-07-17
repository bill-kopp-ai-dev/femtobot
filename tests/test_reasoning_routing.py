"""Tests for PR 4.1 — reasoning routing in the OpenAI-compat provider.

Some openai-compat providers (notably MiniMax-M3) collapse the reasoning
text into ``delta.content`` instead of returning it under
``reasoning_content``. PR 4.1 adds a heuristic in ``_parse_chunks`` that
moves a reasoning-looking prefix from ``content`` to ``reasoning_content``
when no separate reasoning field is present, so the CLI never renders
the thinking text as part of the assistant message.
"""

from __future__ import annotations

import json

from femtobot.providers.openai_compat_provider import (
    OpenAICompatProvider,
    _looks_like_reasoning_start,
)


def _chunk(payload: dict) -> dict:
    return json.loads(json.dumps(payload))


def test_looks_like_reasoning_start_matches():
    assert _looks_like_reasoning_start("Let me think about this.")
    assert _looks_like_reasoning_start("The user wants me to test E1-E8.")
    assert _looks_like_reasoning_start("First, I need to read the AGENTS.md")
    assert _looks_like_reasoning_start("Reasoning: the env is X.")


def test_looks_like_reasoning_start_does_not_match_normal_content():
    assert not _looks_like_reasoning_start("Hello world")
    assert not _looks_like_reasoning_start("The answer is 42.")
    assert not _looks_like_reasoning_start("")
    # Over 4096 chars is past the reasoning phase.
    assert not _looks_like_reasoning_start("Let me " + ("x" * 5000))


def test_parse_chunks_routes_reasoning_when_no_reasoning_field():
    """When ``reasoning_content`` is absent and ``content`` starts with a
    reasoning-looking prefix, the prefix is moved to ``reasoning_content``."""
    chunks = [
        _chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "Let me check the AGENTS.md first."
                        }
                    }
                ]
            }
        ),
        _chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "content": " Tools available: exec, read_file."
                        }
                    }
                ]
            }
        ),
    ]
    response = OpenAICompatProvider._parse_chunks(chunks)
    assert response.reasoning_content is not None
    assert "Let me check" in response.reasoning_content
    assert response.content is not None
    assert "Tools available" in response.content
    assert "Let me check" not in response.content


def test_parse_chunks_keeps_existing_reasoning_content():
    """When ``reasoning_content`` is present, the heuristic MUST NOT
    move content (which would corrupt the response)."""
    chunks = [
        _chunk(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "Let me check the AGENTS.md first.",
                            "reasoning_content": "internal note",
                        }
                    }
                ]
            }
        ),
    ]
    response = OpenAICompatProvider._parse_chunks(chunks)
    assert response.reasoning_content == "internal note"
    assert "Let me check" in (response.content or "")


def test_parse_chunks_no_change_for_normal_content():
    """Non-reasoning-looking content is left alone."""
    chunks = [
        _chunk({"choices": [{"delta": {"content": "Hello world."}}]}),
    ]
    response = OpenAICompatProvider._parse_chunks(chunks)
    assert response.content == "Hello world."
    assert response.reasoning_content is None
