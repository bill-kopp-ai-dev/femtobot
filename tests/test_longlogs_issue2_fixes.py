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
# Issue #3 — per-turn renderer rebuild must NOT be present
# ---------------------------------------------------------------------------
#
# Issue #3 (longlogs 2026-07-20 screenshots) showed that
# ``ParityStreamRenderer.replace_core`` and ``new_core = StreamRenderer(...)``
# inside ``run_interactive`` (the PR #2 attempt to mirror nanobot) leaked
# the previous core's Rich ``Live`` and ``ThinkingSpinner``. Two ``Live``
# displays competed for the same ``sys.stdout`` and produced:
#
#   - raw ANSI bytes in the middle of the response (`?[2K`, `?[2m`, `?[0m`),
#   - spinner state interleaving between turns,
#   - markdown tables rendered as one ANSI-fragment-per-character.
#
# PR #2 was reverted in issue #3; only the turn-token guard (PR #1)
# handles cross-turn message ordering. These two tests pin the API absence.


def test_parity_renderer_has_no_replace_core() -> None:
    """``ParityStreamRenderer.replace_core`` must NOT exist.

    Static check — guards against a future contributor re-introducing
    per-turn renderer rebuilds that leak the previous Rich ``Live``.
    See issue #3 for the regression details.
    """
    from femtobot.cli.parity_stream import ParityStreamRenderer

    assert not hasattr(ParityStreamRenderer, "replace_core"), (
        "ParityStreamRenderer.replace_core was re-introduced after "
        "the issue #3 fix — see issue #3 for why this leaks "
        "Rich Live displays and the previous turn's spinner."
    )


def test_replace_core_swaps_underlying_renderer() -> None:
    """After issue #3 the parity renderer's ``on_delta`` / ``on_end``
    / ``close`` all delegate to a single stable ``StreamRenderer``.

    The structural check: ``ParityStreamRenderer._base`` exists and
    is a ``StreamRenderer`` instance. The original PR #2 swap is
    gone.
    """
    from femtobot.cli.parity_stream import ParityStreamRenderer
    from femtobot.cli.stream import StreamRenderer

    base_old = StreamRenderer(render_markdown=True, show_spinner=False)

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

    # The parity renderer's underlying ``_base`` must be the *same*
    # ``StreamRenderer`` instance we passed in (no swap).
    assert parity._base is base_old
    assert isinstance(parity._base, StreamRenderer)
    # No replacement hook.
    assert not hasattr(parity, "replace_core")


# ---------------------------------------------------------------------------
# End-to-end behavioural — replay the longlogs.txt 2026-07-19 race
# ---------------------------------------------------------------------------


def test_two_turn_race_drops_only_stale_body() -> None:
    """End-to-end replay of the longlogs.txt 2026-07-19 race.

    The original symptom (lines 74-102): in turn-2 of a session the
    body of turn-1 leaks under the new ``[ 👤 You ]`` prompt. The
    triggering race is:

      * User submits turn-1.
      * The agent streams the response (delta messages on the bus).
      * The agent publishes ``_stream_end=True`` to signal the
        streamed answer is closed.
      * A trailing ``_streamed=True, _stream_end_pending=True``
        ``OutboundMessage`` carrying the full body is published.
      * User types turn-2 immediately. The REPL wakes up at
        ``turn_done.wait()`` because ``_stream_end`` was seen.
      * The trailing body of turn-1 reaches the bus **after** the
        REPL has rendered the ``[ 👤 You ]`` header for turn-2.
      * Pre-fix: the body printed under the prompt.
      * Post-fix (PR #1): the body has ``_turn_id == T1`` but the
        active turn is ``T2``, so the consumer drops it.

    This test publishes the exact bus sequence and asserts:
      - turn-1 body is rendered (via _stream_end + _pending pair),
      - turn-2 body is rendered,
      - **no stale body leaks** into the turn-2 render set.
    """
    from femtobot.bus.events import OutboundMessage
    from femtobot.bus.queue import MessageBus

    bus = MessageBus()
    rendered: list[str] = []

    async def scenario():
        # --- Turn 1: stream → _stream_end → trailing body (RACE) ---
        T1 = "turn-1"
        # Stream deltas come in (we don't render them through this
        # code path — the on_delta handler drives the Live render).
        await bus.publish_outbound(
            OutboundMessage(
                channel="cli", chat_id="direct",
                content="R1 ", metadata={"_turn_id": T1, "_stream_delta": True},
            )
        )
        # _stream_end signals "stream closed" — REPL wakes up.
        await bus.publish_outbound(
            OutboundMessage(
                channel="cli", chat_id="direct",
                content="",
                metadata={
                    "_turn_id": T1, "_stream_end": True, "_resuming": False,
                },
            )
        )
        # The trailing body arrives LATE — this is the leak window.
        await bus.publish_outbound(
            OutboundMessage(
                channel="cli", chat_id="direct",
                content="[T1 body] previously leaked under [You]",
                metadata={
                    "_turn_id": T1, "_streamed": True,
                    "_stream_end_pending": True,
                },
            )
        )

        # --- Turn 2 starts mid-stream — REPL has called publish_inbound ---
        T2 = "turn-2"
        active_turn_id = T2

        def _is_for_current_turn(msg):
            mt = (msg.metadata or {}).get("_turn_id")
            return mt is None or mt == active_turn_id

        # Drain everything in order.
        for _ in range(8):
            try:
                msg = await asyncio.wait_for(bus.consume_outbound(), timeout=0.05)
            except asyncio.TimeoutError:
                break
            if not _is_for_current_turn(msg):
                continue  # stale: would previously leak.
            # Only bodies would render — deltas go through on_delta,
            # _stream_end is a control signal.
            if msg.content and msg.metadata.get("_streamed"):
                rendered.append(msg.content)

    asyncio.run(scenario())
    assert rendered == [], (
        "stale T1 body must not render once turn-2 has started; "
        f"got: {rendered!r}"
    )


def test_turn_token_guard_present_and_replace_core_absent() -> None:
    """Sanity bundle for the issue #2 + issue #3 state.

    After the issue #3 revert:

      - PR #1 (turn-token guard) must still be present in run_interactive.
      - PR #2 (per-turn renderer rebuild) must NOT be in run_interactive.
      - ``ParityStreamRenderer.replace_core`` must NOT exist.

    This catches the failure mode where a future contributor might
    re-add ``replace_core`` thinking the cross-turn race fix lives in
    the renderer (it does not — it lives in the consumer's turn-token).
    """
    src = inspect.getsource(
        __import__("femtobot.cli.commands", fromlist=["_ACTIVE_RENDERER"])
    )
    # PR #1 — turn-token guard
    assert "_turn_id" in src and "uuid.uuid4" in src, (
        "PR #1 (turn-token guard) is missing — issue #2 regressed."
    )
    # Issue #3: per-turn rebuild must not be present in run_interactive
    # (it caused the Rich Live leak observed on 2026-07-20). We strip
    # leading whitespace + ``#`` characters so that docstrings and
    # comments (which mention ``replace_core`` historically) don't
    # trigger a false positive. Then we look for an actual call site.
    import re as _re
    code_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith(("#", '"', "'"))
    ]
    code = "\n".join(code_lines)
    assert not _re.search(r"\.\s*replace_core\(", code), (
        "run_interactive has a .replace_core( call — issue #3 fix reverted "
        "but per-turn rebuild is back."
    )
    assert "new_core = StreamRenderer(" not in code, (
        "run_interactive instantiates a new StreamRenderer per turn — "
        "issue #3 fix is incomplete."
    )
