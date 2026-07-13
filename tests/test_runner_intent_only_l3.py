"""L3 intent_only guard tests — concrete-marker dilution regression.

L3 (v0.1.8) closes the loophole exposed by the user's live transcript
on 2026-07-12 around the pBeanOS review session.  The model replied:

    "Pong. Saindo do loop sem emitir tool call — outra vez.
     Plano de ação:
       1. **Emitir as tool calls de fato** (read_file + exec) — neste turno.
       2. Reproduzir o deadlock ao vivo (lock fictício + teste real do
          `register`).
       3. Sintetizar Femto review.
       4. Escrever `/home/bill/Codes/zero_trust_env/contabo/Homarr/docs/REVIEW_E0.md`
          com Femto + claude + issues.
     Emitindo agora."

It contains:
  - intent verbs ("Emitir", "Emitindo", "Reproduzir", "Sintetizar",
    "Escrever")
  - inline backticks (`` `register` ``)
  - a long file path (`/home/bill/Codes/zero_trust_env/.../REVIEW_E0.md`)
  - bold markdown emphasis

The L2 heuristic (v0.1.7) short-circuited on the backticks/path and
*did not* flag this as intent_only — exactly the regression that
produced the "describe-but-don't-execute" loop.  L3 inverts the
default: when an intent verb is present, the response is flagged as
intent_only *unless* the content is overwhelmingly concrete (>=60%
of characters live inside markers) or it matches a final-farewell
pattern.

These tests pin the new behavior:

  * mixed intent+marker responses are flagged (regression coverage for
    the user's transcript),
  * overwhelmingly concrete artifacts (code dumps, tool result blocks)
    are NOT flagged,
  * pure acknowledgments ("Pong.", "Combinado.") are NOT flagged,
  * strong markers (``[Tool result``, ``tool_call_id``,
    ``function_call``) still short-circuit unconditionally,
  * every L1+L2 case still passes (no regression on prior behavior).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from femtobot.agent.hook import AgentHook
from femtobot.agent.runner import AgentRunner, AgentRunSpec
from femtobot.utils.runtime import (
    _MAX_INTENT_RETRIES,
    INTENT_ONLY_FEEDBACK_PROMPT,
    is_intent_only_response,
)

# ---------------------------------------------------------------------------
# L3 regression: mixed intent + concrete marker
# ---------------------------------------------------------------------------


PONG_PROSE = (
    "Pong. Saindo do loop sem emitir tool call — outra vez. "
    "Você está certo em estar frustrado. A correção real é simples: "
    "parar de narrar e clicar.\n\n"
    "Plano de ação:\n"
    "1. **Emitir as tool calls de fato** (read_file + exec) — neste turno.\n"
    "2. Reproduzir o deadlock ao vivo (lock fictício + teste real do "
    "`register`).\n"
    "3. Sintetizar Femto review.\n"
    "4. Escrever `/home/bill/Codes/zero_trust_env/contabo/Homarr/docs/"
    "REVIEW_E0.md` com Femto + claude + issues.\n\n"
    "Emitindo agora."
)


class TestL3MixedIntentAndMarkers:
    """L3 regression: the exact user transcript must now be flagged."""

    def test_pong_prose_with_intent_verb_and_paths_is_flagged(self) -> None:
        """The full transcript from the 2026-07-12 session must trip L3.

        L2 let this through because of the inline `` `register` `` and
        the absolute file path.  L3 must catch it because the intent
        verbs dominate the response.
        """
        assert is_intent_only_response(PONG_PROSE), (
            "L3 must flag mixed intent+marker responses like the Pong "
            "transcript that evaded L2."
        )

    def test_intent_with_inline_code_is_flagged(self) -> None:
        """Mentioning a tool name in backticks is still intent_only."""
        assert is_intent_only_response(
            "Vou chamar `read_file` agora para abrir o arquivo."
        )

    def test_intent_with_absolute_path_is_flagged(self) -> None:
        """Mentioning a path with intent verb is intent_only."""
        assert is_intent_only_response(
            "Vou escrever o relatório em "
            "/home/bill/Codes/zero_trust_env/contabo/Homarr/docs/REVIEW_E0.md"
        )

    def test_intent_with_bold_markdown_is_flagged(self) -> None:
        """Markdown bold does not save intent_only responses."""
        assert is_intent_only_response(
            "**Plano**: vou ler 2 arquivos e emitir o relatório."
        )

    def test_multiple_intent_verbs_with_path_is_flagged(self) -> None:
        """Multiple intent verbs + path — still intent_only."""
        assert is_intent_only_response(
            "Vou ler o arquivo `/home/bill/foo.py`, vou executar os testes, "
            "vou consolidar o relatório."
        )


# ---------------------------------------------------------------------------
# L3 non-regression: overwhelmingly concrete content stays unflagged
# ---------------------------------------------------------------------------


class TestL3ConcreteArtifactShortCircuit:
    """L3 still respects 'this is a real artifact, not a description'."""

    def test_pure_code_block_not_flagged(self) -> None:
        """A long code block with no intent verb is not intent_only."""
        code = (
            "Here's the diff:\n\n"
            "```python\n"
            "def foo():\n"
            "    return 1\n"
            "def bar():\n"
            "    return 2\n"
            "def baz():\n"
            "    return 3\n"
            "```\n"
        )
        assert not is_intent_only_response(code)

    def test_intent_verb_in_long_code_block_not_flagged(self) -> None:
        """Intent verb *inside* a long code block is not intent_only.

        The marker ratio (>=60%) is what saves this — the verb is a
        sub-clause of a real artifact, not the dominant intent.
        """
        code = (
            "Refatoração aplicada:\n\n"
            "```python\n"
            "async def run_tool_call(tool_name, args):\n"
            "    \"\"\"Execute a tool call asynchronously.\n"
            "    \n"
            "    Will dispatch to the right engine.\n"
            "    \"\"\"\n"
            "    if tool_name in registry:\n"
            "        return await registry[tool_name](args)\n"
            "    raise ValueError(tool_name)\n"
            "\n"
            "async def execute_plan(plan):\n"
            "    for step in plan:\n"
            "        await run_tool_call(step.tool, step.args)\n"
            "```\n"
        )
        assert not is_intent_only_response(code)

    def test_tool_result_block_not_flagged(self) -> None:
        """[Tool result ...] prefix is a strong marker → short-circuits."""
        assert not is_intent_only_response(
            "[Tool result for tool_id=call_1]\n"
            "Status: success\n"
            "Output: 42\n"
        )

    def test_function_call_json_not_flagged(self) -> None:
        """function_call JSON pattern is a strong marker."""
        assert not is_intent_only_response(
            '{"function_call": {"name": "agy_run_task", "arguments": {}}}'
        )


# ---------------------------------------------------------------------------
# L3 farewell pattern
# ---------------------------------------------------------------------------


class TestL3FarewellPatterns:
    """Pure acknowledgments should not be flagged as intent_only."""

    @pytest.mark.parametrize(
        "text",
        [
            "Pong.",
            "Pong",
            "pong",
            "Ok.",
            "OK!",
            "Combinado.",
            "Combinado",
            "Entendido.",
            "Pronto.",
            "Beleza.",
            "Show.",
            "Blz",
            "Fechou.",
            "Tranquilo.",
        ],
    )
    def test_pure_acknowledgments_not_flagged(self, text: str) -> None:
        """Pure farewells like 'Pong.' are not intent_only even with no
        tool call.  They're legitimate closures of the turn.
        """
        assert not is_intent_only_response(text), (
            f"Pure acknowledgment {text!r} must not be flagged"
        )


# ---------------------------------------------------------------------------
# L1/L2 non-regression — every prior test case must still pass
# ---------------------------------------------------------------------------


class TestL1L2BackwardCompat:
    """L3 must not break any L1 or L2 case."""

    @pytest.mark.parametrize(
        "text",
        [
            "Tenho contexto suficiente. Vou despachar as duas análises "
            "independentes em paralelo agora.",
            "Tenho contexto suficiente. Despachando agora em paralelo — "
            "agy primeiro (cheap) + claude-sonnet (precisão).",
            "Pensei em despachar, mas não chegou a sair: ainda preciso "
            "escrever os payloads antes de cada agy_run_task/claude_start_task.",
            "Sim, despachando agora as duas em paralelo. Tarefas "
            "independentes, então não há ordem obrigatória.",
            "Combinado. Quando os dois engines (agy + claude-sonnet) "
            "terminarem as análises da E0, eu trago o resultado consolidado.",
            "Ainda não. Eu disse que ia despachar mas acabei só falando — "
            "ainda não disparei nenhuma chamada MCP.",
            "Vou fazer a Femto review agora — ler os 2 arquivos críticos "
            "com lupa, reproduzir o deadlock se possível, e cruzar com o "
            "claude review.",
            "Você está certo — outra vez. Emitindo as chamadas de verdade.",
            "Emitindo agora as chamadas de verdade.",
            "Vou emitir as leituras, reproduzir o deadlock ao vivo, e gerar "
            "o relatório consolidado.",
        ],
    )
    def test_l1l2_production_lines_still_flagged(self, text: str) -> None:
        assert is_intent_only_response(text), (
            f"L1/L2 line must still trip the heuristic: {text!r}"
        )

    def test_pure_question_not_flagged(self) -> None:
        assert not is_intent_only_response("O que você acha disso?")

    def test_blank_not_flagged(self) -> None:
        assert not is_intent_only_response("")
        assert not is_intent_only_response(None)
        assert not is_intent_only_response("   \n  ")

    def test_past_tense_summary_not_flagged(self) -> None:
        assert not is_intent_only_response(
            "Dispatched in parallel — both engines returned successfully."
        )

    def test_loop_condition_not_flagged(self) -> None:
        """Counter-example from L2: 'O loop só termina com o relatório'."""
        assert not is_intent_only_response(
            "O loop só termina com o relatório escrito."
        )


# ---------------------------------------------------------------------------
# Constants surface
# ---------------------------------------------------------------------------


def test_l3_constants_exposed() -> None:
    """Sanity: constants are importable and have safe defaults."""
    assert isinstance(_MAX_INTENT_RETRIES, int)
    assert _MAX_INTENT_RETRIES > 0
    assert isinstance(INTENT_ONLY_FEEDBACK_PROMPT, str)
    assert "tool call" in INTENT_ONLY_FEEDBACK_PROMPT


# ---------------------------------------------------------------------------
# Integration: L3 catches the Pong transcript via the runner
# ---------------------------------------------------------------------------


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
    defs: list = field(default_factory=lambda: [
        {"type": "function", "function": {"name": "read_file"}}
    ])

    def get_definitions(self) -> list:
        return self.defs


class _StubHook(AgentHook):
    def finalize_content(self, ctx, content):  # type: ignore[override]
        return content

    def wants_streaming(self) -> bool:  # type: ignore[override]
        return False


async def test_l3_pong_transcript_triggers_pushback_in_runner() -> None:
    """End-to-end: the user-transcript Pong response must trigger the
    intent_only pushback in the runner (L2 let it through).
    """
    runner = AgentRunner(provider=MagicMock())
    spec = AgentRunSpec(
        model="stub",
        max_iterations=10,
        max_tool_result_chars=10000,
        initial_messages=[
            {"role": "system", "content": "You are Femtobot."},
            {"role": "user", "content": "Siga com a atividade."},
        ],
        tools=_FakeTool(defs=[{"name": "read_file"}]),
        hook=_StubHook(),
    )

    calls = {"n": 0}

    async def fake_request(spec, messages, hook, context):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(content=PONG_PROSE, finish_reason="stop")
        return _FakeResponse(
            content="",
            tool_calls=[MagicMock(id="call_1", name="read_file",
                                  arguments={"path": "x.md"})],
            finish_reason="tool_use",
        )

    runner._request_model = fake_request  # type: ignore[assignment]

    async def fake_execute(spec, tool_calls, *_a, **_kw):
        return [{"ok": True}], [], None

    runner._execute_tools = fake_execute  # type: ignore[assignment]

    result = await runner.run(spec)

    # The Pong prose must NOT be returned as final_content.
    assert "Pong" not in (result.final_content or "")
    # The runner called the model at least twice.
    assert calls["n"] >= 2, (
        f"Runner should push back on Pong transcript; got {calls['n']} calls"
    )
    # The nudge was injected.
    assert any(
        msg.get("role") == "user" and "tool call" in (msg.get("content") or "")
        for msg in result.messages
    ), "Nudge was not injected for Pong transcript"
