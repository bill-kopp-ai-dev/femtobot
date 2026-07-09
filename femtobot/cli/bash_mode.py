"""Bash-mode for the CLI: lines starting with ``!`` are executed directly.

Output is captured locally and printed. The downstream REPL in
``cli/commands.py`` is responsible for the user-facing loop; this module
provides pure helpers (parse, run, format) that are easy to unit-test.

Camada 1 (1.3) do ``FEMTOBOT_CLI_REFACTOR_PLAN.md``.

Security note: this module uses ``asyncio.create_subprocess_shell`` which
inherits the Femtobot process's environment. The Femtobot policy layer
(``tools.exec`` + ``WorkspacePolicy``) is the authoritative gate; this
mode is a convenience for ad-hoc inspection only. Pass timeout via
``agents.cli.bashModeTimeoutS`` in config.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress
from dataclasses import dataclass

DEFAULT_TIMEOUT_S: float = 30.0
MAX_OUTPUT_BYTES: int = 32 * 1024


@dataclass
class BashRunResult:
    """Outcome of a bash-mode command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    elapsed_s: float
    timed_out: bool
    empty: bool


def looks_like_bash_mode(text: str) -> bool:
    """True if ``text`` is a bash-mode invocation (starts with ``!``)."""
    return text.lstrip().startswith("!")


def extract_command(text: str) -> str:
    """Strip the leading ``!`` and return the command to execute.

    Empty command after stripping is treated as invalid. ``!!`` and
    ``! !`` are returned verbatim — the caller dispatches to a
    history-based repeat.
    """
    stripped = text.lstrip()
    return stripped[1:].strip()


def is_repeat_request(text: str) -> bool:
    """True if user typed ``!!`` (repeat last bash command)."""
    return text.strip() in ("!!", "! !")


def parse_timeout(config: object | None) -> float:
    """Read timeout from active config or default to 30s.

    Reads ``agents.cli.bashModeTimeoutS`` (camelCase) or
    ``agents.cli.bash_mode_timeout_s`` (snake_case) from a pydantic
    Config, defaulting to :data:`DEFAULT_TIMEOUT_S`. Any failure falls
    back to the default.
    """
    try:
        cli_cfg = getattr(getattr(config, "agents", None), "defaults", None)
        cli_cfg = getattr(cli_cfg, "cli", None)
        val = float(getattr(cli_cfg, "bash_mode_timeout_s", DEFAULT_TIMEOUT_S))
        return max(1.0, val)
    except Exception:
        return DEFAULT_TIMEOUT_S


def _truncate(text: str) -> str:
    if len(text.encode("utf-8")) <= MAX_OUTPUT_BYTES:
        return text
    encoded = text.encode("utf-8")[:MAX_OUTPUT_BYTES]
    return encoded.decode("utf-8", errors="replace") + "\n... [truncated]"


async def run_bash_command(
    command: str, *, timeout_s: float = DEFAULT_TIMEOUT_S
) -> BashRunResult:
    """Execute ``command`` via ``asyncio.create_subprocess_shell``.

    Captures stdout/stderr, enforces a timeout, and truncates oversized
    output. Returns a :class:`BashRunResult`. Never raises — any
    exception is captured in ``stderr`` and ``exit_code = -1``.
    """
    if not command.strip():
        return BashRunResult(command, -1, "", "", 0.0, False, empty=True)

    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            timed_out = True
            with suppress(ProcessLookupError):
                proc.kill()
            stdout_b, stderr_b = b"", b"(timed out)"
        elapsed = time.monotonic() - t0
        stdout = _truncate(stdout_b.decode("utf-8", errors="replace"))
        stderr = _truncate(stderr_b.decode("utf-8", errors="replace"))
        return BashRunResult(
            command,
            proc.returncode if proc.returncode is not None else -1,
            stdout,
            stderr,
            elapsed,
            timed_out,
            False,
        )
    except Exception as exc:  # defensive
        return BashRunResult(
            command, -1, "", f"spawn error: {exc}", time.monotonic() - t0, False, False
        )


def format_bash_output(result: BashRunResult) -> str:
    """Format a :class:`BashRunResult` as a code-fenced block ready for display."""
    header = f"$ {result.command}"
    if result.timed_out:
        return f"{header}\n[timed out after {result.elapsed_s:.1f}s]"
    body = result.stdout
    if result.stderr:
        body = body + ("\n" if body else "") + f"[stderr]\n{result.stderr}"
    if result.exit_code != 0:
        body = body + ("\n" if body else "") + f"[exit {result.exit_code}]"
    return f"{header}\n{body}".rstrip()
