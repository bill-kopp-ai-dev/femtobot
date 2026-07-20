"""Phase 1 smoke tests for the nanobot CLI mirror.

Verifies that the stream.py mirror lands cleanly: the nanobot
verbatim copy is importable, exposes the expected symbols, and the
femtobot.cli module re-exports them under the canonical
``femtobot.cli.stream`` path (D5).

Important property: this file does NOT depend on the `nanobot`
package being installed at runtime. The byte-for-byte comparison
in ``test_mirror_stream_matches_nanobot_source_byte_for_byte``
reads the source files from disk and compares them directly.
"""

from __future__ import annotations

import inspect


def test_mirror_package_imports_cleanly() -> None:
    """``femtobot.cli._nanobot_mirror`` imports without errors."""
    import femtobot.cli._nanobot_mirror  # noqa: F401


def test_mirror_stream_module_exposes_nanobot_apis() -> None:
    """``femtobot.cli._nanobot_mirror.stream`` exposes the same
    public surface as ``nanobot.cli.stream``.

    This is the Phase 1 invariant — the mirror module is usable on
    its own (you can ``from femtobot.cli._nanobot_mirror.stream
    import StreamRenderer`` even if the femtobot.cli re-export has
    not yet been wired).
    """
    from femtobot.cli._nanobot_mirror import stream as mirror_stream_mod

    assert hasattr(mirror_stream_mod, "StreamRenderer")
    assert hasattr(mirror_stream_mod, "ThinkingSpinner")
    assert hasattr(mirror_stream_mod, "_make_console")


def test_mirror_stream_matches_nanobot_source_byte_for_byte() -> None:
    """The mirror's stream.py matches nanobot's verbatim, except for the documented
    ``on_end`` patch.

    The mirror is supposed to be a verbatim copy of
    ``nanobot/cli/stream.py`` (D1). The audit in commit 9b1f... patches
    ``on_end`` to use ``prompt_toolkit.application.run_in_terminal``
    (bug #30 — direct ``sys.stdout.write`` during an active prompt
    session races the renderer and self-feeds the input queue).

    Rather than attempt a brittle regex-based diff, we sample specific
    invariant sections that MUST match byte-for-byte (the ``__init__``,
    ``on_delta``, ``pause_spinner``, ``stop_for_input``, ``close``,
    ``_renderable``, ``_render_str``, ``_start_spinner``, ``_stop_spinner``,
    ``ensure_header`` bodies) and assert that the ``on_end`` body in
    the mirror contains ``run_in_terminal`` (the documented patch).
    """
    from pathlib import Path

    mirror = (
        Path("/home/bill/Codes/mcp-servers-percival/femtobot")
        / "femtobot/cli/_nanobot_mirror/stream.py"
    )
    nanobot = (
        Path("/home/bill/Codes/agents/nanobot/nanobot/cli/stream.py")
    )

    mirror_src = mirror.read_text(encoding="utf-8")
    nanobot_src = nanobot.read_text(encoding="utf-8")

    # Methods that MUST remain verbatim.
    verbatim_methods = [
        "def __init__",
        "async def on_delta",
        "def pause_spinner",
        "def stop_for_input",
        "async def close",
        "def _renderable",
        "def _render_str",
        "def _start_spinner",
        "def _stop_spinner",
        "def ensure_header",
    ]

    def extract_method_body(src: str, signature: str) -> str:
        """Extract the body of ``signature`` from ``src``.

        Returns the substring starting at ``signature`` and ending
        at the next top-level method declaration or end-of-class.
        """
        idx = src.find(signature)
        if idx == -1:
            return ""
        # Walk forward until we hit another ``def `` at the same
        # indentation, or a top-level ``class `` boundary.
        lines = src[idx:].splitlines(keepends=True)
        out: list[str] = [lines[0]]
        for line in lines[1:]:
            stripped = line.strip()
            # Top-level class boundary (``class Foo:``) at column 0
            # is impossible from inside another class — skip.
            # Same-indentation method boundary: ``    def `` or ``    async def ``.
            if (
                line.startswith("    def ")
                or line.startswith("    async def ")
            ):
                break
            out.append(line)
        return "".join(out)

    for sig in verbatim_methods:
        mirror_body = extract_method_body(mirror_src, sig)
        nanobot_body = extract_method_body(nanobot_src, sig)
        assert mirror_body == nanobot_body, (
            f"Method {sig!r} differs between the mirror and nanobot. "
            f"Drift here is a regression — the mirror is supposed to be a "
            f"verbatim copy. Re-run `cp nanobot/cli/stream.py "
            f"femtobot/cli/_nanobot_mirror/stream.py` per the upstream-sync "
            f"recipe (PLAN §13)."
        )

    # Documented exception: ``on_end`` is patched in the mirror.
    # The mirror now uses ``run_in_terminal`` (preferred) with a
    # ``sys.stdout.write`` fallback for non-prompt-toolkit contexts.
    # The nanobot baseline writes directly to sys.stdout. We assert
    # that the patch is in place (run_in_terminal is the primary
    # write path) and that the nanobot baseline has not been patched.
    mirror_on_end = extract_method_body(mirror_src, "async def on_end")
    nanobot_on_end = extract_method_body(nanobot_src, "async def on_end")

    def strip_comments(src: str) -> str:
        """Strip ``#`` line-comments so position checks ignore prose."""
        out_lines: list[str] = []
        for line in src.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            out_lines.append(line)
        return "\n".join(out_lines)

    mirror_on_end_code = strip_comments(mirror_on_end)
    assert "run_in_terminal" in mirror_on_end_code, (
        "Mirror's on_end should use run_in_terminal (audit patch, "
        "see commit 9b1f... / bug #30). The direct sys.stdout.write "
        "from the nanobot baseline raced the prompt_toolkit renderer "
        "and produced a self-feeding loop."
    )
    run_in_terminal_pos = mirror_on_end_code.find("run_in_terminal")
    sys_stdout_pos = mirror_on_end_code.find("sys.stdout.write")
    assert run_in_terminal_pos != -1 and (
        sys_stdout_pos == -1 or run_in_terminal_pos < sys_stdout_pos
    ), (
        "Mirror's on_end must prefer run_in_terminal over the "
        "sys.stdout.write fallback (audit patch)."
    )
    assert "out.write(self._render_str())" in nanobot_on_end, (
        "Sanity check: nanobot's baseline on_end still uses direct "
        "out.write(self._render_str()) (this is the bug we patched). "
        "If this fails, nanobot upstream changed and the patch may "
        "need to be revised."
    )


