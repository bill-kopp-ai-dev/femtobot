"""Regression guards for the parity-only ``input_prompt_markup`` /
``input_toolbar_markup`` attributes that were not carried over to
the nanobot mirror's ``StreamRenderer``.

Bug surfaced on 2026-07-20: a real ``femtobot agent`` REPL session
raised ``AttributeError: 'StreamRenderer' object has no attribute
'input_prompt_markup'`` immediately after the user submitted the
first prompt, crashing the REPL.

Root cause: ``_read_interactive_input_async`` in
``femtobot/cli/commands.py`` read the prompt + toolbar markup via
direct attribute access (``renderer.input_prompt_markup`` and
``renderer.input_toolbar_markup``). Those attributes were only
defined on the deleted ``ParityStreamRenderer``; the mirror's
``StreamRenderer`` (from ``nanobot/cli/stream.py``) does not
implement them. Direct attribute access raised AttributeError the
moment the user typed into the prompt.

Fix: read via ``getattr(..., None)`` with safe fallbacks to the
legacy ``You:`` HTML markup and ``None`` toolbar.

Companion fix for bug surfaced in the same audit:
``_print_agent_response`` was called synchronously inside the
consumer task and the REPL loop, racing the prompt_toolkit
renderer. Both call sites now go through
``_print_agent_response_in_terminal``, which wraps the write in
``prompt_toolkit.application.run_in_terminal`` so the prompt is
paused before the body is printed.

The mirror's ``StreamRenderer.on_end`` had the same issue: it
wrote the streamed body directly to ``sys.stdout``. Direct
``sys.stdout.write`` inside an asyncio task running concurrently
with prompt_toolkit's input loop produces a race where the body
text gets echoed back into the input queue. The mirror now
prefers ``run_in_terminal`` (with a ``sys.stdout.write`` fallback
for non-prompt-toolkit contexts).
"""

from __future__ import annotations

import re
from pathlib import Path


FEMTOBOT_DIR = "/home/bill/Codes/mcp-servers-percival/femtobot"


def test_commands_py_does_not_direct_access_input_prompt_markup() -> None:
    """``commands.py`` must NOT directly read ``renderer.input_prompt_markup``.

    The previous direct-access pattern raises ``AttributeError``
    at runtime because the mirror's ``StreamRenderer`` does not
    implement that attribute. The fix uses ``getattr(renderer,
    'input_prompt_markup', None)`` with a fallback to the legacy
    ``You:`` markup. We assert the structural shape of the fix by
    forbidding the bare-attribute form in the source.
    """
    src_path = Path(FEMTOBOT_DIR) / "femtobot/cli/commands.py"
    src = src_path.read_text(encoding="utf-8")

    code_lines = [
        line
        for line in src.splitlines()
        if not line.lstrip().startswith(("#", '"', "'"))
    ]
    code = "\n".join(code_lines)

    bare_match = re.search(
        r"\brenderer\.input_prompt_markup\b(?!\s*[\),:])",
        code,
    )
    assert not bare_match, (
        "commands.py has a direct ``renderer.input_prompt_markup`` "
        "attribute access. The mirror's StreamRenderer does NOT "
        "implement this attribute (parity-only). Use "
        "``getattr(renderer, 'input_prompt_markup', None)`` with "
        "a fallback to the legacy ``You:`` markup instead.\n"
        f"Found at: {bare_match.group()!r}"
    )


def test_commands_py_does_not_direct_access_input_toolbar_markup() -> None:
    """Same regression guard for ``input_toolbar_markup``."""
    src_path = Path(FEMTOBOT_DIR) / "femtobot/cli/commands.py"
    src = src_path.read_text(encoding="utf-8")

    code_lines = [
        line
        for line in src.splitlines()
        if not line.lstrip().startswith(("#", '"', "'"))
    ]
    code = "\n".join(code_lines)

    bare_match = re.search(
        r"\brenderer\.input_toolbar_markup\b(?!\s*[\),:])",
        code,
    )
    assert not bare_match, (
        "commands.py has a direct ``renderer.input_toolbar_markup`` "
        "attribute access. Use ``getattr(renderer, "
        "'input_toolbar_markup', None)`` with a ``None`` toolbar "
        "fallback instead."
    )


def test_mirror_stream_renderer_does_not_implement_input_prompt_markup() -> (
    None
):
    """The mirror's ``StreamRenderer`` does NOT have these parity-only attrs.

    Pins the structural difference between the deleted parity
    variant and the mirror. If a future nanobot release adds these
    attributes, the test still passes (because
    ``getattr(..., None)`` is permissive). The test ensures we
    don't silently re-bloat the mirror.
    """
    from femtobot.cli._nanobot_mirror.stream import StreamRenderer

    assert not hasattr(StreamRenderer, "input_prompt_markup"), (
        "The mirror's StreamRenderer should NOT have "
        "'input_prompt_markup' (parity-only attribute)."
    )
    assert not hasattr(StreamRenderer, "input_toolbar_markup"), (
        "The mirror's StreamRenderer should NOT have "
        "'input_toolbar_markup' (parity-only attribute)."
    )


