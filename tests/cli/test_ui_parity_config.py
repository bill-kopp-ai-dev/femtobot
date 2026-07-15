"""Tests for the UI-parity config additions (T1).

Covers the new fields added in v0.1.0-ui.0:

  * ``agents.defaults.user.name`` (Q2 — welcome card / header bar)
  * ``agents.defaults.cli.ui_parity`` (D1 — profile selector)
  * ``agents.defaults.cli.ui_parity.notice`` (preview notice block)
  * ``agents.defaults.cli.permission_prompt.enabled`` (Q4 master switch)
  * ``agents.defaults.cli.permission_prompt.high_risk_only`` (Q4 filter)

Defaults must keep v0.0.x Femtobot behaviour intact — the preview is
opt-in on all fronts.
"""

from __future__ import annotations

from femtobot.config.schema import (
    CliPermissionPromptConfig,
    CliUiParityConfig,
    Config,
    UserConfig,
)


def test_user_name_default_is_placeholder():
    """Q2 — fresh configs carry the ``<your-name>`` placeholder so the user
    can grep for it and personalise via ``/style set user.name=...``."""
    cfg = Config()
    assert cfg.agents.defaults.user.name == "<your-name>"


def test_user_name_can_be_overridden_via_kwargs():
    cfg = Config(
        agents={
            "defaults": {
                "user": {"name": "Bill Kopp"},
            },
        }
    )
    assert cfg.agents.defaults.user.name == "Bill Kopp"


def test_user_config_is_standalone_class():
    """The ``UserConfig`` block must be importable so tests / docs / slash
    commands can reference the type."""
    uc = UserConfig()
    assert uc.name == "<your-name>"
    uc2 = UserConfig(name="Alice")
    assert uc2.name == "Alice"


def test_ui_parity_default_is_off():
    """D1 — v0.1.0-ui.0 default is ``off`` (no behaviour change)."""
    cfg = Config()
    assert cfg.agents.defaults.cli.ui_parity.profile == "off"


def test_ui_parity_notice_default_true_on_preview():
    """D1 — preview shows the notice block; flips to false in later releases."""
    cfg = Config()
    assert cfg.agents.defaults.cli.ui_parity.notice is True


def test_ui_parity_accepts_compat_and_full():
    """D1 — schema accepts both opt-in profiles (the resolver decides
    whether to actually use ``full`` based on release + textual install)."""
    cfg = Config(agents={"defaults": {"cli": {"ui_parity": {"profile": "compat"}}}})
    assert cfg.agents.defaults.cli.ui_parity.profile == "compat"
    cfg2 = Config(agents={"defaults": {"cli": {"ui_parity": {"profile": "full"}}}})
    assert cfg2.agents.defaults.cli.ui_parity.profile == "full"


def test_ui_parity_rejects_unknown_profile():
    """Schema-level validation: typos fall back via the resolver, not the
    schema (so users get a clear "did you mean compat?" message)."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CliUiParityConfig(profile="premium")  # type: ignore[arg-type]


def test_permission_prompt_defaults_match_plan():
    """Q4 — disabled by default, ``high_risk_only`` true by default."""
    cfg = Config()
    pp = cfg.agents.defaults.cli.permission_prompt
    assert pp.enabled is False
    assert pp.high_risk_only is True


def test_permission_prompt_can_be_toggled():
    cfg = Config(
        agents={
            "defaults": {
                "cli": {
                    "permission_prompt": {
                        "enabled": True,
                        "high_risk_only": False,
                    },
                },
            },
        }
    )
    pp = cfg.agents.defaults.cli.permission_prompt
    assert pp.enabled is True
    assert pp.high_risk_only is False


def test_permission_prompt_class_standalone():
    pp = CliPermissionPromptConfig()
    assert pp.enabled is False
    assert pp.high_risk_only is True


def test_existing_cli_fields_unchanged():
    """Regression guard: adding the new fields must not alter any of the
    existing ``agents.defaults.cli.*`` defaults (Camada 1..5)."""
    cfg = Config()
    cli = cfg.agents.defaults.cli
    assert cli.gap_after_turn == 1
    assert cli.role_header == "always"
    assert cli.user_separator is True
    assert cli.margin_x == 2
    assert cli.gap_before_input == 0
    assert cli.turn_box is True
    assert cli.theme == "terracotta-claude"
    assert cli.multiline == "backslash"
