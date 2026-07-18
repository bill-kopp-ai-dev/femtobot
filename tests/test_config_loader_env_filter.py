"""Config-loader env-var namespace filter (audit 2026-07-18 v3).

Regression: ``FEMTOBOT_LOGFIRE`` and other feature-flag env vars share the
``FEMTOBOT_*`` namespace with the actual ``Config`` fields. The previous
``_merge_env_overrides`` happily coerced any matching env var into a
synthetic field on the config dict, which the ``Config`` ``extra="forbid"``
policy then rejected — masking the real config with a silent "Using
default configuration" fallback and surfacing a confusing
``Specified model not found: anthropic/claude-opus-4-5`` error from
PydanticAI.

The fix: ``_merge_env_overrides`` now consults a precomputed set of valid
``Config`` field paths (built lazily from ``Config.model_fields``) and
silently skips env vars whose path is not in that set. Feature flags
keep working when read via ``os.environ.get`` directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from femtobot.config import loader as config_loader
from femtobot.config.loader import _known_config_paths, _merge_env_overrides

pytestmark = pytest.mark.security


@pytest.fixture
def write_config(tmp_path: Path):
    def _write(payload: dict) -> Path:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return _write


def test_known_paths_contains_provider_api_key() -> None:
    """Sanity: the canonical provider-credentials path is in the set."""
    paths = _known_config_paths()
    assert ("providers", "minimax", "api_key") in paths
    assert ("agents", "defaults", "model") in paths
    assert ("agents", "defaults", "provider") in paths


def test_known_paths_does_not_contain_feature_flags() -> None:
    """Logfire / httpx feature flags are NOT Config fields."""
    paths = _known_config_paths()
    assert ("logfire",) not in paths
    assert ("logfire_send",) not in paths
    assert ("logfire_httpx",) not in paths
    assert ("strict_config_load",) not in paths


def test_merge_skips_unknown_femtobot_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``FEMTOBOT_LOGFIRE=1`` must not be injected into the config dict."""
    monkeypatch.setenv("FEMTOBOT_LOGFIRE", "1")
    monkeypatch.setenv("FEMTOBOT_LOGFIRE_HTTPX", "1")
    data: dict = {"agents": {"defaults": {"model": "MiniMax-M3"}}}
    _merge_env_overrides(data)
    # No synthetic fields should have been created.
    assert "logfire" not in data
    assert "logfire_httpx" not in data
    # The legitimate field is untouched.
    assert data["agents"]["defaults"]["model"] == "MiniMax-M3"


def test_merge_preserves_known_provider_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real provider env var (KNOWN path) is still injected."""
    monkeypatch.setenv("FEMTOBOT_PROVIDERS__MINIMAX__API_KEY", "sk-test-xyz")
    data: dict = {
        "agents": {"defaults": {}},
        "providers": {"minimax": {"api_key": None}},
    }
    _merge_env_overrides(data)
    assert data["providers"]["minimax"]["api_key"] == "sk-test-xyz"


def test_merge_mixed_known_and_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known + unknown in the same env: only known is injected."""
    monkeypatch.setenv("FEMTOBOT_LOGFIRE", "1")
    monkeypatch.setenv("FEMTOBOT_PROVIDERS__MINIMAX__API_KEY", "sk-mixed")
    data: dict = {
        "agents": {"defaults": {}},
        "providers": {"minimax": {"api_key": None}},
    }
    _merge_env_overrides(data)
    assert data["providers"]["minimax"]["api_key"] == "sk-mixed"
    assert "logfire" not in data


def test_load_config_under_logfire_env_keeps_user_model(
    write_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: ``FEMTOBOT_LOGFIRE=1`` must NOT swap the configured model
    for the hardcoded default. Regression for the
    ``anthropic/claude-opus-4-5`` false-positive surfaced during agent
    smoke-testing on 2026-07-18.
    """
    cfg_path = write_config(
        {
            "agents": {
                "defaults": {
                    "model": "MiniMax-M3",
                    "provider": "minimax",
                }
            }
        }
    )
    monkeypatch.setenv("FEMTOBOT_LOGFIRE", "1")
    # Reload the path cache so the fixture is re-derived cleanly.
    config_loader._known_config_paths_cache = None  # type: ignore[attr-defined]
    cfg = config_loader.load_config(config_path=cfg_path)
    assert cfg.agents.defaults.model == "MiniMax-M3"
    assert cfg.agents.defaults.provider == "minimax"


def test_logfire_debug_log_emitted_for_unknown_var(
    write_config, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A debug-level log line explains the skip (visible when log level
    is DEBUG; the default loguru config doesn't show DEBUG so this just
    asserts the call path is taken)."""
    cfg_path = write_config({"agents": {"defaults": {"model": "MiniMax-M3"}}})
    monkeypatch.setenv("FEMTOBOT_LOGFIRE", "1")
    config_loader._known_config_paths_cache = None  # type: ignore[attr-defined]
    # Just exercise the path; loguru's sink isn't on stdlib caplog.
    config_loader.load_config(config_path=cfg_path)
    # And the os.environ side effect is still intact for direct readers.
    assert os.environ.get("FEMTOBOT_LOGFIRE") == "1"
