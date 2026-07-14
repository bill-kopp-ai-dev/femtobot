"""Regression test: 12 consecutive read_file tool calls must keep the history intact.

This is the exact failure mode reported in the bug:

  "femtobot is unable to keep a coherent context after several tool calls."

Prior to the V3 fix, ``runner.py`` ran ``_microcompact`` on every turn
unconditionally. With more than 10 ``read_file`` results, the agent
silently rewrote them to ``[read_file result omitted from context]``,
causing the model to lose all references to file content.

After the V3 fix, ``runner.py`` delegates to ``ContextGovernor``, whose
``compact_inflight_overflow`` only fires when the request would actually
exceed the configured budget. With a high ``context_window_tokens`` (the
test uses 200 000), 12 short results must all survive verbatim.
"""

from __future__ import annotations

from types import SimpleNamespace

from femtobot.agent.context_governance import (
    ContextGovernanceConfig,
    ContextGovernor,
)


def _build_messages(num_reads: int) -> list[dict]:
    """Build an initial_messages list that mimics 12 read_file calls."""
    messages = [
        {"role": "system", "content": "You are femtobot."},
        {"role": "user", "content": "Read 12 files."},
    ]
    for i in range(num_reads):
        tool_call_id = f"call_{i:02d}"
        # Realistic read_file body: a few hundred characters per result.
        body = f"file_{i:02d}.txt\n" + ("x" * 400)
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": "read_file",
            "content": body,
        })
    messages.append({"role": "assistant", "content": "All 12 files read."})
    return messages


def test_inflight_overflow_does_not_compact_when_within_budget() -> None:
    """With a high context window, the 12 read_file results must survive intact."""
    messages = _build_messages(12)

    provider = SimpleNamespace(
        generation=SimpleNamespace(max_tokens=4096),
        estimate_message_tokens=lambda msg: max(1, len(str(msg)) // 4),
    )
    tools = SimpleNamespace(get_definitions=lambda: [])

    config = ContextGovernanceConfig(
        provider=provider,
        model="fake",
        tools=tools,
        workspace=None,
        session_key="test_session",
        max_tool_result_chars=200_000,
        context_window_tokens=200_000,
        context_block_limit=None,
        max_tokens=4096,
        inflight_start_index=0,
    )
    governor = ContextGovernor()
    compacted: set[str] = set()
    out = governor.prepare_for_model(config, messages, compacted)

    tool_messages = [m for m in out if m.get("role") == "tool"]
    assert len(tool_messages) == 12, (
        f"expected 12 tool messages preserved, got {len(tool_messages)}"
    )

    # Every result must still contain its file_XX.txt marker and not be
    # rewritten to a compaction summary.
    for i, msg in enumerate(tool_messages):
        assert f"file_{i:02d}.txt" in msg["content"], (
            f"tool result {i} was compacted away: {msg['content']!r}"
        )
        assert "omitted from context" not in msg["content"], (
            f"tool result {i} was rewritten to a placeholder: {msg['content']!r}"
        )

    # Compacted set must be empty since we never overflowed.
    assert compacted == set()


def test_inflight_overflow_compacts_when_budget_is_exceeded() -> None:
    """When the prompt actually exceeds budget, compaction must kick in.

    This guarantees we did not regress in the opposite direction
    (i.e. disabled compaction entirely).
    """
    # Heavy payloads so that 12 results truly exceed a small budget.
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Read 12 files."},
    ]
    for i in range(12):
        tool_call_id = f"call_{i:02d}"
        body = "x" * 2_000  # 2 KB each — 12 * 2 KB = 24 KB of tool output
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": "read_file",
            "content": body,
        })

    class _Provider:
        generation = SimpleNamespace(max_tokens=4096)

        def estimate_message_tokens(self, msg):
            return max(1, len(str(msg)) // 4)

    provider = _Provider()
    tools = SimpleNamespace(get_definitions=lambda: [])

    # 1 500-token budget cannot fit 12 * ~500-token tool bodies
    # (the chain estimate is ~3 500 tokens); the compactor must fire.
    config = ContextGovernanceConfig(
        provider=provider,
        model="fake",
        tools=tools,
        workspace=None,
        session_key="test_session",
        max_tool_result_chars=200_000,
        context_window_tokens=1_500,
        context_block_limit=None,
        max_tokens=0,
        inflight_start_index=0,
    )
    governor = ContextGovernor()
    compacted: set[str] = set()
    out = governor.prepare_for_model(config, messages, compacted)

    tool_messages = [m for m in out if m.get("role") == "tool"]
    summaries = sum(
        1 for m in tool_messages if "compacted to fit context" in m["content"]
    )
    assert summaries > 0, (
        "with a 1500-token budget and 12 * 2 KB tool bodies, the overflow "
        "compactor must have rewritten at least one tool result"
    )
    assert len(compacted) >= summaries


def test_backfill_inserts_synthetic_result_for_missing_tool_call() -> None:
    """An assistant tool_call with no tool reply must be backfilled."""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "orphan",
                    "type": "function",
                    "function": {"name": "exec", "arguments": "{}"},
                }
            ],
        },
    ]
    provider = SimpleNamespace(
        generation=SimpleNamespace(max_tokens=4096),
        estimate_message_tokens=lambda msg: max(1, len(str(msg)) // 4),
    )
    tools = SimpleNamespace(get_definitions=lambda: [])

    config = ContextGovernanceConfig(
        provider=provider,
        model="fake",
        tools=tools,
        workspace=None,
        session_key="test",
        max_tool_result_chars=200_000,
        context_window_tokens=200_000,
        context_block_limit=None,
        max_tokens=4096,
        inflight_start_index=0,
    )
    governor = ContextGovernor()
    compacted: set[str] = set()
    out = governor.prepare_for_model(config, messages, compacted)

    backfilled = [
        m for m in out
        if m.get("role") == "tool"
        and m.get("tool_call_id") == "orphan"
        and "unavailable" in m["content"]
    ]
    assert len(backfilled) == 1, (
        f"expected one synthetic tool result for orphan call, got {backfilled}"
    )


def test_drop_orphan_removes_tool_results_without_matching_call() -> None:
    """Tool results whose tool_call_id has no matching assistant call are dropped."""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
        {
            "role": "tool",
            "tool_call_id": "ghost",
            "name": "read_file",
            "content": "stale payload",
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "live",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "live",
            "name": "read_file",
            "content": "fresh payload",
        },
    ]
    provider = SimpleNamespace(
        generation=SimpleNamespace(max_tokens=4096),
        estimate_message_tokens=lambda msg: max(1, len(str(msg)) // 4),
    )
    tools = SimpleNamespace(get_definitions=lambda: [])

    config = ContextGovernanceConfig(
        provider=provider,
        model="fake",
        tools=tools,
        workspace=None,
        session_key="test",
        max_tool_result_chars=200_000,
        context_window_tokens=200_000,
        context_block_limit=None,
        max_tokens=4096,
        inflight_start_index=0,
    )
    governor = ContextGovernor()
    compacted: set[str] = set()
    out = governor.prepare_for_model(config, messages, compacted)

    tool_ids = {m.get("tool_call_id") for m in out if m.get("role") == "tool"}
    assert "ghost" not in tool_ids
    assert "live" in tool_ids
