"""Reproduce the user-reported scenario exactly.

The user reported that the agent says things like "Tenho contexto
suficiente. Despachando agora em paralelo — agy primeiro (cheap) +
claude-sonnet (precisão)…" but never actually emits the tool calls.

This test exercises the exact text patterns the user saw in production
logs to make sure the intent_only guard catches them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from femtobot.agent.hook import AgentHook
from femtobot.agent.runner import AgentRunner, AgentRunSpec
from femtobot.utils.runtime import is_intent_only_response

# Exact transcripts from the user's logs.
REPORTED_LINES = [
    "Tenho contexto suficiente. Vou despachar as duas análises independentes em paralelo agora.",
    "Tenho contexto suficiente. Despachando agora em paralelo — agy primeiro (cheap) + claude-sonnet (precisão).",
    "Pensei em despachar, mas não chegou a sair: ainda preciso escrever os payloads antes de cada agy_run_task/claude_start_task.",
    "Sim, despachando agora as duas em paralelo. Tarefas independentes, então não há ordem obrigatória.",
    "Combinado. Quando os dois engines (agy + claude-sonnet) terminarem as análises da E0, eu trago o resultado consolidado.",
    "Ainda não. Eu disse que ia despachar mas acabei só falando — ainda não disparei nenhuma chamada MCP.",
    "Vou fazer a Femto review agora — ler os 2 arquivos críticos com lupa, reproduzir o deadlock se possível, e cruzar com o claude review.",
    "Você está certo — outra vez. Emitindo as chamadas de verdade.",
    "Emitindo agora as chamadas de verdade.",
    "Vou emitir as leituras, reproduzir o deadlock ao vivo, e gerar o relatório consolidado.",
    # NOTE: "O loop só termina com o relatório escrito" is intentionally
    # excluded — it describes a condition/policy statement ("the loop
    # *terminates* with the report"), not an action the agent is about
    # to take.  Detecting it would risk false positives on legitimate
    # descriptions of loop semantics.
]


class TestReportedLinesCaught:
    """All reported production lines must be flagged as intent_only."""

    def test_all_reported_lines_flag_intent_only(self) -> None:
        """Every user-reported line must trip the heuristic.

        If any line is NOT detected, the fix L1 misses a real production
        pattern — that's a regression we want loud failures for.
        """
        undetected = [
            line for line in REPORTED_LINES
            if not is_intent_only_response(line)
        ]
        assert not undetected, (
            "These production lines were NOT detected as intent_only:\n"
            + "\n".join(f"  - {line!r}" for line in undetected)
        )

    def test_terminates_with_report_does_not_trigger(self) -> None:
        """Sentence describing a loop condition is NOT intent_only.

        Counter-example to the heuristic: 'O loop só termina com o
        relatório escrito' describes the policy of the loop, not an
        action the agent is about to take.  The heuristic must NOT flag
        it (otherwise we'd be over-aggressive on legitimate summary
        statements).
        """
        assert not is_intent_only_response(
            "O loop só termina com o relatório escrito."
        )


class TestHeuristicWithRealProviderPatterns:
    """Patterns that providers/model APIs sometimes emit in lieu of tool_calls."""

    def test_claude_style_status_message(self) -> None:
        """Claude often says 'I will now do X' as a status update."""
        assert is_intent_only_response(
            "I'll dispatch the two analyses in parallel now."
        )

    def test_anthropic_thinking_block_intent(self) -> None:
        """Anthropic-style 'I'll start by doing X'."""
        assert is_intent_only_response(
            "I am going to read both files and then synthesize the analysis."
        )

    def test_gemini_style_intent(self) -> None:
        """Gemini-style 'I will start' / 'Let me start'."""
        assert is_intent_only_response(
            "Let me start by analyzing the agent loop behavior."
        )

    def test_pure_intent_no_action(self) -> None:
        """Just intent, no action verb tense."""
        assert is_intent_only_response(
            "Vou."
        )

    def test_complex_intent_with_methodology(self) -> None:
        """Detailed methodology description with no concrete result markers."""
        assert is_intent_only_response(
            "Vou paralelizar leituras: agy_run_task e claude_run_task em paralelo, "
            "com payloads específicos para cada engine. Depois analiso os resultados."
        )

    def test_does_not_flag_when_tool_results_already_present(self) -> None:
        """When the message references concrete tool results, it's not intent_only."""
        # The agent should be able to summarize its tool results without
        # being flagged.
        msg = (
            "Resultado da análise agy:\n\n"
            "```\n"
            "file: femtobot/agent/runner.py\n"
            "issue: capped_out flag breaks everything\n"
            "```\n\n"
            "Resultado da análise claude:\n\n"
            "```\n"
            "file: femtobot/utils/runtime.py\n"
            "issue: missing helper\n"
            "```\n"
        )
        assert not is_intent_only_response(msg), (
            "Messages with code blocks / tool results must not be flagged"
        )

    def test_does_not_flag_when_inline_file_path_present(self) -> None:
        """An inline file path counts as concrete content."""
        assert not is_intent_only_response(
            "Vou investigar `femtobot/agent/runner.py` linha 412."
        )


