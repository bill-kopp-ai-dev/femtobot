"""Tests for the transcript module (Camada 2, T2.3)."""

from __future__ import annotations

from femtobot.cli.transcript import (
    ToolCallSummary,
    TranscriptBuffer,
    TurnTranscript,
    render_turn_summary,
)


def test_turn_tool_summary_single_tool() -> None:
    t = TurnTranscript(turn_id="t1", user_input="hello", tool_calls=[
        ToolCallSummary(tool_name="read_file"),
        ToolCallSummary(tool_name="read_file"),
        ToolCallSummary(tool_name="read_file"),
    ])
    assert t.tool_summary == "3× read_file"


def test_turn_tool_summary_multiple_tools() -> None:
    t = TurnTranscript(turn_id="t1", user_input="hello", tool_calls=[
        ToolCallSummary(tool_name="read_file"),
        ToolCallSummary(tool_name="exec"),
    ])
    assert "read_file" in t.tool_summary
    assert "exec" in t.tool_summary


def test_transcript_buffer_commit() -> None:
    buf = TranscriptBuffer()
    buf.start_turn("t1", "hello world")
    buf.commit_turn()
    assert len(buf.turns) == 1
    assert buf.turns[0].user_input == "hello world"


def test_transcript_buffer_verbose_toggle() -> None:
    buf = TranscriptBuffer()
    assert buf.verbose is False
    buf.toggle_verbose()
    assert buf.verbose is True
    buf.toggle_verbose()
    assert buf.verbose is False


def test_transcript_buffer_cancel() -> None:
    buf = TranscriptBuffer()
    buf.start_turn("t1", "hello")
    buf.cancel_turn()
    assert len(buf.turns) == 0


def test_transcript_buffer_max_turns() -> None:
    buf = TranscriptBuffer(max_turns=3)
    for i in range(10):
        buf.start_turn(f"t{i}", f"msg {i}")
        buf.commit_turn()
    assert len(buf.turns) == 3
    # Oldest entries evicted
    assert buf.turns[0].turn_id == "t7"


def test_render_turn_summary() -> None:
    t = TurnTranscript(turn_id="t1", user_input="hello world", tool_calls=[
        ToolCallSummary(tool_name="read_file"),
        ToolCallSummary(tool_name="read_file"),
    ])
    rendered = render_turn_summary(t)
    assert "hello world" in rendered.plain
    assert "read_file" in rendered.plain
