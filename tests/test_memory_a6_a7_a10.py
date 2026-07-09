"""Memory durability / monotonic-cursor / corruption tests (A6, A7, A10).

A6 (REFACTOR_PLAN.md Lote A): the dream cursor now advances only AFTER the
git commit succeeds.  A failed commit (or no commit because nothing
changed) leaves the cursor behind and the next Dream cycle reprocesses.

A7: ``set_last_dream_cursor`` writes through ``atomic_write_text`` so a
crash mid-write can never leave a partially-written cursor file.

A10: malformed JSONL lines are skipped with a one-shot warning that
names the line index.  External writers that regress the on-disk cursor
trigger a loud refusal + ValueError so the regression is caught instead
of silently corrupting downstream.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from femtobot.agent.memory import MemoryStore

pytestmark = pytest.mark.security


def _make_store(workspace: Path) -> MemoryStore:
    # Bypass __init__ side-effects (git init, .env scan) by skipping them:
    # the tests below only need ``_dream_cursor_file`` / ``_cursor_file``
    # / ``_enforce_monotonic_cursor`` / ``_read_entries``.
    store = MemoryStore.__new__(MemoryStore)
    store.workspace = workspace
    store.memory_dir = workspace / "memory"
    store.memory_dir.mkdir(parents=True, exist_ok=True)
    store._cursor_file = store.memory_dir / ".cursor"
    store._dream_cursor_file = store.memory_dir / ".dream_cursor"
    store.history_file = store.memory_dir / "history.jsonl"
    store._corruption_logged = False
    store._malformed_history_logged = False
    store._oversize_logged = False
    store._append_lock = __import__("threading").Lock()
    return store


def test_set_last_dream_cursor_atomic(tmp_path: Path) -> None:
    """A7: ``set_last_dream_cursor`` is atomic — the file is fully written or not at all."""
    store = _make_store(tmp_path)
    store.set_last_dream_cursor(42)
    # No .tmp files should remain after the write completes.
    leftovers = list(store._dream_cursor_file.parent.glob(".dream_cursor.*.tmp"))
    assert not leftovers, f"atomic write left tmp files: {leftovers}"
    assert store._dream_cursor_file.read_text(encoding="utf-8") == "42"


def test_set_last_dream_cursor_overwrites(tmp_path: Path) -> None:
    """A7: subsequent writes fully replace the previous value."""
    store = _make_store(tmp_path)
    store.set_last_dream_cursor(1)
    store.set_last_dream_cursor(2)
    assert store._dream_cursor_file.read_text(encoding="utf-8") == "2"


def test_enforce_monotonic_cursor_accepts_increasing(tmp_path: Path) -> None:
    """A10: increasing cursors are accepted."""
    store = _make_store(tmp_path)
    store._enforce_monotonic_cursor(1)
    store._enforce_monotonic_cursor(2)
    store._enforce_monotonic_cursor(100)


def test_enforce_monotonic_cursor_rejects_regression(tmp_path: Path) -> None:
    """A10: a regression is refused with ValueError (A10)."""
    store = _make_store(tmp_path)
    store._cursor_file.write_text("100", encoding="utf-8")
    with pytest.raises(ValueError, match="Cursor regression"):
        store._enforce_monotonic_cursor(50)


def test_read_entries_skips_malformed_lines(tmp_path: Path) -> None:
    """A10: malformed JSONL lines are skipped without crashing (A10)."""
    store = _make_store(tmp_path)
    lines = [
        json.dumps({"cursor": 1, "timestamp": "2024-01-01 10:00", "content": "ok"}),
        "{not valid json",
        json.dumps({"cursor": 2, "timestamp": "2024-01-01 11:00", "content": "also ok"}),
        "",  # blank line is allowed
    ]
    store.history_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    entries = store._read_entries()
    cursors = [e["cursor"] for e in entries]
    assert cursors == [1, 2]
