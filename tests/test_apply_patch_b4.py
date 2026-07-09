"""apply_patch B4 regression: line-separated additions are preserved (B4).

Before B4 (ref: nanobot v0.2.2 #4266) the ``add`` action could collapse
multiple lines of ``new_text`` into a single line, breaking shell
scripts and Markdown that depend on exact line boundaries.  B4 (in
REFACTOR_PLAN.md Lote B) audits / hardens the existing implementation
so that ``add`` preserves every ``\\n`` in ``new_text`` exactly as
sent, with the trailing ``\\n`` kept when present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from femtobot.agent.tools.apply_patch import ApplyPatchTool

pytestmark = [pytest.mark.durability, pytest.mark.asyncio]


def _tool(tmp_path: Path, *, restrict: bool = False) -> ApplyPatchTool:
    workspace = tmp_path
    return ApplyPatchTool(workspace=workspace, restrict_to_workspace=restrict)


async def test_add_preserves_multiline_new_text(tmp_path: Path) -> None:
    """B4: adding a 2-line block to a new file results in 2 lines (B4)."""
    tool = _tool(tmp_path)
    new_text = "# header\n# body\n"
    edits = [
        {
            "path": "newfile.md",
            "action": "add",
            "new_text": new_text,
        }
    ]
    res = await tool.execute(edits=edits)
    assert "Error" not in res, f"apply_patch failed: {res}"
    out = (tmp_path / "newfile.md").read_text(encoding="utf-8")
    # Two distinct lines must remain (not collapsed into one).
    assert out.splitlines() == ["# header", "# body"]


async def test_add_preserves_trailing_newline(tmp_path: Path) -> None:
    """B4: trailing ``\\n`` in ``new_text`` is kept as-is (B4)."""
    tool = _tool(tmp_path)
    new_text = "line1\nline2\n"
    edits = [{"path": "with_newline.txt", "action": "add", "new_text": new_text}]
    await tool.execute(edits=edits)
    out = (tmp_path / "with_newline.txt").read_bytes()
    assert out == b"line1\nline2\n"


async def test_add_preserves_3_plus_lines(tmp_path: Path) -> None:
    """B4: a longer block keeps all its lines, no collapse (B4)."""
    tool = _tool(tmp_path)
    block = "a\nb\nc\nd\ne\n"
    edits = [{"path": "long.txt", "action": "add", "new_text": block}]
    await tool.execute(edits=edits)
    out = (tmp_path / "long.txt").read_text(encoding="utf-8")
    assert out.splitlines() == ["a", "b", "c", "d", "e"]


async def test_add_preserves_internal_blank_line(tmp_path: Path) -> None:
    """B4: blank lines (consecutive ``\\n\\n``) are kept (B4)."""
    tool = _tool(tmp_path)
    block = "para1\n\npara2\n"
    edits = [{"path": "paragraphs.txt", "action": "add", "new_text": block}]
    await tool.execute(edits=edits)
    out = (tmp_path / "paragraphs.txt").read_text(encoding="utf-8")
    assert out.splitlines() == ["para1", "", "para2"]


async def test_add_to_existing_file_appends_lines(tmp_path: Path) -> None:
    """B4: ``add`` to an existing file appends ``new_text`` lines (B4).

    When the file already exists, ``add`` falls through to the
    ``update`` path.  Make sure the appended lines land on their own
    lines (no in-line merge with the last existing line).
    """
    existing = tmp_path / "existing.txt"
    existing.write_text("first\n", encoding="utf-8")
    tool = _tool(tmp_path)
    edits = [{"path": "existing.txt", "action": "add", "new_text": "second\nthird\n"}]
    await tool.execute(edits=edits)
    out = existing.read_text(encoding="utf-8")
    assert out.splitlines() == ["first", "second", "third"]