def test_commands_py_uses_getattr_with_default_for_prompt_markup() -> None:
    """Verify the fix shape: ``getattr(renderer, 'input_prompt_markup', ...)``.

    After the bug #30 fix, the call site reads the attribute via
    ``getattr(renderer, 'input_prompt_markup', None)`` and falls
    back to the legacy markup on ``None``.
    """
    src_path = Path(FEMTOBOT_DIR) / "femtobot/cli/commands.py"
    src = src_path.read_text(encoding="utf-8")

    assert 'getattr(renderer, "input_prompt_markup"' in src or (
        "getattr(renderer, 'input_prompt_markup'" in src
    ), (
        "commands.py must read input_prompt_markup via getattr "
        "with a default fallback. The direct attribute access is "
        "what caused the AttributeError in the 2026-07-20 REPL "
        "session."
    )


def test_print_agent_response_has_async_in_terminal_variant() -> None:
    """Bug surfaced 2026-07-20: sync ``_print_agent_response`` raced
    prompt_toolkit's input loop, causing the body text to be echoed
    back into the input queue (the user observed the previous
    turn's body pasted into the next ``You:`` prompt).

    The fix added ``_print_agent_response_in_terminal`` which wraps
    the write in ``prompt_toolkit.application.run_in_terminal`` so
    the prompt is paused before the body is printed. Both REPL-time
    call sites (consumer task and REPL loop body renderer) must use
    the in-terminal form, NOT the sync form.
    """
    src_path = Path(FEMTOBOT_DIR) / "femtobot/cli/commands.py"
    src = src_path.read_text(encoding="utf-8")

    # The async variant must exist.
    assert (
        "async def _print_agent_response_in_terminal" in src
    ), (
        "commands.py must define ``_print_agent_response_in_terminal`` "
        "(added in 0.1.0-cli.1 audit fixes to fix the body-into-prompt "
        "echo race)."
    )

    # The async variant must use ``run_in_terminal``.
    assert "run_in_terminal" in src, (
        "commands.py's async print function must use "
        "prompt_toolkit.application.run_in_terminal to defer the "
        "write until the prompt is paused."
    )

    # The two REPL-time call sites must NOT use the sync form.
    # Strip comments first.
    code_lines = [
        line
        for line in src.splitlines()
        if not line.lstrip().startswith(("#", '"', "'"))
    ]
    code = "\n".join(code_lines)

    # Within ``_consume_outbound`` and the REPL loop body render
    # branch, we should see ``await _print_agent_response_in_terminal``.
    assert code.count("await _print_agent_response_in_terminal") >= 2, (
        "Both REPL-time call sites must use the async in-terminal "
        "variant (await _print_agent_response_in_terminal). Found "
        f"{code.count('await _print_agent_response_in_terminal')} "
        "call sites; expected at least 2 (consumer background "
        "notifications + REPL loop body renderer)."
    )


def test_mirror_on_end_prefers_run_in_terminal_over_direct_write() -> None:
    """The mirror's ``StreamRenderer.on_end`` must prefer
    ``run_in_terminal`` over the original direct ``sys.stdout.write``.

    The audit in commit 9b1f... patched ``on_end`` because the
    nanobot baseline's direct ``sys.stdout.write`` raced the
    prompt_toolkit input loop during active REPL sessions, producing
    a self-feeding loop where the body text was echoed back into
    the input queue.
    """
    mirror_path = (
        Path(FEMTOBOT_DIR) / "femtobot/cli/_nanobot_mirror/stream.py"
    )
    mirror_src = mirror_path.read_text(encoding="utf-8")

    def strip_comments(src: str) -> str:
        out: list[str] = []
        for line in src.splitlines():
            if line.lstrip().startswith("#"):
                continue
            out.append(line)
        return "\n".join(out)

    def extract_method_body(src: str, signature: str) -> str:
        idx = src.find(signature)
        if idx == -1:
            return ""
        lines = src[idx:].splitlines(keepends=True)
        out: list[str] = [lines[0]]
        for line in lines[1:]:
            if (
                line.startswith("    def ")
                or line.startswith("    async def ")
            ):
                break
            out.append(line)
        return "".join(out)

    on_end = strip_comments(extract_method_body(mirror_src, "async def on_end"))
    assert "run_in_terminal" in on_end, (
        "Mirror's StreamRenderer.on_end must prefer "
        "prompt_toolkit.application.run_in_terminal over the direct "
        "sys.stdout.write that the nanobot baseline uses. See bug #30 "
        "in the 2026-07-20 audit fixes."
    )