# Integration test: model emits reported pattern twice, then issues tool_call.
@dataclass
class _FakeResponse:
    content: str
    tool_calls: list = None
    finish_reason: str = "stop"
    reasoning_content: str | None = None
    thinking_blocks: list | None = None

    def __post_init__(self) -> None:
        if self.tool_calls is None:
            self.tool_calls = []
        if self.thinking_blocks is None:
            self.thinking_blocks = []
        self.usage = {"prompt_tokens": 1, "completion_tokens": 1}

    @property
    def should_execute_tools(self) -> bool:
        return bool(self.tool_calls) and self.finish_reason in {
            "tool_use", "tool_calls", "function_call"
        }

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class _FakeTool:
    defs: list = field(default_factory=lambda: [{"type": "function", "function": {"name": "agy_run_task"}}])

    def get_definitions(self) -> list:
        return self.defs


class _StubHook(AgentHook):
    def finalize_content(self, ctx, content):  # type: ignore[override]
        return content

    def wants_streaming(self) -> bool:  # type: ignore[override]
        return False


async def test_reported_lines_trigger_pushback_in_runner() -> None:
    """When the model emits the exact user-reported line, the runner pushes back.

    This is the end-to-end test that confirms fix L1 handles the production
    patterns.  The runner must:
      1. Detect the intent_only line on turn 0
      2. Inject the corrective nudge
      3. Call the model again
      4. Accept the second response (with a real tool_call)
    """
    runner = AgentRunner(provider=MagicMock())
    spec = AgentRunSpec(
        model="stub",
        max_iterations=10,
        max_tool_result_chars=10000,
        initial_messages=[
            {"role": "system", "content": "You are Femtobot."},
            {"role": "user", "content": "Despache agy e claude."},
        ],
        tools=_FakeTool(defs=[{"name": "agy_run_task"}]),
        hook=_StubHook(),
    )

    calls = {"n": 0}

    async def fake_request(spec, messages, hook, context):
        calls["n"] += 1
        if calls["n"] == 1:
            # Exact user-reported line.
            return _FakeResponse(
                content="Tenho contexto suficiente. Despachando agora em paralelo "
                "— agy primeiro (cheap) + claude-sonnet (precisão).",
                finish_reason="stop",
            )
        # Second call: real tool_call.
        return _FakeResponse(
            content="",
            tool_calls=[MagicMock(id="call_1", name="agy_run_task", arguments={"x": "y"})],
            finish_reason="tool_use",
        )

    runner._request_model = fake_request  # type: ignore[assignment]

    async def fake_execute(spec, tool_calls, *_a, **_kw):
        return [{"ok": True}], [], None

    runner._execute_tools = fake_execute  # type: ignore[assignment]

    result = await runner.run(spec)

    # The first prose was NOT returned as final_content.
    assert "Tenho contexto suficiente" not in (result.final_content or "")
    # The nudge was injected.
    assert any(
        msg.get("role") == "user" and "tool call" in (msg.get("content") or "")
        for msg in result.messages
    ), "Nudge was not injected into messages"
    # The runner called the model at least twice.
    assert calls["n"] >= 2, (
        f"Runner should have called model again after pushback, got {calls['n']}"
    )


def test_constants_have_safe_defaults() -> None:
    """Sanity check: the cap must be > 0 and the prompt must mention tool calls."""
    from femtobot.utils.runtime import (
        _MAX_INTENT_RETRIES,
        INTENT_ONLY_FEEDBACK_PROMPT,
    )

    assert _MAX_INTENT_RETRIES > 0
    assert _MAX_INTENT_RETRIES <= 5, "Cap too high — would burn iteration budget"
    assert "tool call" in INTENT_ONLY_FEEDBACK_PROMPT
