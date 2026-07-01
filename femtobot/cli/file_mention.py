"""File-mention completer and parser for ``@``-prefixed paths.

Camada 1 (1.4) do ``FEMTOBOT_CLI_REFACTOR_PLAN.md``.

The completer activates only when the user types ``@`` followed by a
partial path. We intentionally avoid ``prompt_toolkit.completion.PathCompleter``
because it does not understand the ``@`` prefix and would activate on
every keystroke. The downstream consumer of the buffer is responsible
for recognizing the literal ``@path`` token and pre-loading its
contents via the ``read_file`` tool.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


# Match the last ``@<partial>`` before the cursor, with optional
# leading whitespace.  ``[^\s@]*`` keeps the match anchored at a single
# token boundary.
MENTION_PATTERN = re.compile(r"(?:^|\s)@(?P<path>[^\s@]*)$")


def find_active_mention(text_before_cursor: str) -> str | None:
    """Return the partial path under the active ``@``-mention, or None.

    >>> find_active_mention("hello @src/foo")
    'src/foo'
    >>> find_active_mention("no mention here")
    None
    >>> find_active_mention("trailing @")
    ''
    """
    if "@" not in text_before_cursor:
        return None
    match = MENTION_PATTERN.search(text_before_cursor)
    if not match:
        return None
    return match.group("path") or ""


def list_path_completions(
    partial: str, *, base_dir: Path | None = None
) -> Iterable[Path]:
    """Yield candidate paths for a ``@path`` mention.

    Falls back to current directory if ``partial`` is not absolute. Does
    NOT read file contents — only yields filesystem entries that match.
    """
    base = base_dir or Path.cwd()
    if not partial:
        # Listing the base directory itself.
        candidate = base
        prefix_name = ""  # empty prefix → list all entries
    elif partial.startswith("~"):
        candidate = Path(partial).expanduser()
        prefix_name = candidate.name
    elif partial.startswith("/"):
        candidate = Path(partial)
        prefix_name = candidate.name
    else:
        candidate = base / partial
        prefix_name = candidate.name

    parent = candidate if candidate.is_dir() else candidate.parent
    if not parent.exists() or not parent.is_dir():
        return
    try:
        for entry in sorted(parent.iterdir()):
            if not prefix_name or entry.name.startswith(prefix_name):
                yield entry
    except (PermissionError, OSError):
        return


class FileMentionCompleter(Completer):
    """prompt_toolkit completer that activates only after ``@`` tokens."""

    def __init__(self, base_dir: Path | None = None, max_results: int = 10):
        self._base = base_dir
        self._max = max_results

    def get_completions(self, document: Document, complete_event):
        partial = find_active_mention(document.text_before_cursor)
        if partial is None:
            return
        yielded = 0
        for path in list_path_completions(partial, base_dir=self._base):
            if yielded >= self._max:
                break
            yield Completion(  # type: ignore[name-defined]
                str(path),
                start_position=-len(partial),
                display=str(path),
                display_meta="dir" if path.is_dir() else "file",
            )
            yielded += 1
