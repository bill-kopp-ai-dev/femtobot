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

    # Strip block + inline comments and docstrings to avoid
    # false positives where the attribute name is mentioned only
    # in prose.
    code_lines = [
        line
        for line in src.splitlines()
        if not line.lstrip().startswith(("#", '"', "'"))
    ]
    code = "\n".join(code_lines)

    # The exact problematic pattern: ``renderer.input_prompt_markup``
    # followed by no fallback. Allowed forms include:
    #   - ``getattr(renderer, "input_prompt_markup", ...)``
    #   - comments (already stripped)
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

    This pins the structural difference between the deleted
    parity variant and the mirror. If a future nanobot release
    adds these attributes, the test still passes (because
    ``getattr(..., None)`` is permissive). But the test ensures
    we don't silently re-bloat the mirror.
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
