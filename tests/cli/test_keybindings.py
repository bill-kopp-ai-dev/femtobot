"""Tests for the keybindings module (Camada 2, T2.1)."""

from __future__ import annotations

from pathlib import Path

from femtobot.cli.keybindings import (
    KeyBinding,
    KeybindingsConfig,
    load_keybindings_file,
    parse_keybindings,
)


def test_parse_minimal_binding() -> None:
    bindings = parse_keybindings([{"context": "chat", "key": "ctrl+r", "action": "history:reverse-search"}])
    assert len(bindings) == 1
    b = bindings[0]
    assert b.context == "chat"
    assert b.key == "ctrl+r"
    assert b.action == "history:reverse-search"
    assert b.is_chord() is False


def test_parse_chord_binding() -> None:
    bindings = parse_keybindings([{"context": "global", "key": "ctrl+x", "then": "ctrl+k", "action": "app:exit"}])
    assert len(bindings) == 1
    b = bindings[0]
    assert b.is_chord() is True
    assert b.then == "ctrl+k"
    assert b.primary_keys() == ["ctrl", "x"]


def test_parse_ignores_invalid_entries() -> None:
    bindings = parse_keybindings([{}, "not-a-dict", {"key": "a"}])
    assert len(bindings) == 1
    assert bindings[0].key == "a"


def test_load_nonexistent_file_returns_empty() -> None:
    cfg = load_keybindings_file(Path("/nonexistent/file.json"))
    assert cfg.bindings == []


def test_load_invalid_json_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "invalid.json"
    f.write_text("not json {{{", "utf-8")
    cfg = load_keybindings_file(f)
    assert cfg.bindings == []


def test_load_valid_file(tmp_path: Path) -> None:
    f = tmp_path / "kb.json"
    f.write_text('[{"context":"chat","key":"ctrl+r","action":"history:reverse-search"}]', "utf-8")
    cfg = load_keybindings_file(f)
    assert len(cfg.bindings) == 1
    assert cfg.bindings[0].context == "chat"


def test_config_for_context() -> None:
    cfg = KeybindingsConfig(bindings=[
        KeyBinding(context="chat", key="ctrl+r", action="a"),
        KeyBinding(context="chat", key="ctrl+l", action="b"),
        KeyBinding(context="global", key="ctrl+q", action="c"),
    ])
    chat = cfg.for_context("chat")
    assert len(chat) == 2
    global_ctx = cfg.for_context("global")
    assert len(global_ctx) == 1


def test_config_lookup() -> None:
    cfg = KeybindingsConfig(bindings=[
        KeyBinding(context="chat", key="ctrl+r", action="history:reverse-search"),
        KeyBinding(context="chat", key="ctrl+l", action="chat:clear-input"),
    ])
    hit = cfg.lookup("chat", "ctrl+r")
    assert hit is not None
    assert hit.action == "history:reverse-search"
    assert cfg.lookup("chat", "ctrl+x") is None


def test_key_binding_primary_keys() -> None:
    b = KeyBinding(key="alt+shift+f1", action="test")
    assert b.primary_keys() == ["alt", "shift", "f1"]


def test_case_insensitive_context() -> None:
    bindings = parse_keybindings([{"context": "CHAT", "key": "a", "action": "x"}])
    assert bindings[0].context == "chat"
