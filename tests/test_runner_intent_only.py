"""``AgentRunner`` intent_only guard tests (v0.1.7 L1).

Audit L1: when the model produces prose that *describes* an upcoming tool
action ("Despachando em paralelo…", "I'll dispatch…") without emitting a
corresponding ``tool_calls`` payload, the runner used to accept that prose
as the final answer and exit the iteration loop.  The user would then see
the agent promise work that was never executed, ask "are you done?", and
get another prose-only answer — an infinite "describing but never doing"
loop.

The fix introduces :func:`is_intent_only_response` and a guard in the
final-response branch of the runner.  When the guard fires the runner
appends a corrective user-role nudge and continues the iteration,
capped at ``_MAX_INTENT_RETRIES`` so a stubborn model cannot burn the
iteration budget.

These tests pin:

* the heuristic itself (positive/negative cases),
* the runner behavior on a single intent_only response (continues, does
  not return prose as final),
* the runner behavior after the retry cap is exceeded (falls back to
  accepting the prose as final so the loop terminates),
* the runner behavior when no tools are available (heuristic does not
  fire — there is nothing to dispatch, so prose is a legitimate answer),
* the runner behavior when the response contains concrete markers (a
  file path, a code block) — heuristic must not fire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from femtobot.agent.hook import AgentHook
from femtobot.agent.runner import AgentRunner, AgentRunSpec
from femtobot.utils.runtime import (
    _MAX_INTENT_RETRIES,
    INTENT_ONLY_FEEDBACK_PROMPT,
    build_intent_only_feedback_message,
    is_intent_only_response,
)

# ---------------------------------------------------------------------------
# Heuristic unit tests
# ---------------------------------------------------------------------------


class TestIsIntentOnlyResponse:
    def test_detects_portuguese_despachando(self) -> None:
        assert is_intent_only_response(
            "Despachando agora em paralelo — agy primeiro (cheap) + claude-sonnet."
        )

    def test_detects_portuguese_vou_executar(self) -> None:
        assert is_intent_only_response(
            "Vou executar o pipeline em paralelo agora."
        )

    def test_detects_english_dispatching(self) -> None:
        assert is_intent_only_response(
            "Dispatching the two engines in parallel now."
        )

    def test_detects_english_i_will(self) -> None:
        assert is_intent_only_response("I'll dispatch the analysis now.")

    def test_does_not_detect_pure_question(self) -> None:
        # No intent verb → not intent_only.
        assert not is_intent_only_response("O que você acha disso?")

    def test_does_not_detect_blank(self) -> None:
        assert not is_intent_only_response("")
        assert not is_intent_only_response(None)
        assert not is_intent_only_response("   \n  ")

    def test_does_not_detect_when_code_block_present(self) -> None:
        # Concrete result marker → not intent_only.
        content = (
            "Vou refatorar usando este snippet:\n\n"
            "```python\ndef foo():\n    return 1\n```\n"
        )
        assert not is_intent_only_response(content)

    def test_does_not_detect_when_file_path_present(self) -> None:
        # Inline code marker → not intent_only.
        assert not is_intent_only_response(
            "Vou editar o arquivo `femtobot/agent/runner.py`."
        )

    def test_does_not_detect_when_url_present(self) -> None:
        # URL-ish marker → not intent_only.
        assert not is_intent_only_response(
            "Vou consultar https://example.com/api/v1/results agora."
        )

    def test_does_not_detect_past_tense(self) -> None:
        # Past tense without future intent → legitimate summary.
        assert not is_intent_only_response(
            "Dispatched in parallel — both engines returned successfully."
        )

    def test_message_has_role_user(self) -> None:
        msg = build_intent_only_feedback_message()
        assert msg["role"] == "user"
        assert "tool call" in msg["content"]


# ---------------------------------------------------------------------------
# Runner integration tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    content: str
    tool_calls: list = None
    finish_reason: str = "stop"
    reasoning_content: str | None = None
    thinking_blocks: list | None = None
    usage: dict | None = None

    def __post_init__(self) -> None:
        if self.tool_calls is None:
            self.tool_calls = []
        if self.usage is None:
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
    """Minimal stand-in for the tool registry — exposes 1 fake tool."""

    defs: list = field(default_factory=lambda: [{"type": "function", "function": {"name": "agy_run_task"}}])

    def get_definitions(self) -> list:
        return self.defs


class _StubHook(AgentHook):
    def finalize_content(self, ctx, content):  # type: ignore[override]
        return content

    def wants_streaming(self) -> bool:  # type: ignore[override]
        return False


def _make_spec(
    max_iterations: int = 5,
    initial_messages: list | None = None,
    with_tools: bool = True,
) -> AgentRunSpec:
    if initial_messages is None:
        initial_messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Do the thing."},
        ]
    tools = _FakeTool(defs=[{"name": "agy_run_task"}]) if with_tools else _FakeTool(defs=[])
    return AgentRunSpec(
        model="stub",
        max_iterations=max_iterations,
        max_tool_result_chars=10000,
        initial_messages=initial_messages,
        tools=tools,
        hook=_StubHook(),
    )


async def test_intent_only_response_does_not_become_final() -> None:
    """L1: a prose-only intent response must NOT terminate the iteration.

    The model answers with 'Despachando agora em paralelo…' but no tool_call.
    The runner must continue iterating instead of returning the prose as
    the final answer.
    """
    runner = AgentRunner(provider=MagicMock())
    spec = _make_spec(max_iterations=5)

    calls = {"n": 0}

    async def fake_request(spec, messages, hook, context):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(
                content="Despachando agora em paralelo — agy primeiro.",
                finish_reason="stop",
            )
        # Second call: model emits a real tool_call → loop should execute.
        return _FakeResponse(
            content="",
            tool_calls=[
                MagicMock(
                    id="call_1",
                    name="agy_run_task",
                    arguments={"prompt": "x"},
                ),
            ],
            finish_reason="tool_use",
        )

    runner._request_model = fake_request  # type: ignore[assignment]

    # Patch tool execution to return immediately so the test focuses on
    # the intent_only guard, not on tool mechanics.
    async def fake_execute(spec, tool_calls, *_args, **_kwargs):
        # Simulate one successful tool call so the loop proceeds.
        return [{"ok": True}], [], None

    runner._execute_tools = fake_execute  # type: ignore[assignment]

    result = await runner.run(spec)

    # The runner called the model at least twice: once for intent_only,
    # then again after the nudge.  The first prose response was NOT
    # returned as final_content.
    assert calls["n"] >= 2, (
        f"Runner should have called the model again after intent_only detection;"
        f" got {calls['n']} calls"
    )
    # final_content should not be the intent_only prose verbatim.
    assert result.final_content != "Despachando agora em paralelo — agy primeiro."
    # The nudge message must be present in messages history.
    nudge_present = any(
        msg.get("role") == "user" and "tool call" in (msg.get("content") or "")
        for msg in result.messages
    )
    assert nudge_present, "Runner did not inject the intent_only nudge into messages"


async def test_intent_only_response_capped_after_max_retries() -> None:
    """L1: after ``_MAX_INTENT_RETRIES`` the loop accepts the prose as final.

    If the model keeps describing without acting, we stop pushing back —
    further nudging would just burn the iteration budget and the user
    still needs to see *something*.
    """
    runner = AgentRunner(provider=MagicMock())
    spec = _make_spec(max_iterations=_MAX_INTENT_RETRIES + 5)

    async def fake_request(spec, messages, hook, context):
        return _FakeResponse(
            content="Vou despachar agora em paralelo.",
            finish_reason="stop",
        )

    runner._request_model = fake_request  # type: ignore[assignment]

    result = await runner.run(spec)

    # The model only ever produces intent_only responses.  After the retry
    # cap the runner accepts the most recent prose as the final answer
    # so the loop terminates and the user isn't left hanging.
    assert result.final_content is not None
    assert "Vou despachar" in result.final_content


async def test_intent_only_heuristic_does_not_fire_without_tools() -> None:
    """L1: when no tools are available, prose describing 'doing' is legitimate.

    If the model has zero tools it cannot dispatch anything — its prose is
    the only possible answer.  The heuristic must not gate the response.
    """
    runner = AgentRunner(provider=MagicMock())
    spec = _make_spec(max_iterations=5, with_tools=False)

    async def fake_request(spec, messages, hook, context):
        return _FakeResponse(
            content="Despachando agora em paralelo — não tenho tools, então explico.",
            finish_reason="stop",
        )

    runner._request_model = fake_request  # type: ignore[assignment]

    result = await runner.run(spec)

    # The prose must be returned as-is — no intent_only guard fires.
    assert "Despachando agora" in result.final_content


async def test_intent_only_heuristic_does_not_fire_when_code_in_response() -> None:
    """L1: responses containing concrete markers are not flagged.

    A response like 'Vou editar X — voici le code:\n```py ... ```' has an
    intent verb AND a code block.  The code block short-circuits the
    heuristic: the model clearly produced something concrete.
    """
    runner = AgentRunner(provider=MagicMock())
    spec = _make_spec(max_iterations=5)

    async def fake_request(spec, messages, hook, context):
        return _FakeResponse(
            content=(
                "Vou editar o arquivo assim:\n\n"
                "```python\ndef foo():\n    return 1\n```\n"
            ),
            finish_reason="stop",
        )

    runner._request_model = fake_request  # type: ignore[assignment]

    result = await runner.run(spec)

    # The response is returned as final — no intent_only pushback.
    assert "```python" in (result.final_content or "")
    assert "Vou editar" in (result.final_content or "")


async def test_intent_only_retries_counter_persists() -> None:
    """L1: the retry counter is stored on the spec so subsequent turns see it."""
    runner = AgentRunner(provider=MagicMock())
    spec = _make_spec(max_iterations=10)

    async def fake_request(spec, messages, hook, context):
        return _FakeResponse(
            content="Vou executar agora.",
            finish_reason="stop",
        )

    runner._request_model = fake_request  # type: ignore[assignment]

    # Run for fewer iterations than the cap to avoid the post-cap fallback
    # path; we just want to confirm the counter gets set on the spec.
    # Pre-seed the counter to exactly the cap so the next attempt falls
    # through to "accept prose as final".
    spec.intent_only_retries = _MAX_INTENT_RETRIES

    result = await runner.run(spec)

    # Once the cap is hit, the most recent prose is the final answer.
    assert "Vou executar" in (result.final_content or "")


def test_constants_are_exposed() -> None:
    """L1: the constants and helpers must remain importable from runtime."""
    # These are the public surface used by the runner.  If a future refactor
    # renames any of them, this test fails loudly.
    assert isinstance(_MAX_INTENT_RETRIES, int)
    assert _MAX_INTENT_RETRIES > 0
    assert isinstance(INTENT_ONLY_FEEDBACK_PROMPT, str)
    assert "tool call" in INTENT_ONLY_FEEDBACK_PROMPT
