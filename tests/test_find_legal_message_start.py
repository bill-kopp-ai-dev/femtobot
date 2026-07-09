"""``find_legal_message_start`` over-clearing fix tests (v0.1.0 fifth-pass I5).

Audit I5: the previous implementation called ``declared.clear()``
when it found an orphan tool result, throwing away legitimate
tool-call IDs that were declared *before* the orphan.  As a
result, valid tool results later in the list were also treated
as orphans and ``start`` kept advancing unnecessarily.

We pin:

* a single orphan at the end returns ``len(messages)`` (the
  standard "drop everything before the orphan" semantics),
* a single orphan in the middle followed by a valid tool
  result returns the position right after the orphan (not
  right after the valid result),
* a single orphan at the start followed by valid tool
  results returns 0 (the orphan is at index 0; the next
  message is index 1; but since declared IDs are *not*
  cleared, the valid results are recognized and start
  remains 0 after the orphan).
"""

from __future__ import annotations

from femtobot.utils.helpers import find_legal_message_start


def test_no_orphans_returns_zero() -> None:
    """I5: with no orphans, ``start`` is 0 (I5 baseline)."""
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1"}],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
    ]
    assert find_legal_message_start(msgs) == 0


def test_orphan_at_end_discards_everything() -> None:
    """I5: an orphan at the end discards everything (I5 baseline)."""
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1"}],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
        {"role": "tool", "tool_call_id": "ORPHAN", "content": "orphan"},
    ]
    assert find_legal_message_start(msgs) == 4  # index after the orphan


def test_orphan_in_middle_with_valid_results_after() -> None:
    """I5: orphan in middle, valid results after — start right after orphan (I5)."""
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1"}, {"id": "t2"}],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "result1"},
        {"role": "tool", "tool_call_id": "ORPHAN", "content": "orphan"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t3"}],
        },
        {"role": "tool", "tool_call_id": "t3", "content": "result3"},
    ]
    # The previous bug cleared ``declared`` at the ORPHAN,
    # so the assistant with t3 looked like an orphan and
    # start advanced to 6 (discarding valid messages).  The
    # fix preserves ``declared``, so t3 is recognized and
    # start is 4 (right after the ORPHAN at index 3).
    assert find_legal_message_start(msgs) == 4


def test_orphan_at_start_preserves_later_valid() -> None:
    """I5: orphan at the very start, valid later — start advances to 1 (I5)."""
    msgs = [
        {"role": "tool", "tool_call_id": "ORPHAN", "content": "orphan"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1"}],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
    ]
    # Orphan at index 0 → start = 1.  The fix preserves
    # ``declared`` so the assistant's t1 declaration is
    # recognized for index 2's tool result.
    assert find_legal_message_start(msgs) == 1


def test_multiple_orphans_advance_past_last() -> None:
    """I5: multiple orphans advance past the last one (I5)."""
    msgs = [
        {"role": "tool", "tool_call_id": "ORPHAN1", "content": "o1"},
        {"role": "tool", "tool_call_id": "ORPHAN2", "content": "o2"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1"}],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
    ]
    # Both orphans before any declaration: start = 2
    # (right after ORPHAN2).  The t1 declaration at index 2
    # matches the tool result at index 3.
    assert find_legal_message_start(msgs) == 2
