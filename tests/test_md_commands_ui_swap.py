"""Tests for the ``/ui`` hot-swap flag (PR 3.1 of the longlogs plan).

The bug fixed in PR 3.1: ``/ui off|compat|full`` mutated the in-memory
config but never rebuilt the active renderer, so the user could not
actually see the change. The fix is a one-line addition to the
``OutboundMessage.metadata`` returned by ``cmd_ui``:
``{"_rebuild_renderer": True}``. The CLI consumer in
``cli/commands._consume_outbound`` reads that flag and rebuilds the
renderer on the spot.

These tests assert that ``cmd_ui`` emits the flag (the CLI consumer
side is tested implicitly by the existing parity suite, since adding a
test for ``_consume_outbound`` would require standing up the full REPL).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from femtobot.command import builtin as cmd_module
from femtobot.command.router import CommandContext


class _FakeDefaults:
    bot_name = "Femtobot"
    bot_icon = ""

    class cli:
        class ui_parity:
            profile = "compat"


class _FakeAgents:
    defaults = _FakeDefaults()


class _FakeConfig:
    agents = _FakeAgents()


class _FakeLoop:
    _config = _FakeConfig()


def _ctx(args: str) -> CommandContext:
    msg = SimpleNamespace(channel="cli", chat_id="direct", metadata={}, content="/ui")
    return CommandContext(
        msg=msg,
        session=None,
        key="cli:direct",
        raw="/ui",
        args=args,
        loop=_FakeLoop(),
    )


def _run(coro):  # noqa: ANN001
    return asyncio.new_event_loop().run_until_complete(coro)


def test_cmd_ui_off_sets_rebuild_flag():
    out = _run(cmd_module.cmd_ui(_ctx("off")))
    assert out is not None
    assert out.metadata.get("_rebuild_renderer") is True
    assert "_FakeLoop__dict__" not in out.content  # no repr leakage


def test_cmd_ui_compat_sets_rebuild_flag():
    out = _run(cmd_module.cmd_ui(_ctx("compat")))
    assert out is not None
    assert out.metadata.get("_rebuild_renderer") is True


def test_cmd_ui_full_sets_rebuild_flag_and_warns():
    out = _run(cmd_module.cmd_ui(_ctx("full")))
    assert out is not None
    assert out.metadata.get("_rebuild_renderer") is True
    assert "full" in out.content.lower()


def test_cmd_ui_unknown_profile_does_not_set_rebuild_flag():
    out = _run(cmd_module.cmd_ui(_ctx("nope")))
    assert out is not None
    # No rebuild should happen when the profile is rejected.
    assert out.metadata.get("_rebuild_renderer") is None or (
        "_rebuild_renderer" not in out.metadata
    )


def test_cmd_ui_show_profile_does_not_set_rebuild_flag():
    out = _run(cmd_module.cmd_ui(_ctx("")))
    assert out is not None
    assert "Currently using" in out.content
    assert not out.metadata.get("_rebuild_renderer")
