"""Tests for the file-mention completer."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.document import Document

from femtobot.cli.file_mention import (
    FileMentionCompleter,
    find_active_mention,
    list_path_completions,
)


def test_find_active_mention_no_at() -> None:
    assert find_active_mention("no mention here") is None


def test_find_active_mention_simple() -> None:
    assert find_active_mention("hello @src/foo") == "src/foo"


def test_find_active_mention_trailing_at() -> None:
    assert find_active_mention("trailing @") == ""


def test_find_active_mention_middle_of_word_ignored() -> None:
    """``foo@bar`` must NOT trigger mention logic."""
    assert find_active_mention("foo@bar") is None


def test_list_path_completions_returns_children(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("")
    (tmp_path / "beta").mkdir()
    (tmp_path / "gamma.py").write_text("")
    results = sorted(p.name for p in list_path_completions("", base_dir=tmp_path))
    assert results == ["alpha.txt", "beta", "gamma.py"]


def test_list_path_completions_filters_by_prefix(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("")
    (tmp_path / "anvil.py").write_text("")
    (tmp_path / "zebra.py").write_text("")
    results = sorted(p.name for p in list_path_completions("a", base_dir=tmp_path))
    assert results == ["alpha.txt", "anvil.py"]


def test_list_path_completions_nonexistent_dir(tmp_path: Path) -> None:
    """A non-existent parent must yield no completions, not raise."""
    results = list(list_path_completions("nope/xyz", base_dir=tmp_path))
    assert results == []


def test_file_mention_completer_off_when_no_at() -> None:
    c = FileMentionCompleter()
    doc = Document(text="plain text", cursor_position=len("plain text"))
    assert list(c.get_completions(doc, None)) == []


def test_file_mention_completer_active_with_at(tmp_path: Path) -> None:
    (tmp_path / "alpha.txt").write_text("")
    (tmp_path / "beta.py").write_text("")
    c = FileMentionCompleter(base_dir=tmp_path, max_results=5)
    doc = Document(text="see @", cursor_position=len("see @"))
    completions = list(c.get_completions(doc, None))
    assert completions  # non-empty
    # display_meta is a FormattedText; just check the rendered string contains "file".
    for comp in completions:
        # Rich text format: list of (style, text) tuples
        text = "".join(
            frag[1] for frag in comp.display_meta if isinstance(frag, tuple)
        )
        assert text == "file"
