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
    """The mirror's stream.py is byte-for-byte equal to nanobot's.

    Any drift here is a regression — the mirror is supposed to be
    a verbatim copy (D1). The two source files are read from
    disk and compared byte-for-byte, independent of whether
    ``nanobot`` is installed in the runtime env.
    """
    from pathlib import Path

    mirror = (
        Path("/home/bill/Codes/mcp-servers-percival/femtobot")
        / "femtobot/cli/_nanobot_mirror/stream.py"
    )
    nanobot = (
        Path("/home/bill/Codes/agents/nanobot/nanobot/cli/stream.py")
    )

    mirror_bytes = mirror.read_bytes()
    nanobot_bytes = nanobot.read_bytes()

    assert mirror_bytes == nanobot_bytes, (
        "_nanobot_mirror/stream.py is not byte-for-byte equal to "
        "nanobot/cli/stream.py. Re-run `cp nanobot/cli/stream.py "
        "femtobot/cli/_nanobot_mirror/stream.py` per the upstream-sync "
        "recipe (PLAN §13)."
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
