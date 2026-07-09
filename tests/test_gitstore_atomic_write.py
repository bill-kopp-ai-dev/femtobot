"""``atomic_write_text`` durability tests (A7).

A7 (REFACTOR_PLAN.md Lote A): the dream cursor and
``history.jsonl`` writes go through ``atomic_write_text`` so a
crash mid-write can never leave a half-written file.  The temp-file
+ ``os.replace`` pattern is the contract; these tests pin it.

We test:

* a normal write lands the new content in *path*,
* no ``.tmp`` siblings are left behind after success,
* the file is created if it didn't exist,
* the parent directory is created when missing,
* raising mid-write cleans up the temp file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from femtobot.utils.gitstore import atomic_write_text

pytestmark = pytest.mark.durability


def _list_tmp_siblings(target: Path) -> list[Path]:
    """List ``target.name.*.tmp`` siblings in *target*'s directory."""
    return sorted(target.parent.glob(f"{target.name}.*.tmp"))


def test_writes_content_to_path(tmp_path: Path) -> None:
    """A7: ``atomic_write_text`` writes *content* verbatim to *path* (A7)."""
    p = tmp_path / "cursor.txt"
    atomic_write_text(p, "42\n")
    assert p.read_text(encoding="utf-8") == "42\n"


def test_creates_missing_file(tmp_path: Path) -> None:
    """A7: missing *path* is created (A7)."""
    p = tmp_path / "new.jsonl"
    assert not p.exists()
    atomic_write_text(p, "hello")
    assert p.exists()
    assert p.read_text(encoding="utf-8") == "hello"


def test_overwrites_existing_file(tmp_path: Path) -> None:
    """A7: an existing *path* is overwritten atomically (A7)."""
    p = tmp_path / "cursor.txt"
    p.write_text("old\n", encoding="utf-8")
    atomic_write_text(p, "new\n")
    assert p.read_text(encoding="utf-8") == "new\n"


def test_creates_missing_parent_directory(tmp_path: Path) -> None:
    """A7: ``mkdir(parents=True)`` for the parent dir (A7)."""
    p = tmp_path / "nested" / "deep" / "file.txt"
    assert not p.parent.exists()
    atomic_write_text(p, "x")
    assert p.parent.exists()
    assert p.read_text(encoding="utf-8") == "x"


def test_no_temp_siblings_after_success(tmp_path: Path) -> None:
    """A7: after a successful write, no ``.tmp`` siblings are left (A7).

    The temp-file pattern is the whole point — but if the cleanup
    were missing, the dir would accumulate ``cursor.txt.abc.tmp``
    files on every write.  This test pins the post-condition.
    """
    p = tmp_path / "history.jsonl"
    for i in range(5):
        atomic_write_text(p, f"line {i}\n")
    assert _list_tmp_siblings(p) == []


def test_no_temp_siblings_after_failed_write(tmp_path: Path) -> None:
    """A7: an exception during write cleans up the temp file (A7).

    We force an exception by writing to a non-writable directory
    AFTER the temp file is created.  Easier: monkey-patch
    ``os.replace`` to raise — the temp file should be unlinked
    in the ``except`` branch.
    """
    import unittest.mock as mock

    p = tmp_path / "history.jsonl"
    with mock.patch("femtobot.utils.gitstore.os.replace", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            atomic_write_text(p, "x")
    # All temp siblings are gone.
    assert _list_tmp_siblings(p) == []


def test_unicode_content_round_trip(tmp_path: Path) -> None:
    """A7: unicode (non-ASCII) content round-trips through the temp file (A7)."""
    p = tmp_path / "i18n.txt"
    atomic_write_text(p, "Olá, femtobot! 你好 🚀\n")
    assert p.read_text(encoding="utf-8") == "Olá, femtobot! 你好 🚀\n"


def test_empty_content_is_a_valid_write(tmp_path: Path) -> None:
    """A7: writing an empty string is fine and produces a 0-byte file (A7)."""
    p = tmp_path / "empty.txt"
    atomic_write_text(p, "")
    assert p.exists()
    assert p.read_text(encoding="utf-8") == ""
    assert p.stat().st_size == 0


def test_replace_keeps_inode_when_possible(tmp_path: Path) -> None:
    """A7: a successful write leaves the directory clean (A7).

    We can't assert the inode stays the same (POSIX
    ``os.replace`` is allowed to swap inodes), but we *can* assert
    the directory has no leftover temp files.
    """
    p = tmp_path / "k.txt"
    atomic_write_text(p, "v1")
    atomic_write_text(p, "v2")
    atomic_write_text(p, "v3")
    assert _list_tmp_siblings(p) == []
    assert p.read_text(encoding="utf-8") == "v3"
