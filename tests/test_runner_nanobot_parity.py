"""``AgentRunner`` nanobot-parity regression tests (v0.1.3 eighth-pass W1-W5).

Comparative audit between Femtobot's ``agent/runner.py`` and the
upstream nanobot project (the fork origin).  This file pins the
four areas we adopted from nanobot in v0.1.3:

* W1: the ``capped_out`` flag and ``for/else`` rationale
  (documentation-level: the Femtobot loop has 4 break points
  and uses ``itertools.count()``, so the nanobot ``for/else``
  idiom does not directly apply — we keep the explicit flag).
* W2: ``_strip_placeholder_assistant_messages`` and
  ``_strip_malformed_tool_calls`` (parity with nanobot's
  ``ContextGovernor.strip_*``).
* W4: ``_has_injection_content`` helper with ``None``/empty-list
  support (parity with nanobot).
* W5: ``_build_goal_continue_message`` with ``str | Callable | None``
  (parity with nanobot's spec/handler split).
"""

from __future__ import annotations

import inspect

from femtobot.agent.runner import AgentRunner

# ---------------------------------------------------------------------------
# W2 — _strip_placeholder_assistant_messages
# ---------------------------------------------------------------------------


def test_strip_placeholder_assistant_messages_removes_marker() -> None:
    """W2: a placeholder assistant message is dropped (W2)."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "[Previous assistant message omitted.]"},
        {"role": "user", "content": "next"},
    ]
    out = AgentRunner._strip_placeholder_assistant_messages(msgs)
    assert len(out) == 3
    assert all(m["content"] != "[Previous assistant message omitted.]" for m in out)


def test_strip_placeholder_assistant_messages_keeps_tool_calls() -> None:
    """W2: a placeholder message with tool_calls is preserved (W2)."""
    msgs = [
        {
            "role": "assistant",
            "content": "[Previous assistant message omitted.]",
            "tool_calls": [{"id": "t1", "function": {"name": "x"}}],
        }
    ]
    out = AgentRunner._strip_placeholder_assistant_messages(msgs)
    # Must not be removed when it carries tool_calls (the result is
    # a meaningful turn for the model).
    assert len(out) == 1


def test_strip_placeholder_assistant_messages_noop_on_clean() -> None:
    """W2: clean history is returned as-is (same list object)."""
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello!"},
    ]
    out = AgentRunner._strip_placeholder_assistant_messages(msgs)
    # Same list object when nothing changed (cheap path).
    assert out is msgs


# ---------------------------------------------------------------------------
# W2 — _strip_malformed_tool_calls
# ---------------------------------------------------------------------------


def test_strip_malformed_tool_calls_drops_bad_names() -> None:
    """W2: a tool_call with ``name=None`` is dropped (W2)."""
    msgs = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "t1", "function": {"name": None}},
                {"id": "t2", "function": {"name": "ok"}},
            ],
        }
    ]
    out = AgentRunner._strip_malformed_tool_calls(msgs)
    assert len(out) == 1
    assert len(out[0]["tool_calls"]) == 1
    assert out[0]["tool_calls"][0]["function"]["name"] == "ok"


def test_strip_malformed_tool_calls_drops_empty_names() -> None:
    """W2: a tool_call with ``name=""`` is dropped (W2)."""
    msgs = [
        {
            "role": "assistant",
            "content": "some content",
            "tool_calls": [{"id": "t1", "function": {"name": ""}}],
        }
    ]
    out = AgentRunner._strip_malformed_tool_calls(msgs)
    # Empty name is dropped; the assistant message still has content
    # so it is preserved.
    assert len(out) == 1
    assert "tool_calls" not in out[0]


def test_strip_malformed_tool_calls_drops_all_bad_assistant() -> None:
    """W2: an assistant turn with only bad calls AND no content is dropped (W2)."""
    msgs = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1", "function": {"name": None}}],
        }
    ]
    out = AgentRunner._strip_malformed_tool_calls(msgs)
    # No valid tool calls and no content → drop the entire message.
    assert out == []


def test_strip_malformed_tool_calls_handles_top_level_name() -> None:
    """W2: tool_calls may use top-level ``name`` (not nested) (W2)."""
    msgs = [
        {
            "role": "assistant",
            "content": "ok",
            "tool_calls": [{"id": "t1", "name": "ok"}, {"id": "t2", "name": ""}],
        }
    ]
    out = AgentRunner._strip_malformed_tool_calls(msgs)
    assert len(out) == 1
    assert len(out[0]["tool_calls"]) == 1
    assert out[0]["tool_calls"][0]["name"] == "ok"


def test_tool_call_name_is_valid_rejects_non_dict() -> None:
    """W2: ``_tool_call_name_is_valid`` rejects non-dict inputs."""
    assert AgentRunner._tool_call_name_is_valid("not a dict") is False
    assert AgentRunner._tool_call_name_is_valid(None) is False
    assert AgentRunner._tool_call_name_is_valid(123) is False


def test_tool_call_name_is_valid_accepts_valid() -> None:
    """W2: ``_tool_call_name_is_valid`` accepts valid calls."""
    assert (
        AgentRunner._tool_call_name_is_valid(
            {"id": "t1", "function": {"name": "ok"}}
        )
        is True
    )
    assert (
        AgentRunner._tool_call_name_is_valid({"id": "t1", "name": "ok"}) is True
    )


# ---------------------------------------------------------------------------
# W4 — _has_injection_content
# ---------------------------------------------------------------------------


def test_has_injection_content_handles_none() -> None:
    """W4: ``None`` content is rejected (W4)."""
    assert AgentRunner._has_injection_content(None) is False


def test_has_injection_content_handles_empty_string() -> None:
    """W4: empty/whitespace string is rejected (W4)."""
    assert AgentRunner._has_injection_content("") is False
    assert AgentRunner._has_injection_content("   ") is False


def test_has_injection_content_handles_non_empty_string() -> None:
    """W4: non-empty string is accepted (W4)."""
    assert AgentRunner._has_injection_content("hello") is True


def test_has_injection_content_handles_empty_list() -> None:
    """W4: empty list is rejected (W4)."""
    assert AgentRunner._has_injection_content([]) is False


def test_has_injection_content_handles_non_empty_list() -> None:
    """W4: non-empty list is accepted (W4)."""
    assert (
        AgentRunner._has_injection_content([{"type": "text", "text": "hi"}])
        is True
    )


def test_has_injection_content_accepts_other_types() -> None:
    """W4: arbitrary truthy types are accepted (W4)."""
    assert AgentRunner._has_injection_content(42) is True
    assert AgentRunner._has_injection_content({"key": "val"}) is True


# ---------------------------------------------------------------------------
# W5 — _build_goal_continue_message
# ---------------------------------------------------------------------------


def test_build_goal_continue_message_with_none_uses_default() -> None:
    """W5: ``None`` falls back to the default prompt (W5)."""
    out = AgentRunner._build_goal_continue_message(None)
    assert out["role"] == "user"
    # Default prompt contains "goal" or similar
    assert isinstance(out["content"], str)
    assert len(out["content"]) > 0


def test_build_goal_continue_message_with_string() -> None:
    """W5: a string is used directly (W5)."""
    out = AgentRunner._build_goal_continue_message("Custom prompt")
    assert out["content"] == "Custom prompt"


def test_build_goal_continue_message_with_callable() -> None:
    """W5: a callable is invoked to produce the content (W5)."""
    out = AgentRunner._build_goal_continue_message(lambda: "from callable")
    assert out["content"] == "from callable"


def test_build_goal_continue_message_broken_callable_falls_back() -> None:
    """W5: a broken callable is logged and we fall back to the default (W5)."""
    def broken():
        raise RuntimeError("oops")

    out = AgentRunner._build_goal_continue_message(broken)
    # The error was caught; the default is returned (not a re-raise).
    assert out["role"] == "user"
    assert len(out["content"]) > 0


def test_build_goal_continue_message_callable_returning_none() -> None:
    """W5: a callable returning ``None`` falls back to default (W5)."""
    out = AgentRunner._build_goal_continue_message(lambda: None)
    assert out["role"] == "user"
    assert len(out["content"]) > 0


# ---------------------------------------------------------------------------
# W1 — capped_out flag rationale (source-level)
# ---------------------------------------------------------------------------


def test_w1_capped_out_flag_rationale_documented() -> None:
    """W1: the ``capped_out`` flag is the minimal pattern given our loop structure (W1)."""
    src = inspect.getsource(AgentRunner.run)
    # The flag must still exist (W1 documents why we keep it).
    assert "capped_out" in src
    # And the comment block must explain why ``for/else`` does not apply.
    assert "W1" in src or "for/else" in src, (
        "W1 audit comment missing — the rationale for keeping the flag "
        "should be visible in the source"
    )
    # The cap-exhaustion break must set the flag.
    assert "capped_out = True" in src
    # The post-loop finalize must be guarded by the flag.
    assert "if capped_out:" in src
    # And the loop must use ``itertools.count()`` (this is the
    # structural reason for/else doesn't directly apply).
    assert "itertools.count()" in src
