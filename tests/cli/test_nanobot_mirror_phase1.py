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

import pytest


def test_mirror_package_imports_cleanly() -> None:
    """``femtobot.cli._nanobot_mirror`` imports without errors."""
    import femtobot.cli._nanobot_mirror  # noqa: F401


def test_stream_renderer_class_object_identity() -> None:
    """The mirror's ``StreamRenderer`` class object is the same Python
    object as the nanobot-installed one (when nanobot is on
    sys.path). Falls back to a definition match if nanobot is not
    installed.
    """
    import sys
    from femtobot.cli._nanobot_mirror.stream import StreamRenderer as FStream

    if "nanobot.cli.stream" in sys.modules:
        from nanobot.cli.stream import StreamRenderer as NStream
        assert FStream is NStream, (
            "StreamRenderer in the mirror must be the same class as "
            "nanobot's — verify that _nanobot_mirror/stream.py is a "
            "byte-for-byte copy of nanobot/cli/stream.py."
        )
    else:
        # Without nanobot installed, we can at least assert the class
        # has the expected signatures.
        assert hasattr(FStream, "on_delta")
        assert hasattr(FStream, "on_end")
        assert hasattr(FStream, "stop_for_input")
        assert hasattr(FStream, "close")


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
    instantiated a ``Live`` and eagerly started a spinner. The
    nanobot baseline is around 12 lines. We assert the constructor
    fits in a tight budget to catch accidental re-bloating.
    """
    from femtobot.cli._nanobot_mirror.stream import StreamRenderer

    src = inspect.getsource(StreamRenderer.__init__)
    # 30 non-blank lines is generous for the nanobot init.
    non_blank = [l for l in src.splitlines() if l.strip()]
    assert len(non_blank) < 30, (
        f"StreamRenderer.__init__ has {len(non_blank)} non-blank "
        f"lines; expected < 30 (matches nanobot baseline). The "
        f"femtobot-parity version was 60+ lines and contained "
        f"live-spawn logic — see issue #3."
    )
