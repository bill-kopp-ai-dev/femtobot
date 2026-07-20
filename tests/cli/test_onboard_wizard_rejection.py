"""Regression guards for the ``femtobot onboard --wizard`` flag.

Bugs surfaced during the post-0.1.0-cli.1 audit:

  - Bug #27 — ``--wizard`` was silently a no-op. The CLI accepted
    the flag, did not print any prompt, and created the instance
    with defaults. Users who relied on the wizard got nothing.

  - Bug #28 — The nested ``run_onboard_wizard`` stub referenced
    ``config`` via ``"config" in dir()``, which works but is
    extremely fragile.

  - Bug #29 — The ``if wizard_result is not None`` branch that
    applied the wizard's config mutation was mis-indented
    (inside the ``else:`` block rather than at the if/elif
    level), so even if the wizard had returned a result, the
    updated config would never be applied.

These tests pin the fixed behaviour: ``--wizard`` exits with
code 2 and a helpful error message; running ``onboard`` without
the flag still works.
"""

from __future__ import annotations

import os
import subprocess
import sys


FEMTOBOT_DIR = "/home/bill/Codes/mcp-servers-percival/femtobot"


def test_onboard_wizard_exits_2_with_error_message() -> None:
    """``femtobot onboard --wizard`` must hard-error (exit 2).

    Regression guard for bug #27. The previous stub returned
    ``None`` and the flag was silently a no-op — the instance
    was created with defaults and no prompt was ever shown.
    """
    out = subprocess.run(
        [
            "uv",
            "run",
            "femtobot",
            "onboard",
            "--wizard",
            "--folder-path",
            "/tmp/femtobot-test-wiz-rejection",
            "--force",
        ],
        cwd=FEMTOBOT_DIR,
        env={**os.environ, "TERM": "dumb"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Hard-error with non-zero exit.
    assert out.returncode != 0, (
        f"--wizard must NOT exit 0 (silent no-op regression). Got:\n"
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )
    assert out.returncode == 2, (
        f"--wizard should exit with code 2 (EX_USAGE), got {out.returncode}.\n"
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )

    # Message must mention the wizard explicitly.
    combined = out.stdout + out.stderr
    assert "--wizard" in combined or "wizard" in combined.lower(), (
        f"Error message must mention the wizard. Got:\n{combined}"
    )

    # Message must NOT silently create the instance (the
    # previous no-op would print the "Creating instance at"
    # banner before exiting).
    assert "Creating instance at" not in combined, (
        f"onboard --wizard must NOT silently create the instance. Got:\n"
        f"{combined}"
    )


def test_onboard_without_wizard_succeeds() -> None:
    """Plain ``femtobot onboard`` must still work.

    Sanity check that the bug #27 fix didn't break the normal
    flow. We use ``--folder-path`` to write into a tmp
    location so we don't pollute the user's HOME.
    """
    out = subprocess.run(
        [
            "uv",
            "run",
            "femtobot",
            "onboard",
            "--folder-path",
            "/tmp/femtobot-test-plain-onboard",
            "--force",
        ],
        cwd=FEMTOBOT_DIR,
        env={**os.environ, "TERM": "dumb"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert out.returncode == 0, (
        f"Plain onboard must succeed. Got exit {out.returncode}.\n"
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )
    combined = out.stdout + out.stderr
    assert "Creating instance at" in combined, (
        f"onboard must print the creation banner. Got:\n{combined}"
    )
    assert "Next Steps" in combined or "initialized successfully" in combined, (
        f"onboard must print the success banner. Got:\n{combined}"
    )


def test_onboard_wizard_does_not_silently_no_op() -> None:
    """The previous stub returned ``None`` immediately.

    This structural test inspects ``commands.py`` source to ensure
    no nested ``def run_onboard_wizard(...): return None``
    stub remains, and that ``--wizard`` is hard-rejected with a
    typer.Exit.
    """
    from pathlib import Path

    src_path = Path(FEMTOBOT_DIR) / "femtobot/cli/commands.py"
    src = src_path.read_text(encoding="utf-8")

    # The bug #27 stub: a nested ``def run_onboard_wizard(...):
    # return None`` inside the ``onboard()`` body. The exact
    # substring ``return None`` immediately following
    # ``def run_onboard_wizard`` is the regression marker.
    import re

    pattern = r"def\s+run_onboard_wizard\([^)]*\)\s*:\s*#\s*type:\s*ignore.*?\n\s*return\s+None"
    assert not re.search(pattern, src, flags=re.DOTALL), (
        "Detected the no-op stub pattern in commands.py — the\n"
        "previous bug #27 fix removed the stub. Re-check that\n"
        "--wizard is hard-rejected with typer.Exit."
    )

    # The fix path: ``--wizard`` raises ``typer.Exit(code=2)``
    # with a clear error message.
    assert "typer.Exit(code=2)" in src, (
        "commands.py must contain a typer.Exit(code=2) for --wizard rejection."
    )
    assert "not available in 0.1.0-cli.1" in src, (
        "commands.py must mention '0.1.0-cli.1' in the wizard-rejection error."
    )
