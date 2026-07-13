"""Tests for M3 — runtime context injection."""

from __future__ import annotations

import time

from femtobot.runtime_context import (
    RuntimeContextBlock,
    ask_pending_block,
    build_runtime_context_blocks,
    goal_active_block,
    goal_blocked_block,
    render_runtime_context,
)
from femtobot.session.goal_state import GOAL_STATE_KEY
from femtobot.session.pending_asks import (
    AskStatus,
    AskTarget,
    PendingAsk,
    append_pending_ask,
)


def test_goal_active_block_returns_none_when_no_goal():
    assert goal_active_block({}) is None
    assert goal_active_block(None) is None
    md = {GOAL_STATE_KEY: {"status": "completed"}}
    assert goal_active_block(md) is None


def test_goal_active_block_includes_id_and_started_at():
    md = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Ship v1.0",
            "ui_summary": "Shipping",
        },
        "goal_started_at": time.time(),
        "goal_id": "goal_abcdef1234567890",
    }
    block = goal_active_block(md)
    assert block is not None
    assert block.source == "goal"
    text = block.to_text()
    assert "Goal (active)" in text
    assert "Ship v1.0" in text
    assert "goal_abcdef1234567890" in text
    assert "Shipping" in text


def test_ask_pending_block_lists_pending_asks():
    md: dict = {}
    append_pending_ask(
        md,
        PendingAsk(
            correlation_id="ask_pending123",
            target=AskTarget.ORCHESTRATOR,
            question="Pick A or B?",
            options=["A", "B"],
        ),
    )
    append_pending_ask(
        md,
        PendingAsk(
            correlation_id="ask_already999",
            target=AskTarget.ORCHESTRATOR,
            question="done",
            status=AskStatus.ANSWERED,
            response="B",
        ),
    )
    block = ask_pending_block(md)
    assert block is not None
    text = block.to_text()
    assert "ask_pending123" in text
    assert "Pick A or B?" in text
    assert "ask_already999" not in text


def test_ask_pending_block_returns_none_when_empty():
    assert ask_pending_block({}) is None
    md: dict = {}
    append_pending_ask(
        md,
        PendingAsk(
            correlation_id="ask_done000000",
            target=AskTarget.ORCHESTRATOR,
            question="x",
            status=AskStatus.ANSWERED,
        ),
    )
    assert ask_pending_block(md) is None


def test_goal_blocked_block_emitted_only_when_waiting():
    md_no_wait = {GOAL_STATE_KEY: {"status": "active", "objective": "x"}}
    assert goal_blocked_block(md_no_wait) is None
    md_wait = {
        GOAL_STATE_KEY: {"status": "active", "objective": "x"},
        "goal_waiting_on": "ask_orchestrator",
        "goal_block_reason": "needs decision",
    }
    block = goal_blocked_block(md_wait)
    assert block is not None
    text = block.to_text()
    assert "blocked" in text.lower()
    assert "needs decision" in text


def test_build_runtime_context_blocks_returns_active_ask_blocked_in_order():
    md: dict = {
        GOAL_STATE_KEY: {"status": "active", "objective": "Ship v1"},
        "goal_started_at": time.time(),
        "goal_waiting_on": "ask_orchestrator",
        "goal_block_reason": "needs decision",
    }
    append_pending_ask(
        md,
        PendingAsk(
            correlation_id="ask_correl1234",
            target=AskTarget.ORCHESTRATOR,
            question="Approve?",
        ),
    )
    blocks = build_runtime_context_blocks(md)
    sources = [b.source for b in blocks]
    assert sources == ["goal", "goal_blocked", "ask_pending"]


def test_render_runtime_context_concatenates_all_blocks():
    md: dict = {
        GOAL_STATE_KEY: {"status": "active", "objective": "ship"},
        "goal_waiting_on": "ask_orchestrator",
    }
    append_pending_ask(
        md,
        PendingAsk(
            correlation_id="ask_q12345678",
            target=AskTarget.ORCHESTRATOR,
            question="Approve?",
        ),
    )
    text = render_runtime_context(md)
    assert "[runtime:goal]" in text
    assert "[runtime:goal_blocked]" in text
    assert "[runtime:ask_pending]" in text


def test_runtime_context_block_to_text_with_no_lines():
    block = RuntimeContextBlock(source="noop", lines=())
    text = block.to_text()
    assert text == "[runtime:noop]\n"