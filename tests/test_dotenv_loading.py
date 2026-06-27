"""Tests for ``.env`` auto-loading by ``femtobot.config.loader``.

These tests cover the security-sensitive plumbing that injects provider API
keys from a gitignored ``.env`` file into the ``Config`` ``BaseSettings``
instance. The behavior under test is:

    1. ``<instance_dir>/.env`` is auto-loaded by ``_load_instance_env_file``
       before ``Config()`` is instantiated.
    2. Values flow into ``Config.providers.<name>.api_key`` /
       ``Config.providers.<name>.api_base`` via the existing
       ``env_prefix="FEMTOBOT_"`` + ``env_nested_delimiter="__"`` machinery.
    3. Explicit shell env vars always win over ``.env`` (``override=False``).
    4. When no ``.env`` is present, ``_load_instance_env_file`` returns
       ``None`` and leaves the environment untouched.
    5. The loader is idempotent and safe to call multiple times.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from femtobot.config import loader
from femtobot.config.loader import (
    _load_instance_env_file,
    load_config,
    set_instance_dir,
)


# Env var names used by the tests. Kept short and obviously synthetic so they
# cannot collide with real provider credentials that might leak into the
# test process via a stale shell.
_FEMTOBOT_MINIMAX_KEY = "FEMTOBOT_PROVIDERS__MINIMAX__API_KEY"
_FEMTOBOT_MINIMAX_BASE = "FEMTOBOT_PROVIDERS__MINIMAX__API_BASE"
_FEMTOBOT_GROQ_KEY = "FEMTOBOT_PROVIDERS__GROQ__API_KEY"
_FEMTOBOT_CUSTOM_KEY = "FEMTOBOT_PROVIDERS__CUSTOM__API_KEY"

_DOTENV_KEY = "faketoken-XYZ-12345"
_DOTENV_BASE = "https://example.invalid/v9"


@pytest.fixture
def env_file(instance_dir: Path) -> Path:
    """Drop a synthetic ``.env`` next to the instance dir and return its path."""
    path = instance_dir / ".env"
    path.write_text(
        "# Auto-generated test .env — values are intentionally synthetic.\n"
        f"{_FEMTOBOT_MINIMAX_KEY}={_DOTENV_KEY}\n"
        f"{_FEMTOBOT_MINIMAX_BASE}={_DOTENV_BASE}\n"
        f"{_FEMTOBOT_GROQ_KEY}=groq-test-token\n"
        # Quoted value with embedded hash — must NOT be parsed as a comment.
        f'{_FEMTOBOT_CUSTOM_KEY}="VENICE_INFERENCE_KEY_#-with-hash"\n',
        encoding="utf-8",
    )
    return path


# -----------------------------------------------------------------------------
# _load_instance_env_file
# -----------------------------------------------------------------------------


def test_load_instance_env_file_reads_instance_dotenv(
    instance_dir: Path, env_file: Path
) -> None:
    set_instance_dir(instance_dir)

    loaded = _load_instance_env_file()

    assert loaded == env_file
    assert os.environ[_FEMTOBOT_MINIMAX_KEY] == _DOTENV_KEY
    assert os.environ[_FEMTOBOT_MINIMAX_BASE] == _DOTENV_BASE
    assert os.environ[_FEMTOBOT_GROQ_KEY] == "groq-test-token"
    # Quoted value with an embedded hash must survive verbatim.
    assert os.environ[_FEMTOBOT_CUSTOM_KEY] == "VENICE_INFERENCE_KEY_#-with-hash"


def test_load_instance_env_file_returns_none_when_missing(
    instance_dir: Path,
) -> None:
    """No ``.env`` in instance dir and none in cwd → returns None, env unchanged."""
    set_instance_dir(instance_dir)
    sentinel = "SENTINEL_BEFORE_NO_DOTENV"

    loaded = _load_instance_env_file()

    assert loaded is None
    # No FEMTOBOT_ var was injected.
    assert not any(k.startswith("FEMTOBOT_") for k in os.environ)
    # Pre-existing non-FEMTOBOT env was not touched.
    assert sentinel not in os.environ or os.environ.get(sentinel) == sentinel


def test_load_instance_env_file_does_not_override_existing(
    instance_dir: Path, env_file: Path
) -> None:
    """Explicit shell/IDE env vars must always win over the ``.env`` file."""
    set_instance_dir(instance_dir)
    # Simulate an explicit env var set by the user's shell BEFORE femtobot
    # starts. We use the camelCase equivalent via the same prefix to make the
    # expectation clear.
    explicit_value = "EXPLICIT-FROM-SHELL"
    os.environ[_FEMTOBOT_MINIMAX_KEY] = explicit_value

    _load_instance_env_file()

    assert os.environ[_FEMTOBOT_MINIMAX_KEY] == explicit_value
    # The other env vars, which were not pre-set, ARE filled from the file.
    assert os.environ[_FEMTOBOT_GROQ_KEY] == "groq-test-token"


def test_load_instance_env_file_is_idempotent(
    instance_dir: Path, env_file: Path
) -> None:
    """Calling the loader twice must not duplicate or mutate values."""
    set_instance_dir(instance_dir)

    first = _load_instance_env_file()
    second = _load_instance_env_file()

    assert first == second == env_file
    assert os.environ[_FEMTOBOT_MINIMAX_KEY] == _DOTENV_KEY


def test_load_instance_env_file_handles_blank_and_comment_lines(
    instance_dir: Path,
) -> None:
    """Lines that are blank or start with ``#`` must be ignored gracefully."""
    path = instance_dir / ".env"
    path.write_text(
        "\n"
        "# leading comment\n"
        f"{_FEMTOBOT_MINIMAX_KEY}={_DOTENV_KEY}\n"
        "\n"
        "   \n"
        f"{_FEMTOBOT_GROQ_KEY}=   groq-spaces-around-equals   \n",
        encoding="utf-8",
    )
    set_instance_dir(instance_dir)

    loaded = _load_instance_env_file()

    assert loaded == path
    assert os.environ[_FEMTOBOT_MINIMAX_KEY] == _DOTENV_KEY
    # ``python-dotenv`` strips surrounding whitespace by default.
    assert os.environ[_FEMTOBOT_GROQ_KEY] == "groq-spaces-around-equals"


