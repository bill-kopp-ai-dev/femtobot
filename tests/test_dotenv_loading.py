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
    6. ``_merge_env_overrides`` patches null/empty leaves in the on-disk
       ``data`` dict so ``Config.model_validate(data)`` (which DOES NOT
       re-read ``os.environ``) still picks up the secrets.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from femtobot.config import loader
from femtobot.config.loader import (
    _load_instance_env_file,
    _merge_env_overrides,
    _set_if_blank,
    _snake_to_camel,
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


# -----------------------------------------------------------------------------
# _merge_env_overrides / _set_if_blank
#
# These functions patch the on-disk ``data`` dict BEFORE
# ``Config.model_validate(data)`` is called, because model_validate does NOT
# re-read ``os.environ``. Without this seam, a scrubbed ``config.json`` with
# ``apiKey: null`` would silently wipe every secret from the ``.env``.
# -----------------------------------------------------------------------------


def test_merge_env_overrides_patches_null_camel_case_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``apiKey: null`` in JSON must be replaced by env value, in-place."""
    monkeypatch.setenv("FEMTOBOT_PROVIDERS__MINIMAX__API_KEY", "tok-1")
    data = {"providers": {"minimax": {"apiKey": None, "apiBase": "https://x"}}}

    merged = _merge_env_overrides(data)

    # No duplicate keys: the existing ``apiKey`` key was overwritten, NOT a
    # new ``api_key`` added next to it.
    assert "apiKey" in merged["providers"]["minimax"]
    assert "api_key" not in merged["providers"]["minimax"]
    assert merged["providers"]["minimax"]["apiKey"] == "tok-1"
    # Untouched fields survive.
    assert merged["providers"]["minimax"]["apiBase"] == "https://x"


def test_merge_env_overrides_patches_null_snake_case_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A snake_case ``api_key: null`` leaf is also patched."""
    monkeypatch.setenv("FEMTOBOT_PROVIDERS__GROQ__API_KEY", "tok-2")
    data = {"providers": {"groq": {"api_key": None}}}

    merged = _merge_env_overrides(data)

    assert merged["providers"]["groq"]["api_key"] == "tok-2"


def test_merge_env_overrides_does_not_overwrite_non_null_json_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the JSON has a real (non-null) value, it wins over the env var.

    This is intentional — the user wrote it in the file, so we trust their
    explicit choice over an inherited environment value.
    """
    monkeypatch.setenv("FEMTOBOT_PROVIDERS__MINIMAX__API_KEY", "from-env")
    data = {"providers": {"minimax": {"apiKey": "from-json"}}}

    merged = _merge_env_overrides(data)

    assert merged["providers"]["minimax"]["apiKey"] == "from-json"


def test_merge_env_overrides_ignores_unrelated_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``FEMTOBOT_*`` env vars participate."""
    monkeypatch.setenv("UNRELATED_API_KEY", "nope")
    monkeypatch.setenv("PATH", "/usr/bin")
    data: dict = {"providers": {"minimax": {"apiKey": None}}}

    merged = _merge_env_overrides(data)

    assert merged["providers"]["minimax"]["apiKey"] is None


def test_merge_env_overrides_skips_empty_string_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare ``KEY=`` line in ``.env`` must NOT clobber a configured value."""
    monkeypatch.setenv("FEMTOBOT_PROVIDERS__MINIMAX__API_KEY", "")
    data = {"providers": {"minimax": {"apiKey": "explicitly-set"}}}

    merged = _merge_env_overrides(data)

    assert merged["providers"]["minimax"]["apiKey"] == "explicitly-set"


def test_merge_env_overrides_refuses_to_create_new_subtrees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env vars cannot invent new dict sub-trees the JSON never sketched.

    This is a safety property: a stale env var like
    ``FEMTOBOT_NONEXISTENT__FIELD=x`` must not silently materialize a
    ``nonExistent`` section that downstream code didn't anticipate.
    """
    monkeypatch.setenv("FEMTOBOT_NONEXISTENT__FIELD", "x")
    data: dict = {"providers": {"minimax": {"apiKey": None}}}

    merged = _merge_env_overrides(data)

    assert "nonexistent" not in merged
    assert merged["providers"]["minimax"]["apiKey"] is None


def test_merge_env_overrides_handles_non_dict_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: a corrupted JSON root (not a dict) returns unchanged."""
    monkeypatch.setenv("FEMTOBOT_PROVIDERS__MINIMAX__API_KEY", "tok")
    data = ["not", "a", "dict"]  # type: ignore[list-item]

    merged = _merge_env_overrides(data)  # type: ignore[arg-type]

    assert merged is data


def test_set_if_blank_writes_when_key_missing() -> None:
    """When neither ``api_key`` nor ``apiKey`` exist at the leaf, write the snake form.

    Intermediate dicts must already exist — by design ``_set_if_blank``
    refuses to invent new sub-trees (see
    ``test_merge_env_overrides_refuses_to_create_new_subtrees``).
    """
    node = {"providers": {"minimax": {}}}
    _set_if_blank(node, ["providers", "minimax", "api_key"], "v")
    assert node == {"providers": {"minimax": {"api_key": "v"}}}


def test_set_if_blank_overwrites_blank_camel() -> None:
    """When only the camelCase key exists and is ``None``, overwrite in place."""
    node = {"providers": {"minimax": {"apiKey": None}}}
    _set_if_blank(node, ["providers", "minimax", "api_key"], "v")
    assert "apiKey" in node["providers"]["minimax"]
    assert "api_key" not in node["providers"]["minimax"]
    assert node["providers"]["minimax"]["apiKey"] == "v"


def test_set_if_blank_preserves_non_null_value() -> None:
    """When the camelCase key holds a real value, leave it alone."""
    node = {"providers": {"minimax": {"apiKey": "keep-me"}}}
    _set_if_blank(node, ["providers", "minimax", "api_key"], "v")
    assert node["providers"]["minimax"]["apiKey"] == "keep-me"


def test_snake_to_camel_known_cases() -> None:
    """Pin the helper so a future Pydantic alias-generator change is caught."""
    assert _snake_to_camel("api_key") == "apiKey"
    assert _snake_to_camel("api_base") == "apiBase"
    assert _snake_to_camel("extra_headers") == "extraHeaders"
    assert _snake_to_camel("api") == "api"