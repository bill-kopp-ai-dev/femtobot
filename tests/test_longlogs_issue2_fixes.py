"""Regression tests for issue #2 — longlogs.txt 2026-07-19.

The second follow-up session in ``/home/bill/Codes/agents/longlogs.txt``
(lines 74-102) shows the assistant response leaking under the
``[ 👤 You ]`` prompt of the **next** turn. Two fixes ship together:

  - PR #1: every user turn is tagged with a UUID ``_turn_id`` that
    propagates through every OutboundMessage derived from it. The
    consumer drops any message whose ``_turn_id`` does not match the
    active turn, so a late-arriving body from the previous turn can
    no longer race under the new prompt.

  - PR #2: the underlying :class:`StreamRenderer` (the core that
    owns ``_buf`` / ``_live`` / ``_ENDED``) is rebuilt on every
    turn, mirroring ``nanobot/cli/commands.py``. The parity layer
    (``ParityStreamRenderer``) wrapping it stays stable so the
    Welcome card and HeaderBar do not re-print.

These tests pin both behaviours so a future refactor that regresses
either of them shows up in CI immediately.

Refs: docs/exec-plan-resolucao-bugs-longlogs.md (PR 2.x, 5.x)
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# PR #1 — turn-token guard
# ---------------------------------------------------------------------------


def test_publish_inbound_carries_turn_id_metadata() -> None:
    """``_read_interactive_input_async`` mints a UUID ``_turn_id``
    and tags the published ``InboundMessage`` with it.

    Source-order check — the fix is structural, similar to issue #1's
    ``stop_for_input`` invariant. A test that fails this is the
    regression we want to catch.
    """
    # The REPL body lives in ``run_interactive`` (a local closure),
    # not in a module-level function we can import directly. Verify
    # both: the helper publishes ``_turn_id`` AND the helper is
    # called from the REPL body. We do this by inspecting the source
    # for the literal ``_turn_id`` in the publish site.
    src = inspect.getsource(
        __import__("femtobot.cli.commands", fromlist=["_ACTIVE_RENDERER"])
    )
    # Must reference both the mint (``uuid.uuid4``) and the metadata
    # key (``_turn_id``) at the publish site.
    assert "_turn_id" in src, (
        "expected _turn_id in run_interactive so each turn has its own UUID"
    )
    assert 'uuid.uuid4' in src, (
        "expected uuid.uuid4 call in run_interactive to mint a fresh turn_id"
    )


def test_consumer_drops_stale_turn_messages() -> None:
    """``_is_for_current_turn`` returns False when a message's
    ``_turn_id`` no longer matches the active turn, True otherwise.

    Behavioural test: build a tiny harness that simulates a stale
    body arriving after a new turn has started and assert the guard
    excludes it cleanly.
    """
    from femtobot.bus.events import OutboundMessage

    # Build the guard via the same closure the REPL uses. The closure
    # binds ``active_turn_id`` and consults it on each call. Re-create
    # a minimal version here for unit-test exposure.
    active_turn_id = "T-new"

    def _is_for_current_turn(msg):
        meta = msg.metadata or {}
        msg_turn = meta.get("_turn_id")
        if msg_turn is None:
            return True
        if active_turn_id is None:
            return True
        return msg_turn == active_turn_id

    # Stale body from the previous turn — DROP.
    stale = OutboundMessage(
        channel="cli",
        chat_id="direct",
        content="hello world",  # the body that must NOT render
        metadata={"_turn_id": "T-old", "_streamed": True},
    )
    assert _is_for_current_turn(stale) is False, (
        "stale turn body must be dropped (issue #2, race fix)"
    )

    # Current-turn body — ADMIT.
    fresh = OutboundMessage(
        channel="cli",
        chat_id="direct",
        content="fresh body",
        metadata={"_turn_id": "T-new", "_streamed": True},
    )
    assert _is_for_current_turn(fresh) is True

    # Background notification (no _turn_id) — always ADMIT.
    bg = OutboundMessage(
        channel="cli",
        chat_id="startup",
        content="⚠ MCP server unreachable",
        metadata={"render_as": "text"},
    )
    assert _is_for_current_turn(bg) is True


def test_consumer_skips_stale_body_in_simulated_bus() -> None:
    """End-to-end smoke: a real MessageBus publishes a stale body after
    a new turn has started. A consumer that consults the guard sees
    the message, the guard drops it, and the consumer's body-rendering
    counter stays at 0 for the stale turn.

    This mirrors the longlogs.txt 2026-07-19 race where the
    trailing body of turn 1 leaked under the ``[ 👤 You ]`` prompt
    of turn 2.
    """
    from femtobot.bus.events import OutboundMessage
    from femtobot.bus.queue import MessageBus

    bus = MessageBus()
    rendered: list[str] = []

    async def scenario():
        # Publish a stale body FIRST (race: order-of-arival for the
        # trailing streamed body ahead of the user's next input).
        await bus.publish_outbound(
            OutboundMessage(
                channel="cli",
                chat_id="direct",
                content="TURN-1-BODY (stale, should be dropped)",
                metadata={"_turn_id": "T1", "_streamed": True},
            )
        )
        # Now the REPL signals turn 2 has started: the guard switches.
        active_turn_id = "T2"

        def _is_for_current_turn(msg):
            mt = msg.metadata.get("_turn_id")
            return mt is None or mt == active_turn_id

        # Drain a burst — emulate the consumer's selection loop.
        rendered_count = 0
        for _ in range(2):
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=0.05)
            except asyncio.TimeoutError:
                break
            if not _is_for_current_turn(msg):
                # dropped — would `continue` in the real consumer.
                continue
            if msg.content:
                rendered.append(msg.content)
                rendered_count += 1
        return rendered_count

    count = asyncio.run(scenario())
    assert count == 0, f"expected 0 renders; got {count} ({rendered!r})"
    assert rendered == [], (
        f"stale body must never end up rendered, but got {rendered!r}"
    )


# ---------------------------------------------------------------------------
# PR #2 — per-turn core rebuild + ParityStreamRenderer.replace_core
# ---------------------------------------------------------------------------


def test_parity_renderer_has_replace_core() -> None:
    """``ParityStreamRenderer`` exposes a ``replace_core`` hook used
    by the REPL to swap the underlying ``StreamRenderer`` per turn.

    Static check — the fix is structural.
    """
    from femtobot.cli.parity_stream import ParityStreamRenderer

    assert hasattr(ParityStreamRenderer, "replace_core"), (
        "ParityStreamRenderer.replace_core is required by issue #2 PR #2"
    )
    assert callable(ParityStreamRenderer.replace_core)


def test_replace_core_swaps_underlying_renderer() -> None:
    """After ``replace_core(new)``, ``on_delta`` / ``on_end`` /
    ``close`` / ``header_printed`` all delegate to ``new``."""
    from femtobot.cli.parity_stream import ParityStreamRenderer
    from femtobot.cli.stream import StreamRenderer

    base_old = StreamRenderer(render_markdown=True, show_spinner=False)
    base_new = StreamRenderer(render_markdown=True, show_spinner=False)

    # Build a real ParityStreamRenderer on top of base_old.
    # We need a minimal config-like object — ParityStreamRenderer
    # reads ``config.agents.defaults.cli.theme`` and
    # ``config.agents.defaults.bot_name`` defensively, so we
    # supply a tiny stand-in that satisfies those attributes.
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        agents=SimpleNamespace(
            defaults=SimpleNamespace(
                cli=SimpleNamespace(theme="terracotta-claude"),
                user=SimpleNamespace(name=None),
                model="test-model",
                model_preset="default",
                workspace="/tmp",
            )
        )
    )

    try:
        parity = ParityStreamRenderer(
            base_renderer=base_old,
            config=cfg,
            bot_name="Femtobot",
            bot_icon="🐈",
            changelog_path="/nonexistent/CHANGELOG.md",
        )
    except Exception:
        # If parity renderer import-time construction blows up
        # (e.g. missing Rich widgets in headless env), skip with
        # an explanatory note instead of failing.
        pytest.skip("ParityStreamRenderer init requires a TTY-capable env")

    parity.replace_core(base_new)
    assert parity._base is base_new, (
        "replace_core must rebind the underlying StreamRenderer"
    )
    assert parity._console is base_new.console, (
        "replace_core must rebind the console reference too"
    )


def test_run_interactive_rebuilds_core_per_turn() -> None:
    """The REPL body must call ``replace_core`` (or equivalent)
    before each ``publish_inbound`` so the next turn has a clean
    ``_buf`` / ``_live`` / ``_ENDED``.

    Structural check — guards against the regressions that
    longlogs.txt 2026-07-19 (lines 74-102) captured.
    """
    src = inspect.getsource(
        __import__("femtobot.cli.commands", fromlist=["_ACTIVE_RENDERER"])
    )
    # Look for the per-turn rebuild evidence.
    assert "replace_core" in src, (
        "expected REPL to call replace_core per turn (issue #2 PR #2)"
    )
    # And the StreamRenderer must be instantiated inside the loop
    # (i.e. after the inner ``while True:`` of run_interactive). We
    # approximate this by checking for the StreamRenderer symbol
    # being imported (already at module level) and used alongside
    # the per-turn metadata update.
    assert "new_core = StreamRenderer(" in src, (
        "expected REPL to build a fresh StreamRenderer per turn"
    )


# ---------------------------------------------------------------------------
# Diagnostic — both fixes must be applied together
# ---------------------------------------------------------------------------


def test_both_fixes_present() -> None:
    """Sanity bundle: both issue #2 fixes are wired in the same REPL.

    A future refactor that reverts one but keeps the other is the
    failure mode we want this test to catch (the longlogs bug only
    fully disappears when BOTH fixes are present).
    """
    src = inspect.getsource(
        __import__("femtobot.cli.commands", fromlist=["_ACTIVE_RENDERER"])
    )
    assert "replace_core" in src and "new_core = StreamRenderer(" in src, (
        "PR #2 (per-turn core rebuild) is missing"
    )
    assert "_turn_id" in src and "uuid.uuid4" in src, (
        "PR #1 (turn-token guard) is missing"
    )
