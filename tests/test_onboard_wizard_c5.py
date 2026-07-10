"""Onboard wizard tests (C5).

C5 (REFACTOR_PLAN.md Lote C): ``femtobot onboard`` runs an optional
wizard that prompts for provider / model / API key.  We test the
non-interactive pieces: the curated model list, the env-key table,
and the in-memory config mutation that the wizard performs when the
user makes choices.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from femtobot.cli.onboard_wizard import (
    _CURATED_MODELS,
    _env_key_for,
    _list_providers,
    _models_for,
    run_onboard_wizard,
)

pytestmark = pytest.mark.architecture


def test_curated_models_have_known_providers() -> None:
    """C5: every curated model entry references a real provider (C5)."""
    expected = {
        "anthropic",
        "openai",
        "openrouter",
        "ollama",
        "gemini",
        "groq",
        "mistral",
        "deepseek",
    }
    assert set(_CURATED_MODELS.keys()) <= expected
    # At least the big three are present.
    for p in ("anthropic", "openai", "openrouter"):
        assert p in _CURATED_MODELS
        assert len(_CURATED_MODELS[p]) >= 2


def test_env_key_for_known_providers() -> None:
    """C5: ``_env_key_for`` returns the conventional env var name (C5)."""
    assert _env_key_for("anthropic") == "ANTHROPIC_API_KEY"
    assert _env_key_for("openai") == "OPENAI_API_KEY"
    assert _env_key_for("openrouter") == "OPENROUTER_API_KEY"


def test_env_key_for_unknown_provider_is_none() -> None:
    """C5: an unknown provider has no env key mapping (C5)."""
    assert _env_key_for("no_such_provider") is None


def test_models_for_known_provider() -> None:
    """C5: ``_models_for`` returns the curated list for known providers (C5)."""
    models = _models_for("anthropic")
    assert "claude-3-5-sonnet-20241022" in models


def test_models_for_unknown_provider_returns_custom_placeholder() -> None:
    """C5: an unknown provider gets a single ``<custom>`` placeholder (C5)."""
    models = _models_for("no_such_provider")
    assert models == ["<custom>"]


def test_list_providers_returns_sorted_list() -> None:
    """C5: ``_list_providers`` returns a sorted list of strings (C5)."""
    providers = _list_providers()
    assert isinstance(providers, list)
    assert all(isinstance(p, str) for p in providers)
    assert providers == sorted(providers)


def test_run_onboard_wizard_returns_none_when_not_tty() -> None:
    """C5: non-TTY stdin makes the wizard a no-op (C5)."""
    with patch("sys.stdin") as fake_stdin:
        fake_stdin.isatty.return_value = False
        result = run_onboard_wizard(config=None)
    assert result is None


def test_run_onboard_wizard_cancelled_returns_result() -> None:
    """C5: a tty + canned input runs the prompts (C5)."""
    # Simulate a tty + a tiny script of answers.
    answers = iter(
        [
            "Q",  # main-menu "Quick Start"
            "anthropic",  # provider
            "claude-3-5-sonnet-20241022",  # model
            "",  # api key (skip)
        ]
    )

    def fake_ask(*args, **kwargs):
        return next(answers)

    class FakeConsole:
        def print(self, *args, **kwargs):
            return None

    with (
        patch("sys.stdin") as fake_stdin,
        patch("femtobot.cli.onboard_wizard.Prompt") as fake_prompt,
    ):
        fake_stdin.isatty.return_value = True
        fake_prompt.ask.side_effect = fake_ask
        result = run_onboard_wizard(config=None, console=FakeConsole())  # type: ignore[arg-type]

    # Wizard returns the chosen provider / model even when no config was passed.
    assert result is not None
    assert result.provider == "anthropic"
    assert result.model == "claude-3-5-sonnet-20241022"
    assert result.api_key_provided is False


def test_run_onboard_wizard_with_config_mutates_in_place() -> None:
    """C5: the wizard mutates ``config.model_presets`` and ``config.providers`` (C5)."""
    from femtobot.config.schema import Config, ModelPresetConfig, ProviderConfig

    cfg = Config()
    cfg.providers = {"anthropic": ProviderConfig(api_key="sk-test")}
    cfg.model_presets = {}

    answers = iter(
        [
            "Q",  # main-menu "Quick Start" (CLI-parity v0.1.7 Issue 3)
            "openai",  # provider
            "gpt-4o",  # model
            "sk-openai-test",  # api key
        ]
    )

    def fake_ask(*args, **kwargs):
        return next(answers)

    from unittest.mock import MagicMock
    fake_console = MagicMock()

    with (
        patch("sys.stdin") as fake_stdin,
        patch.dict(os.environ, {}, clear=False),
        patch("femtobot.cli.onboard_wizard.Prompt") as fake_prompt,
    ):
        fake_stdin.isatty.return_value = True
        # Ensure the wizard thinks no key is in env so it asks.
        os.environ.pop("OPENAI_API_KEY", None)
        fake_prompt.ask.side_effect = fake_ask
        result = run_onboard_wizard(config=cfg, console=fake_console)

    # Wizard should have created a new provider entry + preset.
    assert result is not None
    assert "openai" in cfg.providers
    assert cfg.providers["openai"].api_key == "sk-openai-test"
    assert "openai-wizard" in cfg.model_presets
    preset = cfg.model_presets["openai-wizard"]
    assert isinstance(preset, ModelPresetConfig)
    assert preset.model == "gpt-4o"
    # The default preset is now ``openai-wizard``.
    assert cfg.agents.defaults.model_preset == "openai-wizard"
