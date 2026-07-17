"""Tool-use guard hook (PR 5.3 of the longlogs remediation plan).

Detects the pattern from ``longlogs.txt`` (2026-07-15 19:47 turn): the
user asked the agent to execute something, but the agent answered with a
plan / enumeration of options instead of calling any tool — even when a
local tool such as ``exec`` or ``read_file`` is clearly available.

The hook is **opt-in** (``agents.defaults.tool_use_guard.enabled=False``
by default to preserve backward compatibility) and injects a soft
"internal nudge" into the LLM messages when the bad pattern is observed.
The nudge asks the model to either call a tool now or explain concretely
why it cannot (missing tool, missing credentials, blocking policy) — but
it does NOT itself emit any tool call. The agent decides.
"""

from __future__ import annotations

import re
from typing import Any

from femtobot.agent.hook import AgentHook, AgentHookContext


# Action verbs in the user's message that indicate the user is asking
# the agent to actually *do* something. The list is intentionally
# narrow: false positives are worse than false negatives because the
# nudge adds tokens and may confuse the agent.
_USER_ACTION_KEYWORDS = (
    r"\btest",
    r"\brun",
    r"\brode\b",  # Portuguese imperative
    r"\bexecute",
    r"\bcall\b",
    r"\binvoke",
    r"\btrigger",
    r"\bperform",
    r"\bstart\b",
    r"\bopen\b",
    r"\bsend\b",
)

_USER_ACTION_RE = re.compile("|".join(_USER_ACTION_KEYWORDS), re.IGNORECASE)

# Phrases the agent tends to use when it is about to emit a "plan" /
# "options" answer instead of taking action.
_PLANNING_MARKERS = (
    r"vou (fazer|emitir|começar|tentar)",
    r"here'?s how",
    r"you can (either|choose)",
    r"você pode (escolher|optar)",
    r"qual (caminho|opção) prefere",
    r"plano:\s*\n",
    r"option \d",
    r"opção \d",
)
_PLANNING_MARKERS_RE = re.compile("|".join(_PLANNING_MARKERS), re.IGNORECASE)


_NUDGE_TEMPLATE = (
    "Internal nudge: the user asked you to execute something "
    "({user_keywords}), but no tool was called this turn. Either "
    "invoke a tool now (e.g. `exec` for shell commands, "
    "`read_file` / `grep` for local inspection) or state concretely "
    "why you cannot (missing tool, missing credentials, blocking "
    "policy). Do not respond with a plan or enumeration of options — "
    "those are exactly what was already failing."
)


class ToolUseGuardHook(AgentHook):
    """Inject a nudge into the LLM when a turn ends with no tool call.

    The hook fires on ``after_iteration``. It looks at the most recent
    user message and the final agent content, and decides whether the
    "asked-to-execute, answered-with-plan" pattern from ``longlogs.txt``
    is in play. When it is, it appends a soft system note to the
    messages list — the agent gets one more chance to actually act.

    The hook never raises. Errors are swallowed and logged via the
    parent class.
    """

    def __init__(self, reraise: bool = False) -> None:
        super().__init__(reraise=reraise)
        # Track the last nudge to avoid an infinite loop: if the model
        # still does not call a tool after the nudge, the runner would
        # loop forever without this latch.
        self._nudged_at_iteration: int | None = None

    async def after_iteration(self, context: AgentHookContext) -> None:
        # Only act at the end of a turn (no further tool calls pending).
        if context.tool_calls:
            return
        if context.stop_reason and context.stop_reason != "completed":
            return
        if self._nudged_at_iteration == context.iteration:
            # Already nudged this iteration; do not loop forever.
            return

        user_text = _extract_last_user_text(context.messages)
        if not user_text:
            return
        if not _USER_ACTION_RE.search(user_text):
            return

        final = context.final_content or ""
        if not final:
            return
        # Planning-marker heuristic: detect the agent enumerating options.
        if not _PLANNING_MARKERS_RE.search(final):
            return

        keywords = ", ".join(_USER_ACTION_RE.findall(user_text)[:3]) or "executar"
        context.messages.append(
            {
                "role": "system",
                "content": _NUDGE_TEMPLATE.format(user_keywords=keywords),
            }
        )
        self._nudged_at_iteration = context.iteration


def _extract_last_user_text(messages: list[dict[str, Any]]) -> str | None:
    """Return the most recent user-role message text, or ``None``.

    Skips system and tool messages. Trailing assistant / tool messages
    do not affect the result — we only care about the user's original
    ask.
    """
    for msg in reversed(messages):
        role = msg.get("role")
        if role != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "".join(parts) if parts else None
    return None
