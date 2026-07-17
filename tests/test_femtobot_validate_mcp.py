"""Tests for ``_warn_missing_mcp_executables`` (PR 6.1).

Covers:

- stdio server whose absolute command path does not exist → warning.
- stdio server whose bare executable is not on PATH → warning.
- stdio server whose executable IS on PATH → no warning.
- URL-based server (sse / ws / http) → never warned (out of scope).
- Missing ``mcp_servers`` attribute → no warning, no crash.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from femtobot.femtobot import _warn_missing_mcp_executables


def _config(mcp_servers):
    return SimpleNamespace(tools=SimpleNamespace(mcp_servers=mcp_servers))


def test_absolute_command_missing():
    cfg = _config(
        {
            "percival-osm": SimpleNamespace(
                command="/no/such/binary",
                type="stdio",
            )
        }
    )
    # Loguru writes to stderr; ``caplog`` only captures stdlib logging.
    # Capture stderr directly so we can assert the warning text.
    import io
    import sys as _sys

    from loguru import logger as _loguru

    sink = io.StringIO()
    handler_id = _loguru.add(sink, level="WARNING", format="{message}")
    try:
        _warn_missing_mcp_executables(cfg)
    finally:
        _loguru.remove(handler_id)
    text = sink.getvalue()
    assert "percival-osm" in text
    assert "/no/such/binary" in text


def test_bare_executable_missing(monkeypatch):
    cfg = _config(
        {
            "percival-osm": SimpleNamespace(
                command="definitely-not-installed-xyz",
                type="stdio",
            )
        }
    )
    # Force an empty PATH so ``shutil.which`` returns None deterministically.
    monkeypatch.setenv("PATH", "")
    import io

    from loguru import logger as _loguru

    sink = io.StringIO()
    handler_id = _loguru.add(sink, level="WARNING", format="{message}")
    try:
        _warn_missing_mcp_executables(cfg)
    finally:
        _loguru.remove(handler_id)
    text = sink.getvalue()
    assert "percival-osm" in text
    assert "not on PATH" in text


def test_executable_on_path_no_warning():
    # Pick the running Python binary, which is guaranteed to exist.
    binary = sys.executable
    cfg = _config(
        {
            "percival-osm": SimpleNamespace(
                command=binary,
                type="stdio",
            )
        }
    )
    import io

    from loguru import logger as _loguru

    sink = io.StringIO()
    handler_id = _loguru.add(sink, level="WARNING", format="{message}")
    try:
        _warn_missing_mcp_executables(cfg)
    finally:
        _loguru.remove(handler_id)
    assert "percival-osm" not in sink.getvalue()


def test_url_based_server_no_warning():
    cfg = _config(
        {
            "remote": SimpleNamespace(
                command=None,
                url="http://example.com/mcp",
                type="sse",
            )
        }
    )
    import io

    from loguru import logger as _loguru

    sink = io.StringIO()
    handler_id = _loguru.add(sink, level="WARNING", format="{message}")
    try:
        _warn_missing_mcp_executables(cfg)
    finally:
        _loguru.remove(handler_id)
    assert "remote" not in sink.getvalue()


def test_no_mcp_servers_attribute_no_crash():
    cfg = SimpleNamespace()  # no .tools
    # Should not raise.
    _warn_missing_mcp_executables(cfg)
