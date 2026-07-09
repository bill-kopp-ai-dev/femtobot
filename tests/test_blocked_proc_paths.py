"""``_is_blocked_device`` /proc blocking tests (v0.0.8 third-pass B7).

Audit B7: the device-blocklist regex only covered
``/proc/<pid>/fd/[012]`` and missed ``/proc/self/environ`` (which
contains the entire process environment, including API keys set
via ``export OPENAI_API_KEY=...``).  Reading it would leak every
secret the agent has access to.

The fix adds ``environ`` / ``maps`` / ``mem`` to the blocklist.

We pin:

* ``/proc/self/environ`` is blocked,
* ``/proc/1234/environ`` is blocked,
* ``/proc/self/maps`` is blocked,
* ``/proc/<pid>/mem`` is blocked,
* legitimate workspace files are not blocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from femtobot.agent.tools.filesystem import _is_blocked_device

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "raw_path",
    [
        "/proc/self/environ",
        "/proc/1234/environ",
        "/proc/self/maps",
        "/proc/1234/maps",
        "/proc/1234/mem",
    ],
)
def test_proc_environ_and_friends_are_blocked(raw_path: str) -> None:
    """B7: ``/proc/self/environ`` and friends are blocked (B7)."""
    assert _is_blocked_device(raw_path), f"{raw_path!r} should be blocked"


def test_workspace_files_are_not_blocked(tmp_path: Path) -> None:
    """B7: legitimate workspace files are not blocked (B7)."""
    real = tmp_path / "real.txt"
    real.write_text("hello")
    # The function should accept real files inside the workspace.
    assert not _is_blocked_device(str(real))


def test_symlink_to_environ_is_blocked(tmp_path: Path) -> None:
    """B7: a symlink that resolves to ``/proc/self/environ`` is blocked (B7)."""
    symlink = tmp_path / "sneaky"
    # On systems without /proc (e.g. macOS test env), skip.
    if not Path("/proc/self/environ").exists():
        pytest.skip("/proc not available on this platform")
    try:
        symlink.symlink_to("/proc/self/environ")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink not supported: {exc}")
    assert _is_blocked_device(symlink)
