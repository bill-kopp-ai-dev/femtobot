"""Repro the longlogs.txt Opção 1 duplication bug.

Hypothesis: after ``on_end`` prints the final buffer, a late ``on_delta``
call re-renders the same buffer to ``self._buf`` because ``_buf += delta``
is unconditional. The fix: gate ``on_delta`` with ``_ended`` and clear
``_buf`` after the final print.
"""
import sys

import pytest

sys.path.insert(0, "/home/bill/Codes/CLI-router-project/femtobot")

from femtobot.cli.stream import StreamRenderer


@pytest.fixture
def renderer():
    # No console capture needed — we assert on internal buffer state and
    # behaviour, not the rendered string. The original bug was a duplicate
    # ``on_delta`` that re-accumulated into ``_buf`` after ``on_end`` had
    # printed it; the fix swaps that accumulation for a guard flag and a
    # post-print buffer reset.
    return StreamRenderer(
        bot_name="test",
        bot_icon="",
        show_spinner=False,
    )


@pytest.mark.asyncio
async def test_post_end_delta_does_not_re_accumulate(renderer):
    content = (
        "Já fiz essa busca. Vou trazer as 2 opções:\n"
        "## Opção 1 — Bolo de goiaba\n"
        "Ingredientes: 2 xícaras, 3 ovos.\n"
        "## Opção 2 — Bolo Romeu e Julieta\n"
        "Ingredientes: 300g goiabada."
    )

    # First pass: chunks then on_end (mimics a real streamed turn)
    for i in range(0, len(content), 10):
        await renderer.on_delta(content[i:i+10])
    await renderer.on_end()

    assert renderer._ended is True, "after on_end, _ended must be set"
    assert renderer._buf == "", "after on_end, _buf must be cleared"

    # Second pass: same content arrives AGAIN as a trailing body.
    for i in range(0, len(content), 10):
        await renderer.on_delta(content[i:i+10])

    assert renderer._buf == "", (
        "post-end on_delta must NOT re-accumulate — would cause duplicate render"
    )


@pytest.mark.asyncio
async def test_close_resets_ended_for_next_turn(renderer):
    content1 = "Hello from turn 1. ## Opção 1\n- a\n- b"
    content2 = "Hello from turn 2. ## Opção 2\n- c\n- d"

    for i in range(0, len(content1), 10):
        await renderer.on_delta(content1[i:i+10])
    await renderer.on_end()
    assert renderer._ended is True

    await renderer.close()
    assert renderer._ended is False, "close() must reset _ended for next turn"
    assert renderer._buf == "", "close() must reset _buf"

    # Now the next turn can stream again.
    for i in range(0, len(content2), 10):
        await renderer.on_delta(content2[i:i+10])
    await renderer.on_end()

    assert "Opção 1" in renderer._buf or renderer._buf == ""
    # The second-turn buffer should be cleared by on_end (per fix).


@pytest.mark.asyncio
async def test_resuming_on_end_does_not_swallow_next_delta(renderer):
    """on_end(resuming=True) must not latch ``_ended``.

    Regression: the original ``_ended`` fix set the flag unconditionally
    in ``on_end``, including for ``resuming=True`` — the signal the
    runner sends between tool-call iterations of the *same* turn before
    it streams the model's follow-up answer. Latching there silently
    dropped every post-tool-call delta for the rest of the turn.
    """
    await renderer.on_delta("Let me check that for you.")
    await renderer.on_end(resuming=True)
    assert renderer._ended is False, (
        "on_end(resuming=True) must not latch _ended — more deltas follow "
        "in the same turn (after tool calls)"
    )

    await renderer.on_delta("Done, the answer is 42.")
    assert renderer._buf == "Done, the answer is 42.", (
        "post-resume delta must accumulate — it is new content, not a "
        "duplicate of the pre-tool-call buffer"
    )
    await renderer.on_end()
    assert renderer._ended is True


@pytest.mark.asyncio
async def test_stop_for_input_resets_ended_for_next_turn(renderer):
    """A second streamed turn must render even though ``close()`` is
    never called between turns on the streamed path (the CLI REPL only
    calls ``close()`` when nothing streamed at all — see
    ``commands.py``'s ``elif renderer and not renderer.streamed``).
    ``stop_for_input()`` is what the REPL calls once per turn instead.
    """
    await renderer.on_delta("Turn one answer.")
    await renderer.on_end()
    assert renderer._ended is True

    renderer.stop_for_input()
    assert renderer._ended is False

    await renderer.on_delta("Turn two answer.")
    assert renderer._buf == "Turn two answer.", (
        "second turn must stream normally, not be swallowed by a stale "
        "_ended latch from turn one"
    )
