"""Hard-error shim for the removed ``--ui compat`` flag (D4).

In 0.1.0-cli.1 the parity UI was removed entirely. The
``--ui compat`` flag now exits 64 (EX_USAGE) before any Typer
parsing begins. This is a hard-error — there is no graceful
fallback to the older ``ui_parity=off`` path because that would
silently downgrade users to a UX they did not choose.

Detection runs against ``sys.argv[1:]`` so the call works from
both ``python -m femtobot`` and ``femtobot agent --ui compat``.
Idempotent — safe to call multiple times.
"""

from __future__ import annotations

import sys
from typing import Sequence

EXIT_CODE = 64  # EX_USAGE per BSD sysexits(3)

_COMPAT_HELP = (
    "femtobot: --ui compat has been removed in 0.1.0-cli.1.\n"
    "The parity UI was the source of multiple TUI bugs across 0.1.0-ui.*.\n"
    "The 0.1.0-cli line ships only the canonical nanobot CLI baseline.\n"
    "Re-run without --ui compat; the default output is identical to\n"
    "the nanobot baseline.\n"
    "See CHANGELOG.md and plans/femtobot_nanobot_cli_migration/ "
    "for migration notes.\n"
)


def block_if_compat(argv: Sequence[str] | None = None) -> None:
    """Detect ``--ui compat`` *before* Typer parses anything.

    Exits with code 64 (EX_USAGE) if found. Catches both
    ``--ui compat`` and ``--ui=compat`` form, anywhere in argv.
    """
    args = list(argv if argv is not None else sys.argv[1:])

    for i, arg in enumerate(args):
        if arg == "--ui" and i + 1 < len(args) and args[i + 1] == "compat":
            _abort()
            return
        if arg.startswith("--ui=") and arg.split("=", 1)[1] == "compat":
            _abort()
            return


def _abort() -> None:
    sys.stderr.write(_COMPAT_HELP)
    sys.exit(EXIT_CODE)
