"""Tests for the secret-scrubbing layer used by ``write_default_config`` and
``save_config``.

Refs: project security review (2026-06-27).

Background
----------
``Config`` is a ``pydantic_settings.BaseSettings`` with
``env_prefix="FEMTOBOT_"``, which means ``Config()`` auto-populates fields
from shell env vars. Before the scrubber, those env-loaded values were dumped
verbatim into ``config.json``. This module ensures that secret-bearing fields
(api_key, token, secret, password, ...) are replaced with ``None`` before the
config hits disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from loguru import logger as _loguru_logger

from femtobot.config.schema import Config
from femtobot.utils.helpers import write_default_config
from femtobot.utils.secret_scrub import (
    DEFAULT_SENSITIVE_FIELDS,
    count_secrets,
    is_sensitive_field_name,
    scrub_secrets,
)


@pytest.fixture
def loguru_sink() -> list[str]:
    """Capture loguru messages emitted during a test.

    loguru doesn't bridge to the stdlib logging module by default, so
    pytest's ``caplog`` won't see them. This fixture installs a temporary
    sink that buffers formatted messages; the sink is removed at teardown.
    """
    captured: list[str] = []
    sink_id = _loguru_logger.add(
        lambda msg: captured.append(str(msg)),
        level="WARNING",
        format="{message}",
    )
    try:
        yield captured
    finally:
        _loguru_logger.remove(sink_id)


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------


def test_default_catalog_includes_api_key() -> None:
    """``api_key`` MUST be in the catalog — it's the field that triggered the
    whole scrubber."""
    assert "api_key" in DEFAULT_SENSITIVE_FIELDS


def test_default_catalog_includes_common_secret_names() -> None:
    """Common credential / token names are present."""
    expected = {"api_key", "secret", "token", "password", "private_key"}
    assert expected.issubset(DEFAULT_SENSITIVE_FIELDS)


def test_default_catalog_excludes_lookalikes() -> None:
    """Fields that LOOK sensitive but aren't credentials stay out."""
    # `max_tokens`, `context_window_tokens`, etc. must NOT be scrubbed.
    assert "max_tokens" not in DEFAULT_SENSITIVE_FIELDS
    assert "context_window_tokens" not in DEFAULT_SENSITIVE_FIELDS
    assert "max_tool_iterations" not in DEFAULT_SENSITIVE_FIELDS


def test_is_sensitive_field_name_is_case_insensitive() -> None:
    """Field-name match is case-insensitive."""
    assert is_sensitive_field_name("API_KEY")
    assert is_sensitive_field_name("Api_Key")
    assert is_sensitive_field_name("api_key")
    assert is_sensitive_field_name("Secret")
    assert not is_sensitive_field_name("max_tokens")
    assert not is_sensitive_field_name("model")


# ---------------------------------------------------------------------------
# scrub_secrets() — basic mechanics
# ---------------------------------------------------------------------------


def test_scrub_replaces_api_key_with_none() -> None:
    scrubbed, n = scrub_secrets({"api_key": "sk-leaked-123"})
    assert scrubbed == {"api_key": None}
    assert n == 1


def test_scrub_preserves_non_sensitive_fields() -> None:
    data = {"api_key": "sk-x", "model": "claude-opus", "max_tokens": 8192}
    scrubbed, n = scrub_secrets(data)
    assert scrubbed == {"api_key": None, "model": "claude-opus", "max_tokens": 8192}
    assert n == 1


def test_scrub_does_not_mutate_input() -> None:
    """The input tree must be left untouched (deep-copy semantics)."""
    data = {
        "providers": {"minimax": {"api_key": "sk-real", "api_base": "https://x"}},
        "agents": {"defaults": {"model": "claude-opus"}},
    }
    snapshot = json.dumps(data, sort_keys=True)
    scrubbed, n = scrub_secrets(data)
    # Input unchanged.
    assert json.dumps(data, sort_keys=True) == snapshot
    # Output scrubbed.
    assert scrubbed["providers"]["minimax"]["api_key"] is None
    assert scrubbed["providers"]["minimax"]["api_base"] == "https://x"
    assert scrubbed["agents"]["defaults"]["model"] == "claude-opus"
    assert n == 1