def test_stream_renderer_constructor_size() -> None:
    """Sanity invariant — the ``StreamRenderer.__init__`` is small.

    The femtobot-parity variant had a 60+ line ``__init__`` that
    eagerly spawned a ``Live`` and a spinner. The nanobot baseline
    is around 17 non-blank lines. We assert the constructor fits
    in a budget tight enough to catch accidental re-bloating (the
    parity version had 60+ lines and embedded the entire spinner
    construction). The threshold (30) is generous enough to
    accommodate 1-2 line upstream growth without flaking.
    """
    from femtobot.cli._nanobot_mirror.stream import StreamRenderer

    src = inspect.getsource(StreamRenderer.__init__)
    non_blank = [l for l in src.splitlines() if l.strip()]
    assert len(non_blank) < 30, (
        f"StreamRenderer.__init__ has {len(non_blank)} non-blank "
        f"lines; expected < 30 (nanobot baseline is ~17). The "
        f"femtobot-parity version was 60+ lines and contained "
        f"live-spawn logic — see issue #3."
    )


def test_femtobot_cli_stream_canonical_re_export() -> None:
    """``femtobot.cli.stream.StreamRenderer`` resolves to the mirror's class.

    D5 says the canonical path must stay stable so all user-facing
    imports (``from femtobot.cli.stream import StreamRenderer``)
    keep working. Verified by ``test_cli_init.py`` for the
    package-level re-export, and here for the ``stream`` module
    specifically.
    """
    from femtobot.cli import stream as femtobot_stream_mod
    from femtobot.cli._nanobot_mirror import stream as mirror_stream_mod

    assert femtobot_stream_mod.StreamRenderer is mirror_stream_mod.StreamRenderer
    assert (
        femtobot_stream_mod.ThinkingSpinner is mirror_stream_mod.ThinkingSpinner
    )
    assert femtobot_stream_mod._make_console is mirror_stream_mod._make_console


def test_mirror_does_not_shadow_femtobot_commands_typer_apps() -> None:
    """``femtobot.cli._nanobot_mirror`` does NOT export Typer sub-apps.

    Regression guard for the bug fixed in this audit round: the
    mirror's ``__init__`` previously re-exported
    ``agent_app``/``sessions_app``/etc. as
    ``_MissingFemtobotFeature`` stubs from ``_adapters``. Code
    importing the mirror and expecting real ``typer.Typer``
    instances silently got a stub. The mirror now exposes only
    the stream layer; the real Typer sub-apps live in
    ``femtobot.cli.commands`` where they are defined.
    """
    import femtobot.cli._nanobot_mirror as mirror

    for name in (
        "agent_app",
        "gateway_app",
        "sessions_app",
        "mcp_app",
        "femtobot_app",
    ):
        assert not hasattr(mirror, name), (
            f"femtobot.cli._nanobot_mirror.{name} must NOT be "
            f"exported — it was a _MissingFemtobotFeature stub and "
            f"silently shadowed the real Typer app defined in "
            f"femtobot.cli.commands."
        )


def test_femtobot_cli_package_exposes_stream_symbols() -> None:
    """``femtobot.cli`` re-exports the stream layer.

    Regression guard for the bug fixed in this audit round:
    ``femtobot/cli/__init__.py`` was empty after Phase 4, so
    ``from femtobot.cli import StreamRenderer`` would raise
    ImportError. The re-export was restored.
    """
    import femtobot.cli as cli_mod

    assert hasattr(cli_mod, "StreamRenderer")
    assert hasattr(cli_mod, "ThinkingSpinner")
    assert hasattr(cli_mod, "_make_console")
