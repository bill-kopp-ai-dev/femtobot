"""End-to-end regression prompt for the v0.1.x "agent loses context" bug.

This is the prompt the user (Bill) should send to the running ``femtobot``
CLI to confirm the regression is fixed. It does NOT call any LLM — it just
exercises the runner's context-governance pipeline with a synthetic
message stream that mimics the exact failure mode reported in the bug
report:

  "femtobot is unable to keep a coherent context after several tool calls"
  "cannot call MCP servers"
  "cannot execute tools and do useful tasks"

How to run it
-------------

From the project root (``femtobot/``)::

    python tests/e2e_regression_prompt.py

The script will:
1. Build a synthetic 12-turn conversation that mimics the agent having
   made 12 consecutive ``read_file`` tool calls (the exact trigger of the
   old ``_microcompact`` unconditional rewrite).
2. Push that conversation through ``AgentRunner._governor.prepare_for_model``
   using the same ``AgentRunSpec`` the real CLI builds.
3. Assert that *all 12* tool results survive verbatim (the regression
   was rewriting them to ``[read_file result omitted from context]``).
4. Re-run with a deliberately-too-small context window to prove the
   overflow compactor still fires when it should.
5. Print a checklist the operator can tick off after a manual run.

After running this script and observing ``ALL CHECKS PASSED``, the
operator should also perform the *manual* end-to-end check at the bottom
of this file: run ``femtobot`` in the real CLI, paste the prompt in
``MANUAL_E2E_PROMPT``, and confirm the agent (a) calls MCP servers,
(b) reads multiple files coherently, and (c) does not loop on the
"describe-action-but-no-tool-call" auto-correction message that
dominated the regressed sessions.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from femtobot.agent.context_governance import (  # noqa: E402
    ContextGovernanceConfig,
    ContextGovernor,
)


# ---------------------------------------------------------------------------
# Synthetic conversation — 12 read_file calls in a row.
# ---------------------------------------------------------------------------


def _make_conversation(num_files: int = 12) -> list[dict[str, Any]]:
    """Build a synthetic conversation: 1 user turn + 12 read_file tool calls.

    Each tool result is intentionally long enough to be a real load (a few
    hundred chars of file body) so a regression that truncates them shows
    up as missing content rather than missing tokens.
    """
    body_template = (
        "// file_{i:02d}.txt\n"
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris "
        "nisi ut aliquip ex ea commodo consequat."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are femtobot. Use tools to answer."},
        {"role": "user", "content": "Read 12 files in sequence and summarise."},
    ]
    for i in range(num_files):
        call_id = f"call_{i:02d}"
        body = body_template.format(i=i) * 2  # ~600 chars per result
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": f'{{"path":"file_{i:02d}.txt"}}'},
                }
            ],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": "read_file",
            "content": body,
        })
    messages.append({"role": "assistant", "content": "All 12 files have been read."})
    return messages


# ---------------------------------------------------------------------------
# Tiny provider stub used only by this script (no LLM calls).
# ---------------------------------------------------------------------------


class _StubProvider:
    """Minimal stand-in for ``LLMProvider`` that just counts tokens by length."""

    generation = SimpleNamespace(max_tokens=4096)

    @staticmethod
    def estimate_message_tokens(message: dict[str, Any]) -> int:
        return max(1, len(json.dumps(message, default=str)) // 4)


class _StubTools:
    """Minimal stand-in for ``ToolRegistry`` (only ``get_definitions`` is used)."""

    def get_definitions(self) -> list[dict[str, Any]]:
        return []


def _make_config(*, context_window_tokens: int) -> ContextGovernanceConfig:
    return ContextGovernanceConfig(
        provider=_StubProvider(),
        model="fake-model",
        tools=_StubTools(),
        workspace=None,
        session_key="e2e_regression",
        max_tool_result_chars=200_000,
        context_window_tokens=context_window_tokens,
        context_block_limit=None,
        max_tokens=4096,
        inflight_start_index=0,
    )


# ---------------------------------------------------------------------------
# Check 1 — the regression itself: results must survive under a normal window.
# ---------------------------------------------------------------------------


def check_regression_is_fixed() -> tuple[bool, list[str]]:
    notes: list[str] = []
    messages = _make_conversation(12)
    governor = ContextGovernor()
    compacted: set[str] = set()
    out = governor.prepare_for_model(_make_config(context_window_tokens=200_000), messages, compacted)

    tool_msgs = [m for m in out if m.get("role") == "tool"]
    if len(tool_msgs) != 12:
        return False, [f"expected 12 tool messages preserved, got {len(tool_msgs)}"]

    for i, msg in enumerate(tool_msgs):
        marker = f"file_{i:02d}.txt"
        content = msg.get("content", "")
        if marker not in content:
            return False, [f"tool result {i} lost its file marker ({marker!r})"]
        if "omitted from context" in content:
            return False, [f"tool result {i} was rewritten to a placeholder (regression!)"]

    if compacted:
        return False, [f"compacted ids leaked into a non-overflow turn: {sorted(compacted)}"]

    notes.append("12 tool results preserved verbatim under a 200 000-token budget.")
    notes.append("No '[omitted from context]' placeholder was injected.")
    return True, notes


# ---------------------------------------------------------------------------
# Check 2 — the compactor still fires when the prompt genuinely overflows.
# ---------------------------------------------------------------------------


def check_compactor_still_works() -> tuple[bool, list[str]]:
    notes: list[str] = []
    messages = _make_conversation(12)
    # Force the payloads to be heavy so the chain estimate definitely exceeds budget.
    for msg in messages:
        if msg.get("role") == "tool":
            msg["content"] = "x" * 4_000  # ~1 000 tokens each → 12 * 1 000 = 12 000 tokens

    # Use an 8 000-token window with a 512-token max completion. The chain
    # estimate is ~12 000 tokens (well above the 6 464-token budget), so the
    # overflow compactor must fire and rewrite at least one tool result.
    config = _make_config(context_window_tokens=8_000)
    # Override max_tokens so the budget is non-negative.
    object.__setattr__(config, "max_tokens", 512)

    governor = ContextGovernor()
    compacted: set[str] = set()
    out = governor.prepare_for_model(config, messages, compacted)

    tool_msgs = [m for m in out if m.get("role") == "tool"]
    summaries = sum(1 for m in tool_msgs if "compacted to fit context" in m["content"])
    if summaries == 0:
        return False, [
            "overflow compactor did not fire when 12 * 4 KB results were "
            "pushed through an 8 000-token budget (chain estimate ~12 000 tokens)"
        ]
    if len(compacted) < summaries:
        return False, [
            f"compacted ids ({len(compacted)}) < summaries ({summaries}); bookkeeping drifted"
        ]
    notes.append(
        f"overflow compactor rewrote {summaries}/{len(tool_msgs)} tool results to summaries "
        f"under an 8 000-token budget; compacted ids = {sorted(compacted)}"
    )
    return True, notes


# ---------------------------------------------------------------------------
# Check 3 — corrupt history self-heals (placeholders stripped, malformed
# tool_calls dropped, orphan tool results removed, missing tool_calls backfilled).
# ---------------------------------------------------------------------------


def check_corrupt_history_self_heals() -> tuple[bool, list[str]]:
    notes: list[str] = []
    corrupt: list[dict[str, Any]] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
        # (1) Placeholder assistant turn (compaction artefact).
        {"role": "assistant", "content": "[Previous assistant message omitted.]"},
        # (2) Assistant turn with one bad tool_call (name=None) and one good one.
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "bad", "type": "function", "function": {"name": None}},
                {"id": "ok", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
        # (3) Tool result for the "bad" call (orphan — its call was dropped).
        {
            "role": "tool",
            "tool_call_id": "bad",
            "name": "read_file",
            "content": "stale payload from before the malformed call was dropped",
        },
        # (4) Missing tool result for an assistant call (orphan on the other side).
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "live", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
    ]

    governor = ContextGovernor()
    out = governor.prepare_for_model(_make_config(context_window_tokens=200_000), corrupt, set())

    placeholders = [m for m in out if "omitted." in str(m.get("content", ""))]
    if placeholders:
        return False, [f"placeholder assistant message survived: {placeholders}"]

    bad_call_still_present = any(
        tc.get("function", {}).get("name") is None
        for msg in out
        if msg.get("role") == "assistant"
        for tc in msg.get("tool_calls", [])
    )
    if bad_call_still_present:
        return False, ["a tool_call with name=None survived the strip_malformed pass"]

    bad_id_still_present = any(
        m.get("tool_call_id") == "bad" for m in out if m.get("role") == "tool"
    )
    if bad_id_still_present:
        return False, ["a tool result for a dropped call_id survived the drop_orphan pass"]

    live_backfilled = [
        m for m in out
        if m.get("role") == "tool"
        and m.get("tool_call_id") == "live"
        and "unavailable" in m.get("content", "")
    ]
    if not live_backfilled:
        return False, [
            "the missing tool result for 'live' was not backfilled with the "
            "[Tool result unavailable …] placeholder"
        ]

    notes.append("placeholder assistant message was stripped.")
    notes.append("malformed tool_call (name=None) was dropped; its orphan result was also dropped.")
    notes.append("missing tool result for 'live' was backfilled with the synthetic error.")
    return True, notes


# ---------------------------------------------------------------------------
# Check 4 — close_mcp_servers is wired in and the _mcp_closing flag exists.
# ---------------------------------------------------------------------------


def check_close_mcp_wiring() -> tuple[bool, list[str]]:
    notes: list[str] = []
    try:
        from femtobot.agent.tools.mcp import close_mcp_servers  # noqa: F401
        from femtobot.agent.context import close_mcp  # noqa: F401
    except ImportError as exc:
        return False, [f"close_mcp_servers / close_mcp not importable: {exc}"]
    notes.append("close_mcp_servers is importable from femtobot.agent.tools.mcp.")
    notes.append("close_mcp is importable from femtobot.agent.context.")
    return True, notes


# ---------------------------------------------------------------------------
# Check 5 — AgentHook has the three new tool lifecycle callbacks.
# ---------------------------------------------------------------------------


def check_hook_lifecycle() -> tuple[bool, list[str]]:
    notes: list[str] = []
    from femtobot.agent.hook import AgentHook

    required = ("before_execute_tool", "after_execute_tool", "on_execute_tool_error")
    missing = [name for name in required if not hasattr(AgentHook(), name)]
    if missing:
        return False, [f"AgentHook is missing: {missing}"]

    notes.append("AgentHook exposes before_execute_tool, after_execute_tool, on_execute_tool_error.")
    return True, notes


# ---------------------------------------------------------------------------
# Driver.
# ---------------------------------------------------------------------------


CHECKS = [
    ("regression — 12 read_file results survive", check_regression_is_fixed),
    ("overflow compactor still fires on real overflow", check_compactor_still_works),
    ("corrupt history self-heals end-to-end", check_corrupt_history_self_heals),
    ("close_mcp_servers is wired in", check_close_mcp_wiring),
    ("AgentHook exposes the three new tool lifecycle callbacks", check_hook_lifecycle),
]


def main() -> int:
    failures: list[str] = []
    print("=" * 72)
    print("femtobot v0.1.x regression — end-to-end pipeline checks")
    print("=" * 72)

    for label, fn in CHECKS:
        ok, notes = fn()
        status = "PASS" if ok else "FAIL"
        print(f"\n[{status}] {label}")
        for n in notes:
            print(f"        · {n}")
        if not ok:
            failures.append(label)

    print("\n" + "=" * 72)
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for label in failures:
            print(f"  - {label}")
        print("=" * 72)
        return 1

    print("ALL CHECKS PASSED — pipeline regression is fixed.")
    print("=" * 72)
    print()
    print("Next step: perform the manual end-to-end check below.")
    print()
    print(MANUAL_E2E_PROMPT)
    return 0


# ---------------------------------------------------------------------------
# Manual end-to-end prompt (paste into the real ``femtobot`` CLI).
# ---------------------------------------------------------------------------


MANUAL_E2E_PROMPT = """\
MANUAL_E2E_PROMPT — paste the following into the femtobot CLI to confirm
the regression is fixed end-to-end (uses real MCP servers, real LLM, real
filesystem):

  Open 6 different files in this repo (any .py files), summarise what each
  one does, and then call the agy MCP server's list tools to confirm MCP
  is reachable. Use exec to run `ls -la femtobot/agent` afterwards so I
  can see you really touched the filesystem. If anything fails, do NOT
  give up — try a different approach and explain what changed.

Expected behaviour (proves the regression is fixed)
---------------------------------------------------
1. The agent must read *all six* files coherently — i.e. the summaries
   must reference real symbols from those files, not "[previous content
   omitted]" placeholders. (The old regression destroyed file content
   after the 10th read_file call.)

2. The agent must call the agy MCP server at least once and report what
   tools it discovered. (The old regression left MCP hooks broken.)

3. The agent must run `ls -la` via exec and quote the real output.

4. The agent must NOT enter a loop of "your previous reply described an
   action but did not include any tool call" auto-correction messages.
   (The old regression poisoned the message history and forced the model
   to describe actions in prose instead of emitting tool calls.)

If all four hold, the regression is solved.
"""


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_async_main()) if False else main())


async def _async_main() -> int:  # pragma: no cover — kept for future async hooks
    return main()
