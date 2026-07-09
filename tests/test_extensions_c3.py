"""Extension registry tests (C3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from femtobot.agent.tools.extensions import (
    ExtensionConfig,
    load_extensions,
)

pytestmark = pytest.mark.architecture


def test_load_extensions_returns_empty_when_file_missing(tmp_path: Path) -> None:
    """C3: missing ``extensions.json`` is a clean no-op (C3)."""
    assert load_extensions(tmp_path) == []


def test_load_extensions_parses_cli(tmp_path: Path) -> None:
    """C3: a CLI extension is parsed into :class:`ExtensionConfig` (C3)."""
    (tmp_path / "extensions.json").write_text(
        json.dumps(
            {
                "extensions": {
                    "hello_cli": {
                        "kind": "cli",
                        "command": "echo",
                        "args": ["hello"],
                        "capabilities": ["read-only"],
                    }
                }
            }
        )
    )
    exts = load_extensions(tmp_path)
    assert len(exts) == 1
    ext = exts[0]
    assert ext.name == "hello_cli"
    assert ext.kind == "cli"
    assert ext.command == "echo"
    assert ext.args == ["hello"]
    assert ext.capabilities == ["read-only"]
    assert ext.is_valid()


def test_load_extensions_parses_http(tmp_path: Path) -> None:
    """C3: an HTTP extension is parsed (C3)."""
    (tmp_path / "extensions.json").write_text(
        json.dumps(
            {
                "extensions": {
                    "hello_http": {
                        "kind": "http",
                        "url": "http://127.0.0.1:9999/hook",
                        "capabilities": ["network"],
                    }
                }
            }
        )
    )
    exts = load_extensions(tmp_path)
    assert len(exts) == 1
    assert exts[0].kind == "http"
    assert exts[0].url == "http://127.0.0.1:9999/hook"


def test_load_extensions_skips_invalid_kind(tmp_path: Path) -> None:
    """C3: an unknown kind is rejected (no exception, just skipped) (C3)."""
    (tmp_path / "extensions.json").write_text(
        json.dumps(
            {
                "extensions": {
                    "bad_kind": {"kind": "unsupported"},
                    "good_kind": {"kind": "cli", "command": "true"},
                }
            }
        )
    )
    exts = load_extensions(tmp_path)
    assert [e.name for e in exts] == ["good_kind"]


def test_load_extensions_skips_missing_required_field(tmp_path: Path) -> None:
    """C3: cli without ``command`` is rejected; http without ``url`` is rejected (C3)."""
    (tmp_path / "extensions.json").write_text(
        json.dumps(
            {
                "extensions": {
                    "missing_command": {"kind": "cli"},
                    "missing_url": {"kind": "http"},
                    "valid_cli": {"kind": "cli", "command": "ls"},
                }
            }
        )
    )
    exts = load_extensions(tmp_path)
    assert [e.name for e in exts] == ["valid_cli"]


def test_load_extensions_invalid_json_returns_empty(tmp_path: Path) -> None:
    """C3: malformed JSON returns [] (no crash) (C3)."""
    (tmp_path / "extensions.json").write_text("{not json", encoding="utf-8")
    assert load_extensions(tmp_path) == []


def test_load_extensions_top_level_not_object(tmp_path: Path) -> None:
    """C3: top-level array returns [] (C3)."""
    (tmp_path / "extensions.json").write_text(json.dumps([1, 2, 3]))
    assert load_extensions(tmp_path) == []


def test_load_extensions_sorted_output(tmp_path: Path) -> None:
    """C3: result list is sorted by name (C3)."""
    (tmp_path / "extensions.json").write_text(
        json.dumps(
            {
                "extensions": {
                    "zulu": {"kind": "cli", "command": "true"},
                    "alpha": {"kind": "cli", "command": "true"},
                    "mike": {"kind": "cli", "command": "true"},
                }
            }
        )
    )
    exts = load_extensions(tmp_path)
    assert [e.name for e in exts] == ["alpha", "mike", "zulu"]


def test_extension_config_is_valid_cli() -> None:
    """C3: ``is_valid()`` returns True only when the right field is set (C3)."""
    valid_cli = ExtensionConfig(name="x", kind="cli", command="true")
    assert valid_cli.is_valid()
    invalid_cli = ExtensionConfig(name="y", kind="cli", command=None)
    assert not invalid_cli.is_valid()


def test_extension_config_is_valid_http() -> None:
    """C3: HTTP extensions require a URL (C3)."""
    valid_http = ExtensionConfig(name="x", kind="http", url="http://localhost:1234")
    assert valid_http.is_valid()
    invalid_http = ExtensionConfig(name="y", kind="http", url=None)
    assert not invalid_http.is_valid()
