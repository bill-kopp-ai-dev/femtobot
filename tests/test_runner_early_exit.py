"""``AgentRunner`` early-exit regression tests (v0.1.2 sixth-pass C1).

Audit C1: the previous implementation fell through the post-loop
finalize path on *every* ``break``, including the legitimate
"final response" path.  The post-loop code then *unconditionally*
overwrote ``final_content`` with the ``max_iterations`` template
message and reset ``stop_reason = "max_iterations"`` — even when
the model had produced a perfectly valid response and we were
about to return it.

This is the root cause of the Femtobot user-facing
"Max iterations (200) reached" message on trivial questions like
"ping" or "Who are you?": the model answered in 1 iteration, the
loop hit the legitimate ``final response`` break, and the
post-loop overwrite hid the answer.

We now track whether the break was due to *cap exhaustion*
(``capped_out = True``) and only enter the cap-exhaustion
finalize path when that's the case.

We pin:

* a model that responds on iteration 0 with no tool calls
  (``finish_reason=stop``, non-blank content) returns the
  model's content — NOT the max_iterations template,
* ``stop_reason`` is "completed" (or whatever the model path
  set), not "max_iterations",
* the assistant message is appended to history on the
  final-response path.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from femtobot.agent.hook import AgentHook
from femtobot.agent.runner import AgentRunner, AgentRunSpec


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
    """Minimal stand-in for the tool registry ``AgentRunner`` expects."""

    defs: list

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
) -> AgentRunSpec:
    if initial_messages is None:
        initial_messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "ping"},
        ]
    return AgentRunSpec(
        model="stub",
        max_iterations=max_iterations,
        max_tool_result_chars=10000,
        initial_messages=initial_messages,
        tools=_FakeTool(defs=[]),
        hook=_StubHook(),
    )


async def test_final_response_break_preserves_model_content() -> None:
    """C1: a model that responds on iter 0 returns its content, not max_iterations."""
    runner = AgentRunner(provider=MagicMock())
    spec = _make_spec(max_iterations=200)

    async def fake_request(spec, messages, hook, context):
        return _FakeResponse(content="Pong! 🏓", finish_reason="stop")

    runner._request_model = fake_request  # type: ignore[assignment]

    result = await runner.run(spec)

    # The model produced "Pong! 🏓" — that MUST be returned as-is.
    assert result.final_content == "Pong! 🏓", (
        f"Model content was overwritten by the post-loop finalize path;"
        f" got {result.final_content!r}"
    )
    assert result.stop_reason != "max_iterations", (
        f"stop_reason was overwritten to {result.stop_reason!r}"
    )


async def test_final_response_breaks_without_overwriting_assistant_message() -> None:
    """C1: the assistant message is appended to history on the final-response path."""
    runner = AgentRunner(provider=MagicMock())
    spec = _make_spec(max_iterations=200)

    async def fake_request(spec, messages, hook, context):
        return _FakeResponse(content="Short answer.", finish_reason="stop")

    runner._request_model = fake_request  # type: ignore[assignment]

    result = await runner.run(spec)

    # The assistant message MUST be the last entry in messages,
    # and it MUST be the model content (not the max_iterations
    # template).
    last_msg = result.messages[-1]
    assert last_msg["role"] == "assistant"
    assert last_msg["content"] == "Short answer.", (
        f"Last message was overwritten: {last_msg['content']!r}"
    )


async def test_capped_out_flag_init() -> None:
    """C1: source-level check that ``capped_out`` flag is wired (C1)."""
    import inspect

    from femtobot.agent.runner import AgentRunner

    src = inspect.getsource(AgentRunner.run)
    # The flag must be initialized.
    assert "capped_out = False" in src
    # And set to True on cap-exhaustion break.
    assert "capped_out = True" in src
    # And the post-loop finalize must be wrapped in ``if capped_out:``.
    assert "if capped_out:" in src