def test_scrub_handles_nested_dicts() -> None:
    data = {
        "providers": {
            "minimax": {"api_key": "sk-1", "api_base": "u"},
            "groq": {"api_key": "gsk-1"},
        }
    }
    scrubbed, n = scrub_secrets(data)
    assert scrubbed["providers"]["minimax"]["api_key"] is None
    assert scrubbed["providers"]["minimax"]["api_base"] == "u"
    assert scrubbed["providers"]["groq"]["api_key"] is None
    assert n == 2


def test_scrub_handles_lists_of_dicts() -> None:
    """MCP servers, fallback_models, etc. are lists — they must be walked."""
    data = {
        "fallback_models": [
            {"model": "claude-opus", "provider": "anthropic", "api_key": "sk-1"},
            {"model": "gpt-4o", "provider": "openai"},
        ]
    }
    scrubbed, n = scrub_secrets(data)
    assert scrubbed["fallback_models"][0]["api_key"] is None
    assert scrubbed["fallback_models"][0]["model"] == "claude-opus"
    assert scrubbed["fallback_models"][1] == {"model": "gpt-4o", "provider": "openai"}
    assert n == 1


def test_scrub_handles_lists_of_primitives() -> None:
    """``disabled_skills`` and similar are lists of strings."""
    data = {"disabled_skills": ["summarize", "skill-creator"]}
    scrubbed, n = scrub_secrets(data)
    assert scrubbed == data
    assert n == 0


def test_scrub_does_not_count_none_values() -> None:
    """A field that's already None is not counted as a scrubbed secret."""
    data = {"api_key": None, "token": None}
    scrubbed, n = scrub_secrets(data)
    assert scrubbed == data
    assert n == 0


def test_scrub_does_not_count_empty_strings() -> None:
    data = {"api_key": "", "token": ""}
    scrubbed, n = scrub_secrets(data)
    assert scrubbed == data
    assert n == 0


def test_scrub_handles_all_default_sensitive_names() -> None:
    """Every name in the catalog is actually scrubbed when set."""
    for name in DEFAULT_SENSITIVE_FIELDS:
        data = {name: "leaked-value"}
        scrubbed, n = scrub_secrets(data)
        assert scrubbed[name] is None, f"Field {name!r} was not scrubbed"
        assert n == 1, f"Field {name!r} was not counted"


def test_scrub_preserves_unrecognized_suffix_tokens() -> None:
    """``max_tokens`` and ``context_window_tokens`` end with 'tokens' but are
    not credentials — they must NOT be scrubbed."""
    data = {"max_tokens": 8192, "context_window_tokens": 65536}
    scrubbed, n = scrub_secrets(data)
    assert scrubbed == data
    assert n == 0


def test_scrub_accepts_custom_catalog() -> None:
    """Callers can extend or override the sensitive-field catalog."""
    data = {"api_key": "sk-1", "custom_field": "value"}
    scrubbed, n = scrub_secrets(
        data, sensitive_names=frozenset({"custom_field"})
    )
    # Only `custom_field` is scrubbed because we overrode the catalog.
    assert scrubbed == {"api_key": "sk-1", "custom_field": None}
    assert n == 1


def test_scrub_is_idempotent() -> None:
    """Scrubbing an already-scrubbed structure is a no-op."""
    once, n1 = scrub_secrets({"api_key": "sk-1", "model": "x"})
    twice, n2 = scrub_secrets(once)
    assert once == twice
    assert n1 == 1
    assert n2 == 0


def test_count_secrets_does_not_copy() -> None:
    """``count_secrets`` is a non-mutating observer."""
    data = {"api_key": "sk-1", "token": "tok-1"}
    n = count_secrets(data)
    assert n == 2
    # Original unchanged.
    assert data["api_key"] == "sk-1"
    assert data["token"] == "tok-1"


