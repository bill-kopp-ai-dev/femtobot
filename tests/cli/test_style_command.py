"""Tests for ``/style`` slash command (Camada 5 — runtime spacing tweaks)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from femtobot.bus.events import InboundMessage, OutboundMessage
from femtobot.command.builtin import cmd_style
from femtobot.command.router import CommandContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(cli_overrides: dict | None = None) -> SimpleNamespace:
    """Build a fake loop carrying a config with the desired CLI overrides.

    Always starts from a known baseline (the schema defaults) so the test
    is hermetic and doesn't depend on prior mutations.
    """
    cli = SimpleNamespace(
        gap_after_turn=1,
        role_header="always",
        user_separator=True,
        margin_x=4,
        gap_before_input=2,
        turn_box=True,
    )
    for key, value in (cli_overrides or {}).items():
        setattr(cli, key, value)
    config = SimpleNamespace(
        agents=SimpleNamespace(defaults=SimpleNamespace(cli=cli))
    )
    return SimpleNamespace(_config=config)


def _make_ctx(loop, args: str) -> CommandContext:
    msg = InboundMessage(
        channel="cli", chat_id="chat", sender_id="user", content="/style"
    )
    return CommandContext(
        msg=msg, session=None, key="chat", raw="/style", args=args, loop=loop
    )


# ---------------------------------------------------------------------------
# /style  (no args) — list current values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_style_no_args_lists_current_values() -> None:
    loop = _make_loop(cli_overrides={"margin_x": 6, "turn_box": False})
    ctx = _make_ctx(loop, args="")
    result = await cmd_style(ctx)
    assert isinstance(result, OutboundMessage)
    assert "`margin_x` = `6`" in result.content
    assert "`turn_box` = `False`" in result.content
    assert "Override with `/style set" in result.content


# ---------------------------------------------------------------------------
# /style set …
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_style_set_updates_config() -> None:
    loop = _make_loop()
    ctx = _make_ctx(loop, args="set margin_x=4")
    await cmd_style(ctx)
    assert loop._config.agents.defaults.cli.margin_x == 4


@pytest.mark.asyncio
async def test_style_set_multiple_keys() -> None:
    loop = _make_loop()
    ctx = _make_ctx(loop, args="set margin_x=4 gap_after_turn=2 turn_box=false")
    await cmd_style(ctx)
    cli = loop._config.agents.defaults.cli
    assert cli.margin_x == 4
    assert cli.gap_after_turn == 2
    assert cli.turn_box is False


@pytest.mark.asyncio
async def test_style_set_role_header_literal() -> None:
    loop = _make_loop()
    ctx = _make_ctx(loop, args="set role_header=minimal")
    await cmd_style(ctx)
    assert loop._config.agents.defaults.cli.role_header == "minimal"


@pytest.mark.asyncio
async def test_style_set_user_separator_bool_aliases() -> None:
    loop = _make_loop()
    for raw, expected in (
        ("true", True),
        ("yes", True),
        ("on", True),
        ("1", True),
        ("false", False),
        ("no", False),
        ("off", False),
    ):
        # Reset to True before each subtest.
        loop._config.agents.defaults.cli.user_separator = True
        ctx = _make_ctx(loop, args=f"set user_separator={raw}")
        result = await cmd_style(ctx)
        assert loop._config.agents.defaults.cli.user_separator is expected, (
            f"raw={raw} → expected {expected}, content={result.content!r}"
        )


# ---------------------------------------------------------------------------
# /style reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_style_reset_restores_schema_defaults() -> None:
    loop = _make_loop(cli_overrides={
        "margin_x": 7,
        "gap_after_turn": 3,
        "role_header": "off",
        "turn_box": False,
    })
    ctx = _make_ctx(loop, args="reset")
    await cmd_style(ctx)
    cli = loop._config.agents.defaults.cli
    # Defaults come from the schema (single source of truth).
    from femtobot.config.schema import (
        CLI_DEFAULT_GAP_AFTER_TURN,
        CLI_DEFAULT_MARGIN_X,
        CLI_DEFAULT_ROLE_HEADER_MODE,
        CLI_DEFAULT_TURN_BOX,
    )
    assert cli.margin_x == CLI_DEFAULT_MARGIN_X
    assert cli.gap_after_turn == CLI_DEFAULT_GAP_AFTER_TURN
    assert cli.role_header == CLI_DEFAULT_ROLE_HEADER_MODE
    assert cli.turn_box is CLI_DEFAULT_TURN_BOX


# ---------------------------------------------------------------------------
# Validation / error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_style_set_out_of_bounds_rejected() -> None:
    loop = _make_loop()
    ctx = _make_ctx(loop, args="set margin_x=99")
    result = await cmd_style(ctx)
    # Value not applied.
    assert loop._config.agents.defaults.cli.margin_x == 4
    # User gets a clear error message.
    assert "out of bounds" in result.content.lower()


@pytest.mark.asyncio
async def test_style_set_unknown_key_rejected() -> None:
    loop = _make_loop()
    ctx = _make_ctx(loop, args="set foo=1")
    result = await cmd_style(ctx)
    assert "Unknown key" in result.content
    assert "foo" in result.content


@pytest.mark.asyncio
async def test_style_set_invalid_literal_rejected() -> None:
    loop = _make_loop()
    ctx = _make_ctx(loop, args="set role_header=banana")
    result = await cmd_style(ctx)
    assert "must be one of" in result.content
    # Original value preserved.
    assert loop._config.agents.defaults.cli.role_header == "always"


@pytest.mark.asyncio
async def test_style_set_malformed_token() -> None:
    loop = _make_loop()
    ctx = _make_ctx(loop, args="set margin_x")  # missing '='
    result = await cmd_style(ctx)
    assert "missing '='" in result.content


@pytest.mark.asyncio
async def test_style_unknown_subcommand() -> None:
    loop = _make_loop()
    ctx = _make_ctx(loop, args="foo")
    result = await cmd_style(ctx)
    assert "Unknown subcommand" in result.content


# ---------------------------------------------------------------------------
# Graceful degradation when loop is missing _config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_style_graceful_when_no_config_on_loop() -> None:
    loop = SimpleNamespace()  # no _config
    ctx = _make_ctx(loop, args="")
    result = await cmd_style(ctx)
    assert "/style is unavailable" in result.content
