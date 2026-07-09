"""Tests for the schema-level ``agents.cli.*`` block (Camada 1)."""

from __future__ import annotations

from femtobot.config.schema import (
    AgentDefaults,
    CliConfig,
    CliSessionStatusConfig,
    CliWhimsyConfig,
    Config,
)


def test_cli_config_defaults_are_backward_compatible() -> None:
    """All fields default to values that reproduce the pre-Camada-1 behavior."""
    cfg = CliConfig()
    assert cfg.multiline == "backslash"
    assert cfg.completer_enabled is True
    assert cfg.completer_max_results == 10
    assert cfg.bash_mode_enabled is True
    assert cfg.bash_mode_timeout_s == 30.0
    assert cfg.file_mention_enabled is True
    assert cfg.theme == "terracotta-claude"


def test_whimsy_defaults() -> None:
    w = CliWhimsyConfig()
    assert w.verbs_enabled is True
    assert w.spinner_style == "auto"
    assert w.verb_pool_size == 40


def test_session_status_defaults() -> None:
    s = CliSessionStatusConfig()
    assert s.enabled is True
    assert s.show_tokens is True
    assert s.show_elapsed is True


def test_agent_defaults_have_cli_block() -> None:
    """``AgentDefaults`` must carry a ``cli`` block with sane defaults."""
    d = AgentDefaults()
    assert isinstance(d.cli, CliConfig)


def test_full_config_constructs_with_no_args() -> None:
    """The full Config must instantiate with no FEMTOBOT_* env override."""
    cfg = Config()
    assert isinstance(cfg.agents.defaults.cli, CliConfig)
    assert cfg.agents.defaults.cli.theme == "terracotta-claude"


def test_submit_multiline_transform_replaces_backslash_newlines() -> None:
    from femtobot.cli.commands import submit_multiline_transform

    assert submit_multiline_transform("line1\\\nline2") == "line1\nline2"
    assert submit_multiline_transform("a\\\nb\\\nc") == "a\nb\nc"
    # No backslash-newlines: pass-through
    assert submit_multiline_transform("plain text") == "plain text"
