"""``history.jsonl`` BOM handling tests (v0.0.8 third-pass audit B4).

Audit B4: the default ``utf-8`` codec does not strip a leading
``\\ufeff`` (BOM).  When an external editor (or a tar/gzip export
that preserves BOM) saves ``history.jsonl`` with a leading BOM,
the very first line failed ``json.loads`` and the entire file was
silently dropped on load — losing the user's history.

The fix is to open with ``encoding="utf-8-sig"`` (auto-strip BOM)
or decode with the BOM-aware codec.

We pin:

* a BOM-prefixed ``history.jsonl`` is read in full,
* the first entry is not silently dropped,
* a non-BOM file still loads correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from femtobot.agent.memory import MemoryStore

pytestmark = pytest.mark.security


def _make_store(workspace: Path) -> MemoryStore:
    return MemoryStore(workspace)


def test_bom_prefixed_history_loads_in_full(tmp_path: Path) -> None:
    """B4: a BOM-prefixed ``history.jsonl`` is read in full (B4)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    memory_dir = ws / "memory"
    memory_dir.mkdir()
    history = memory_dir / "history.jsonl"
    entries = [
        {"role": "user", "content": "first message"},
        {"role": "assistant", "content": "first reply"},
        {"role": "user", "content": "second message"},
    ]
    # Write with a BOM at the start.
    with open(history, "wb") as f:
        f.write(b"\xef\xbb\xbf")  # UTF-8 BOM
        for e in entries:
            f.write((json.dumps(e) + "\n").encode("utf-8"))
    store = _make_store(ws)
    # ``_read_entries`` returns the parsed list of raw entries
    # (without cursor filtering).  We use this because the test
    # entries don't carry cursor metadata.
    loaded = list(store._read_entries())
    assert len(loaded) == 3
    assert loaded[0]["content"] == "first message"


def test_non_bom_history_still_loads(tmp_path: Path) -> None:
    """B4: a non-BOM file is unchanged by the fix (B4)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    memory_dir = ws / "memory"
    memory_dir.mkdir()
    history = memory_dir / "history.jsonl"
    entries = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    with open(history, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    store = _make_store(ws)
    loaded = list(store._read_entries())
    assert len(loaded) == 2
    assert loaded[0]["content"] == "hi"


def test_read_last_entry_works_with_bom(tmp_path: Path) -> None:
    """B4: ``_read_last_entry`` parses the last line of a BOM file (B4)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    memory_dir = ws / "memory"
    memory_dir.mkdir()
    history = memory_dir / "history.jsonl"
    last = {"role": "assistant", "content": "the final reply"}
    with open(history, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write((json.dumps({"role": "user", "content": "hi"}) + "\n").encode("utf-8"))
        f.write((json.dumps(last) + "\n").encode("utf-8"))
    store = _make_store(ws)
    result = store._read_last_entry()
    assert result is not None
    assert result["content"] == "the final reply"


def test_empty_history_file_returns_empty(tmp_path: Path) -> None:
    """B4: an empty file returns no entries (B4 baseline)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    memory_dir = ws / "memory"
    memory_dir.mkdir()
    history = memory_dir / "history.jsonl"
    history.touch()
    store = _make_store(ws)
    assert list(store._iter_valid_entries()) == []
    assert store._read_last_entry() is None
