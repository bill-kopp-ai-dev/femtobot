"""Runtime-specific helper functions and constants."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger

from femtobot.utils.helpers import stringify_text_blocks

_MAX_REPEAT_EXTERNAL_LOOKUPS = 2

# Third same-target workspace violation in a turn escalates to "stop retrying".
_MAX_REPEAT_WORKSPACE_VIOLATIONS = 2

EMPTY_FINAL_RESPONSE_MESSAGE = (
    "I completed the tool steps but couldn't produce a final answer. "
    "Please try again or narrow the task."
)

FINALIZATION_RETRY_PROMPT = (
    "Please provide your response to the user based on the conversation above."
)

LENGTH_RECOVERY_PROMPT = (
    "Output limit reached. Continue exactly where you left off "
    "— no recap, no apology. Break remaining work into smaller steps if needed."
)

SUSTAINED_GOAL_CONTINUE_PROMPT = (
    "You have an active sustained goal. Please continue working toward the "
    "objective using your tools, or call complete_goal if the work is truly finished."
)

# L1 (v0.1.7): guard against "intent_only" final responses — turns where the
# LLM narrates an upcoming tool action in prose but does not actually emit a
# tool_call.  Without this guard the runner terminates the iteration on the
# first turn, treating the prose as the final answer; the user then sees the
# model promise work that was never executed (the "Despachando agora em
# paralelo..." pathology observed in v0.1.6 debug sessions).
#
# Heuristic: a response is flagged as intent_only when *all* of:
#   * no tool_calls were executed in this turn;
#   * the cleaned content describes a future/ongoing action (verb pattern);
#   * there are no concrete markers of completed work (tool results, file
#     edits, citations, code blocks, or backtick-quoted identifiers).
#
# Conservative on purpose — false positives (overriding a real answer) hurt
# less than false negatives (letting the agent claim "I'm dispatching"
# forever).  See tests/test_runner_intent_only.py for the boundary cases.
_INTENT_VERB_PATTERNS: tuple[str, ...] = (
    # Portuguese (BR) — observed in production logs.
    r"\b(?:vou|vamos|estou|estamos|pretendo|pretendemos|irei|iremos|"
    r"despachando|despacharei|despacharemos|despachar|despachei|"
    r"executando|executarei|executar|"
    r"preparando|prepararei|preparar|"
    r"enviando|enviarei|emitindo|emitirei|"
    r"rodando|rodarei|rodar|"
    r"iniciando|iniciarei|iniciar|"
    r"come[çc]ando|come[çc]arei|come[çc]ar|"
    r"analisando|analisarei|analisar|"
    r"levantando|levantarei|levantar|levantado|"
    r"trazendo|trago|trarei|"
    r"polindo|polirei|polir|"
    r"consolidando|consolidarei|consolidar|"
    r"lendo|lerei|ler|"
    r"gerando|gerarei|gerar|"
    r"reproduzindo|reproduzirei|reproduzir|"
    r"cruzar|cruzando|cruzarei|"
    r"termino|terminarei|terminar)\b",
    # Past + future compound tenses observed in production logs.
    r"\b(?:ia\s+despachar|ia\s+executar|ia\s+chamar|"
    r"vou\s+emitir|ia\s+emitir|"
    r"disse\s+que\s+ia|"
    r"pensei\s+em\s+despachar|pensei\s+em\s+executar)\b",
    # English — generic dispatch / execute verbs in 1st person.
    r"\b(?:i'?ll|i\s+will|i'?m\s+going\s+to|i\s+am\s+going\s+to|"
    r"let\s+me|i'?m\s+dispatching|i'?m\s+running|i'?m\s+executing|"
    r"i'?m\s+preparing|i'?m\s+starting|i'?m\s+kicking\s+off|"
    r"dispatching|running|executing|preparing|kicking\s+off|"
    r"spinning\s+up|will\s+dispatch|will\s+run|will\s+execute)\b",
)
_INTENT_VERB_RE = re.compile(
    "|".join(_INTENT_VERB_PATTERNS),
    re.IGNORECASE | re.UNICODE,
)

# Markers that strongly indicate the response *did* something concrete.
# These alone do NOT short-circuit the intent_only guard anymore (L3):
# the model often replies with prose that *mentions* a path or a tool name
# while still being a "describe-but-don't-execute" answer.  We classify a
# response as intent_only whenever an intent verb is present, unless the
# content is overwhelmingly dominated by concrete result markers (see
# ``_STRONG_RESULT_RATIO`` below).
_CONCRETE_RESULT_MARKERS: tuple[str, ...] = (
    "```",          # fenced code block
    "`",            # inline code / file path / identifier
    "://",          # URL-ish (e.g. file://, https://)
    ".md:",         # markdown line ref
    ".py:",         # python line ref
    "[Tool result", # injected tool result prefix
    "tool_call_id",
    "function_call",
)

# Strong-result markers (tool-result blocks, function_call JSON) are
# unambiguous proof that the model produced a real artifact.  These still
# short-circuit the guard at any density.
_STRONG_RESULT_MARKERS: tuple[str, ...] = (
    "[Tool result",
    "tool_call_id",
    "function_call",
)

# Phrases that mean the model already finished describing what it *will*
# do and is explicitly closing the turn.  These legitimately end the loop
# even when an intent verb slipped in.  Common in "Pong" / "ok" responses.
_FINAL_FAREWELL_PATTERNS: tuple[str, ...] = (
    # Plain acknowledgments / farewells / ping-pong.  These are full-line
    # responses — anything longer than this is treated as narration.
    r"^\s*(?:pong|ok|entendido|combinado|certinho|pronto|beleza|"
    r"show|blz|fechou|fechado|tranquilo|confirmado|recebido|"
    r"anotado|registrado|sim|não|nao)\s*[\.\!\?]*\s*$",
)


def _concrete_chars(content: str) -> int:
    r"""DEPRECATED: replaced by simpler ``\`\`\`\` count check in L3.

    Kept for backward compatibility with any callers importing it.
    Returns the total character count of the response — no longer
    computes the in-marker ratio.  Use ``content.count("```")`` directly
    for the new check.
    """
    return len(content)


def is_intent_only_response(content: str | None) -> bool:
    """Return True when *content* looks like a self-reported future action.

    Used by the agent runner to break the "describe-but-don't-execute" loop
    where the LLM answers with prose like "Despachando em paralelo…" without
    emitting a corresponding ``tool_calls`` payload.

    L3 (v0.1.8): the heuristic no longer short-circuits as soon as a
    concrete marker appears.  Real-world runs (see
    ``tests/test_runner_intent_only_l3.py``) showed the model replying
    with prose that *mentions* a path or tool name while still being a
    pure description — e.g. "Plano: 1. read_file em
    ``/path/file.md``.  Emitindo agora."  The guard must catch those
    cases.

    L4 (longlogs.txt analysis, 2026-07-15): the heuristic was
    asymmetric — the farewell allow-list short-circuited the entire
    intent-verb check, so a response that *both* quoted an intent verb
    inside a string ("meu 'Vou te dar 2 boas opções'…") *and* ended
    with a farewell ("Pronto.") was accepted as final.  That made the
    runner miss the describe-but-don't-execute pathology and triggered
    the cascading "Falso-positivo de novo" follow-up turns.  We now
    treat intent verbs as the primary signal and only let a farewell
    short-circuit the guard when the response is *entirely* a farewell
    (no other content, no embedded quoted intent verbs).

    Short-circuit happens when:

    1. The content contains a *strong* marker (``[Tool result``,
       ``tool_call_id``, ``function_call``) — unambiguous proof of a
       real tool artifact.
    2. The content is a *fenced code block* of substantial size — the
       dominant content is real code, not narration with sprinkled
       backticks.
    3. The content is *entirely* a pure acknowledgment (whole-string
       match against the farewell regex) — there is no narration of
       intent and no substantive body.

    Anything else with an intent verb is flagged.
    """
    if not content or not content.strip():
        return False

    # (1) Strong markers short-circuit unconditionally.
    for marker in _STRONG_RESULT_MARKERS:
        if marker in content:
            return False

    # (2) Substantial fenced code block — when ``\`\`\`\` appears more
    # than once (open + close), the response is dominated by a real
    # artifact.  Mentions of intent verbs inside the code body are not
    # narrating an action; they're just identifiers.
    triple_backtick_count = content.count("```")
    if triple_backtick_count >= 2:
        return False

    # No intent verb → not intent_only. We check this *before* the
    # farewell allow-list so a neutral response (no narration, no
    # tool calls) is correctly classified.
    if not _INTENT_VERB_RE.search(content):
        return False

    # (3) Final farewells short-circuit ONLY when the entire content is
    # a pure acknowledgment — not when a farewell is appended to a
    # longer narration.  Without this guard the runner was tricked by
    # responses like "Falso-positivo de novo. ... Pronto." into
    # accepting them as terminal, which then leaked into the next turn
    # and triggered the intent-only retry loop ("Falso-positivo de novo"
    # repeated 3× in longlogs.txt).
    stripped = content.strip()
    for pattern in _FINAL_FAREWELL_PATTERNS:
        if re.fullmatch(pattern, stripped, flags=re.IGNORECASE | re.UNICODE):
            return False

    return True


INTENT_ONLY_FEEDBACK_PROMPT = (
    "Your previous reply described an action ('{verb}…') but did not include "
    "any tool call. To actually execute that action you must emit the "
    "corresponding tool call (e.g. agy_run_task, claude_run_task, read_file, "
    "exec, etc.) in this turn. If you have already finished the task and "
    "this was a recap of work already done, answer with a concrete result "
    "instead — show file paths, line ranges, or output snippets so the user "
    "can verify the work was performed."
)

# Cap on intent-only retries. After this many consecutive intent-only
# responses we stop pushing back and accept the model's text as final — by
# then it's clearly not going to call a tool and further nudging would just
# burn iteration budget.
_MAX_INTENT_RETRIES = 2


def build_intent_only_feedback_message(verb_match: str | None = None) -> dict[str, str]:
    """Build the user-role nudge that asks the LLM to actually emit a tool call."""
    verb_hint = (verb_match or "").strip().rstrip(".…")
    content = INTENT_ONLY_FEEDBACK_PROMPT
    if verb_hint:
        content = content.replace("{verb}", verb_hint)
    else:
        content = content.replace("{verb}", "despachando/executando")
    return {"role": "user", "content": content}


def empty_tool_result_message(tool_name: str) -> str:
    """Short prompt-safe marker for tools that completed without visible output."""
    return f"({tool_name} completed with no output)"


def ensure_nonempty_tool_result(tool_name: str, content: Any) -> Any:
    """Replace semantically empty tool results with a short marker string."""
    if content is None:
        return empty_tool_result_message(tool_name)
    if isinstance(content, str) and not content.strip():
        return empty_tool_result_message(tool_name)
    if isinstance(content, list):
        if not content:
            return empty_tool_result_message(tool_name)
        text_payload = stringify_text_blocks(content)
        if text_payload is not None and not text_payload.strip():
            return empty_tool_result_message(tool_name)
    return content


def is_blank_text(content: str | None) -> bool:
    """True when *content* is missing or only whitespace."""
    return content is None or not content.strip()


def build_finalization_retry_message() -> dict[str, str]:
    """A short no-tools-allowed prompt for final answer recovery."""
    return {"role": "user", "content": FINALIZATION_RETRY_PROMPT}


def build_length_recovery_message() -> dict[str, str]:
    """Prompt the model to continue after hitting output token limit."""
    return {"role": "user", "content": LENGTH_RECOVERY_PROMPT}


def build_goal_continue_message(custom: str | None = None) -> dict[str, str]:
    """Prompt the model to continue when a sustained goal is still active."""
    return {"role": "user", "content": custom or SUSTAINED_GOAL_CONTINUE_PROMPT}


def external_lookup_signature(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Stable signature for repeated external lookups we want to throttle."""
    if tool_name == "web_fetch":
        url = str(arguments.get("url") or "").strip()
        if url:
            return f"web_fetch:{url.lower()}"
    if tool_name == "web_search":
        query = str(arguments.get("query") or arguments.get("search_term") or "").strip()
        if query:
            return f"web_search:{query.lower()}"
    return None


def repeated_external_lookup_error(
    tool_name: str,
    arguments: dict[str, Any],
    seen_counts: dict[str, int],
) -> str | None:
    """Block repeated external lookups after a small retry budget."""
    signature = external_lookup_signature(tool_name, arguments)
    if signature is None:
        return None
    count = seen_counts.get(signature, 0) + 1
    seen_counts[signature] = count
    if count <= _MAX_REPEAT_EXTERNAL_LOOKUPS:
        return None
    logger.warning(
        "Blocking repeated external lookup {} on attempt {}",
        signature[:160],
        count,
    )
    return (
        "Error: repeated external lookup blocked. "
        "Use the results you already have to answer, or try a meaningfully different source."
    )


# Workspace-boundary violations are soft errors, with per-target throttling.

_OUTSIDE_PATH_PATTERN = re.compile(r"(?:^|[\s|>'\"])((?:/[^\s\"'>;|<]+)|(?:~[^\s\"'>;|<]+))")


def workspace_violation_signature(
    tool_name: str,
    arguments: dict[str, Any],
) -> str | None:
    """Return a stable cross-tool signature for the outside-workspace target."""
    for key in ("path", "file_path", "target", "source", "destination"):
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return _normalize_violation_target(val.strip())

    if tool_name in {"exec", "shell"}:
        cmd = str(arguments.get("command") or "").strip()
        if cmd:
            match = _OUTSIDE_PATH_PATTERN.search(cmd)
            if match:
                return _normalize_violation_target(match.group(1))
        cwd = str(arguments.get("working_dir") or "").strip()
        if cwd:
            return _normalize_violation_target(cwd)

    return None


def _normalize_violation_target(raw: str) -> str:
    """Normalize *raw* path so that equivalent spellings collide on the same key."""
    try:
        normalized = Path(raw).expanduser().resolve().as_posix()
    except Exception:
        normalized = raw.replace("\\", "/")
    return f"violation:{normalized}".lower()


def repeated_workspace_violation_error(
    tool_name: str,
    arguments: dict[str, Any],
    seen_counts: dict[str, int],
) -> str | None:
    """Return an escalated error after repeated bypass attempts."""
    signature = workspace_violation_signature(tool_name, arguments)
    if signature is None:
        return None
    count = seen_counts.get(signature, 0) + 1
    seen_counts[signature] = count
    if count <= _MAX_REPEAT_WORKSPACE_VIOLATIONS:
        return None
    logger.warning(
        "Escalating repeated workspace bypass attempt {} (attempt {})",
        signature[:160],
        count,
    )
    target = signature.split("violation:", 1)[1] if "violation:" in signature else signature
    return (
        "Error: refusing repeated workspace-bypass attempts.\n"
        f"You have tried to access '{target}' (or an equivalent path) "
        f"{count} times in this turn. This is a hard policy boundary -- "
        "switching tools, shell tricks, working_dir overrides, symlinks, "
        "or base64 piping will NOT change the answer. Stop retrying. "
        "If the user genuinely needs this resource, tell them you cannot "
        "access it and ask how they want to proceed (e.g. copy the file "
        "into the workspace, or disable restrict_to_workspace for this run)."
    )