# ---------------------------------------------------------------------------
# Integration: write_default_config() scrubs by default
# ---------------------------------------------------------------------------


def _build_config_with_secrets(monkeypatch: pytest.MonkeyPatch) -> Config:
    """Build a Config as if FEMTOBOT_PROVIDERS__MINIMAX__API_KEY was set.

    We can't easily inject env vars into Pydantic Settings without side
    effects on the rest of the test session, so we set the field directly on
    the model after construction. The point is to simulate the post-load
    state of ``Config()`` once env-var auto-loading has populated it.
    """
    cfg = Config()
    cfg.providers.minimax.api_key = "sk-cp-leaked-key"
    cfg.providers.groq.api_key = "gsk-leaked"
    cfg.providers.minimax.api_base = "https://api.minimax.io/v1"
    cfg.agents.defaults.model = "MiniMax-M3"
    cfg.agents.defaults.provider = "minimax"
    return cfg


def test_write_default_config_scrubs_secrets_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: a config with API keys is written to disk with keys=None."""
    cfg = _build_config_with_secrets(monkeypatch)
    out = tmp_path / "config.json"

    write_default_config(cfg, out, force=True)

    persisted = json.loads(out.read_text(encoding="utf-8"))
    assert persisted["providers"]["minimax"]["apiKey"] is None
    assert persisted["providers"]["groq"]["apiKey"] is None
    # Non-secret fields are preserved.
    assert persisted["providers"]["minimax"]["apiBase"] == "https://api.minimax.io/v1"
    assert persisted["agents"]["defaults"]["model"] == "MiniMax-M3"


def test_write_default_config_scrubs_when_force_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``force=True`` re-scrubs on overwrite (no skipped path)."""
    out = tmp_path / "config.json"
    out.write_text('{"old": "data"}', encoding="utf-8")

    cfg = _build_config_with_secrets(monkeypatch)
    write_default_config(cfg, out, force=True)

    persisted = json.loads(out.read_text(encoding="utf-8"))
    assert persisted["providers"]["minimax"]["apiKey"] is None


def test_write_default_config_respects_scrub_false_opt_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``scrub_secrets=False`` lets the user opt out (with a warning)."""
    cfg = _build_config_with_secrets(monkeypatch)
    out = tmp_path / "config.json"

    write_default_config(cfg, out, force=True, scrub_secrets=False)

    persisted = json.loads(out.read_text(encoding="utf-8"))
    # The opt-out path keeps secrets verbatim.
    assert persisted["providers"]["minimax"]["apiKey"] == "sk-cp-leaked-key"
    assert persisted["providers"]["groq"]["apiKey"] == "gsk-leaked"


def test_write_default_config_logs_warning_when_secrets_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loguru_sink: list[str]
) -> None:
    """A ``loguru`` warning fires when secrets are detected in the in-memory
    config — gives the user a chance to learn where to put them."""
    cfg = _build_config_with_secrets(monkeypatch)
    out = tmp_path / "config.json"

    write_default_config(cfg, out, force=True)

    assert any(
        "sensitive field" in m and "config.json" in m for m in loguru_sink
    ), f"Expected warning about sensitive fields. Got: {loguru_sink!r}"


def test_write_default_config_no_warning_when_clean(
    tmp_path: Path, loguru_sink: list[str]
) -> None:
    """A pure-default Config (no secrets) emits no warning — silence = OK."""
    cfg = Config()
    out = tmp_path / "config.json"

    write_default_config(cfg, out, force=True)

    assert not any("sensitive field" in m for m in loguru_sink), (
        f"Unexpected warning on clean config: {loguru_sink!r}"
    )


def test_write_default_config_skips_existing_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the file already exists and ``force=False``, write is a no-op and
    no scrubbing happens (the existing file is untouched)."""
    out = tmp_path / "config.json"
    sentinel = '{"untouched": true}'
    out.write_text(sentinel, encoding="utf-8")

    cfg = _build_config_with_secrets(monkeypatch)
    written = write_default_config(cfg, out, force=False)

    assert written is False
    assert out.read_text(encoding="utf-8") == sentinel


