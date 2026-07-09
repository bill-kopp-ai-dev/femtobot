"""Config-loader fail-fast tests (A1).

A1 (REFACTOR_PLAN.md Lote A) added a strict mode gated by
``FEMTOBOT_STRICT_CONFIG_LOAD`` that aborts with exit code 2 on invalid
JSON or a required-field ``pydantic.ValidationError``.  The default
behavior (lenient) is preserved for backward compat — the loader still
falls back to defaults, but now logs at ``error`` level (not ``warning``)
for JSON syntax errors and required-field validation errors so a silent
fallback can't mask a broken config.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from femtobot.config import loader as config_loader

pytestmark = pytest.mark.security


@pytest.fixture
def write_config(tmp_path: Path):
    def _write(payload: str | dict) -> Path:
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps(payload) if isinstance(payload, dict) else payload,
            encoding="utf-8",
        )
        return path

    return _write


def test_strict_mode_aborts_on_invalid_json(
    write_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Strict mode + invalid JSON → SystemExit(2) (A1)."""
    path = write_config("{not valid json")
    monkeypatch.setenv("FEMTOBOT_STRICT_CONFIG_LOAD", "1")
    with pytest.raises(SystemExit) as excinfo:
        config_loader.load_config(config_path=path)
    assert excinfo.value.code == 2


def test_lenient_mode_emits_error_on_invalid_json(
    write_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lenient mode (default) emits at error level for invalid JSON (A1)."""
    from loguru import logger

    path = write_config("{not valid json")
    seen: list[tuple[str, str]] = []

    def _sink(message) -> None:  # type: ignore[no-untyped-def]
        record = message.record if hasattr(message, "record") else message
        seen.append((record["level"].name, record["message"]))

    handler_id = logger.add(_sink, level="ERROR")
    try:
        cfg = config_loader.load_config(config_path=path)
    finally:
        logger.remove(handler_id)
    # Loader returns defaults on failure in lenient mode.
    assert cfg is not None
    error_messages = [m for level, m in seen if level == "ERROR"]
    assert any("invalid JSON" in m for m in error_messages)


def test_validate_config_strict_returns_false(
    write_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``validate_config(..., strict=True)`` returns ``(False, msg)`` on bad JSON (A1)."""
    path = write_config("{not valid json")
    monkeypatch.setenv("FEMTOBOT_STRICT_CONFIG_LOAD", "1")
    ok, _msg = config_loader.validate_config(config_path=path, strict=True)
    assert ok is False


def test_validate_config_lenient_returns_true_on_bad_json(
    write_config,
) -> None:
    """In lenient mode, the validator still returns ``True`` (best-effort) (A1)."""
    path = write_config("{not valid json")
    ok, _msg = config_loader.validate_config(config_path=path, strict=False)
    assert ok is True


def test_is_strict_config_load_env_truthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Truthy env values enable strict mode (A1)."""
    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv("FEMTOBOT_STRICT_CONFIG_LOAD", value)
        assert config_loader._is_strict_config_load() is True


def test_is_strict_config_load_default_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the env var, strict mode is off (backward compat, A1)."""
    monkeypatch.delenv("FEMTOBOT_STRICT_CONFIG_LOAD", raising=False)
    assert config_loader._is_strict_config_load() is False
