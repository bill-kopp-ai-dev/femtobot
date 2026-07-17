"""Tests for ``ToolUseGuardHook`` (PR 5.3).

Covers the four cases:

- User asks to run something AND the agent answered with a plan/options
  marker → nudge is appended.
- User asks to run something AND the agent called a tool → no nudge.
- User does not ask to run anything AND the agent answers with a plan →
  no nudge (avoids false positives on conversation summaries).
- Nudge is fired at most once per iteration (no infinite-loop nudge
  storms).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from femtobot.agent.hook import AgentHookContext
from femtobot.agent.tool_use_guard import ToolUseGuardHook


def _run(coro):  # noqa: ANN001
    return asyncio.new_event_loop().run_until_complete(coro)


def _ctx(
    *,
    user_text: str,
    final_content: str | None,
    tool_calls: list | None = None,
    iteration: int = 1,
    stop_reason: str = "completed",
) -> AgentHookContext:
    return AgentHookContext(
        iteration=iteration,
        messages=[{"role": "user", "content": user_text}],
        final_content=final_content,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,
    )


def test_nudge_injected_when_user_asks_to_run_and_agent_returns_plan():
    hook = ToolUseGuardHook()
    ctx = _ctx(
        user_text="Por favor rode os 8 testes E1-E8",
        final_content=(
            "Vou começar mapeando o ambiente.\n"
            "Plano:\n1. abc\n2. def"
        ),
    )
    _run(hook.after_iteration(ctx))
    assert any(
        msg.get("role") == "system" and "Internal nudge" in msg.get("content", "")
        for msg in ctx.messages
    )


def test_no_nudge_when_tool_was_called():
    hook = ToolUseGuardHook()
    ctx = _ctx(
        user_text="rode os 8 testes",
        final_content="Vou começar mapeando o ambiente.",
        tool_calls=[SimpleNamespace(name="exec")],
    )
    _run(hook.after_iteration(ctx))
    assert not any(
        msg.get("role") == "system" and "Internal nudge" in msg.get("content", "")
        for msg in ctx.messages
    )


def test_no_nudge_when_user_did_not_ask_to_execute():
    hook = ToolUseGuardHook()
    ctx = _ctx(
        user_text="Como funciona o MCP router?",
        final_content=(
            "O MCP router funciona assim: ...\n"
            "Plano:\n1. xyz"
        ),
    )
    _run(hook.after_iteration(ctx))
    assert not any(
        msg.get("role") == "system" and "Internal nudge" in msg.get("content", "")
        for msg in ctx.messages
    )


def test_nudge_only_fires_once_per_iteration():
    hook = ToolUseGuardHook()
    ctx = _ctx(
        user_text="execute o teste",
        final_content="Vou fazer o plano:\n1. um",
    )
    _run(hook.after_iteration(ctx))
    # Second call must not re-nudge.
    _run(hook.after_iteration(ctx))
    nudge_messages = [
        msg
        for msg in ctx.messages
        if msg.get("role") == "system"
        and "Internal nudge" in msg.get("content", "")
    ]
    assert len(nudge_messages) == 1


def test_no_nudge_when_no_user_text():
    hook = ToolUseGuardHook()
    ctx = _ctx(user_text="", final_content="Vou fazer.\nPlano:\n1. um")
    _run(hook.after_iteration(ctx))
    assert not any(
        msg.get("role") == "system" and "Internal nudge" in msg.get("content", "")
        for msg in ctx.messages
    )


def test_no_nudge_when_stop_reason_not_completed():
    hook = ToolUseGuardHook()
    ctx = _ctx(
        user_text="execute o teste",
        final_content="Vou fazer.\nPlano:\n1. um",
        stop_reason="tool_use",
    )
    _run(hook.after_iteration(ctx))
    assert not any(
        msg.get("role") == "system" and "Internal nudge" in msg.get("content", "")
        for msg in ctx.messages
    )