# -----------------------------------------------------------------------------
# load_config integration: env vars → Config.providers.<name>.api_key
# -----------------------------------------------------------------------------


def test_load_config_picks_up_provider_keys_from_dotenv(
    instance_dir: Path, env_file: Path
) -> None:
    """End-to-end: ``load_config`` reads the ``.env`` and exposes the keys."""
    set_instance_dir(instance_dir)
    # Point the loader at a non-existent config.json so it falls back to the
    # default Config() construction (which is when the env vars are read).
    cfg_path = instance_dir / "config.json"
    assert not cfg_path.exists()

    config = load_config(config_path=cfg_path)

    # API keys must be visible on the resolved providers.
    assert config.providers.minimax.api_key == _DOTENV_KEY
    assert config.providers.minimax.api_base == _DOTENV_BASE
    assert config.providers.groq.api_key == "groq-test-token"
    assert (
        config.providers.custom.api_key
        == "VENICE_INFERENCE_KEY_#-with-hash"
    )


def test_load_config_does_not_persist_keys_when_config_json_absent(
    instance_dir: Path, env_file: Path
) -> None:
    """Loading a config without a backing file must not create one.

    Guard against a regression where ``load_config`` would silently
    materialize a ``config.json`` (potentially with secret values inline)
    simply because a ``.env`` was present.
    """
    set_instance_dir(instance_dir)
    cfg_path = instance_dir / "config.json"
    assert not cfg_path.exists()

    _ = load_config(config_path=cfg_path)

    assert not cfg_path.exists()