def test_write_default_config_round_trips_real_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scrubbed output, when re-loaded via ``Config.model_validate``,
    produces the same non-secret fields."""
    cfg = _build_config_with_secrets(monkeypatch)
    out = tmp_path / "config.json"
    write_default_config(cfg, out, force=True)

    persisted = json.loads(out.read_text(encoding="utf-8"))
    reloaded = Config.model_validate(persisted)

    assert reloaded.agents.defaults.model == "MiniMax-M3"
    assert reloaded.agents.defaults.provider == "minimax"
    assert reloaded.providers.minimax.api_base == "https://api.minimax.io/v1"
    # Secrets are null after round-trip.
    assert reloaded.providers.minimax.api_key is None
    assert reloaded.providers.groq.api_key is None


# ---------------------------------------------------------------------------
# Integration: save_config() in loader.py mirrors write_default_config()
# ---------------------------------------------------------------------------


def test_save_config_scrubs_secrets_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``femtobot.config.loader.save_config`` has the same default behavior."""
    from femtobot.config.loader import save_config

    cfg = _build_config_with_secrets(monkeypatch)
    out = tmp_path / "config.json"

    save_config(cfg, out)

    persisted = json.loads(out.read_text(encoding="utf-8"))
    assert persisted["providers"]["minimax"]["apiKey"] is None
    assert persisted["providers"]["groq"]["apiKey"] is None


def test_save_config_respects_scrub_false_opt_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from femtobot.config.loader import save_config

    cfg = _build_config_with_secrets(monkeypatch)
    out = tmp_path / "config.json"

    save_config(cfg, out, scrub_secrets=False)

    persisted = json.loads(out.read_text(encoding="utf-8"))
    assert persisted["providers"]["minimax"]["apiKey"] == "sk-cp-leaked-key"


def test_save_config_logs_warning_when_secrets_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loguru_sink: list[str]
) -> None:
    from femtobot.config.loader import save_config

    cfg = _build_config_with_secrets(monkeypatch)
    out = tmp_path / "config.json"

    save_config(cfg, out)

    assert any("sensitive field" in m for m in loguru_sink), (
        f"Expected warning about sensitive fields. Got: {loguru_sink!r}"
    )


# ---------------------------------------------------------------------------
# Regression: defense-in-depth against the original bug
# ---------------------------------------------------------------------------


def test_default_config_has_no_secrets_after_onboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate the exact ``femtobot onboard`` flow end-to-end.

    This is the regression test for the bug the user hit: with the fix in
    place, even if the parent shell exports ``FEMTOBOT_PROVIDERS__MINIMAX__API_KEY``,
    the persisted ``config.json`` will not contain the key.

    We simulate the env-var path by setting the field directly on the Config
    object (same end-state as Pydantic Settings auto-loading).
    """
    from femtobot.utils.helpers import build_default_onboard_config

    instance = tmp_path / "instance"
    cfg = build_default_onboard_config(instance)
    # Simulate Pydantic Settings having read env vars into the model.
    cfg.providers.minimax.api_key = "sk-cp-from-env"
    cfg.providers.groq.api_key = "gsk-from-env"
    cfg.providers.custom.api_key = "VENICE-from-env"

    out = instance / "config.json"
    write_default_config(cfg, out, force=True)

    persisted = json.loads(out.read_text(encoding="utf-8"))
    assert persisted["providers"]["minimax"]["apiKey"] is None
    assert persisted["providers"]["groq"]["apiKey"] is None
    assert persisted["providers"]["custom"]["apiKey"] is None
    # Non-secret fields are preserved.
    assert persisted["agents"]["defaults"]["workspace"] == "workspace"
