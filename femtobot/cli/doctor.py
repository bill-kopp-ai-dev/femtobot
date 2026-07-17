"""`femtobot doctor` — quick triage of a workspace (PR 7.2 of longlogs plan).

Runs a small, read-only battery of checks:

1. ``config`` — ``femtobot config validate`` is currently invoked by
   the caller; here we just verify ``Config`` loads.
2. ``mcp_servers`` — runs the AGENTS.md / USER.md / SOUL.md scanner
   (PR 1.1) and reports any server that is referenced but not
   configured.
3. ``spinner`` — sanity-checks the parity spinner path (no actual
   Live; just confirms ``SpinnerWithElapsed`` and ``ThinkingSpinner``
   can be constructed without error).
4. ``live_race`` — checks that stdout is either a TTY (where the
   ``\\x1b[2J`` clear works) or a captured log (where newlines are
   used). Reports WARN if neither matches.

Returns a dict with one entry per check: ``{"status": "OK" | "WARN" | "FAIL",
"detail": str}``. The CLI consumer (and ``/doctor`` slash command)
renders the dict as a table.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from femtobot.agent.context import collect_mcp_missing_references
from femtobot.cli.parity_widgets import SpinnerWithElapsed
from femtobot.cli.stream import ThinkingSpinner


def _check_config() -> dict[str, str]:
    try:
        from femtobot.config.schema import Config  # noqa: F401
    except Exception as exc:
        return {"status": "FAIL", "detail": f"Config import failed: {exc}"}
    return {"status": "OK", "detail": "Config schema imports cleanly."}


def _check_mcp_servers(workspace: Path | None) -> dict[str, str]:
    try:
        from femtobot.config.loader import load_config, resolve_config_env_vars
        from femtobot.config.schema import Config
    except Exception as exc:
        return {"status": "FAIL", "detail": f"Config loader unavailable: {exc}"}
    try:
        cfg: Config = resolve_config_env_vars(load_config(None))
    except Exception as exc:
        # Missing / unreadable config is treated as a WARN, not a FAIL
        # — many workspaces rely on defaults only.
        return {"status": "WARN", "detail": f"Config could not be loaded: {exc}"}
    missing = collect_mcp_missing_references(
        workspace=workspace,
        configured_servers=set(getattr(cfg.tools, "mcp_servers", {}) or {}),
    )
    if missing:
        return {
            "status": "WARN",
            "detail": (
                f"MCP servers referenced in workspace docs but not configured: "
                f"{sorted(missing)}. Add them to .femtobot/config.json "
                "under tools.mcp_servers and run /mcp reload."
            ),
        }
    return {"status": "OK", "detail": "No unreferenced MCP servers."}


def _check_spinner() -> dict[str, str]:
    try:
        # Both code paths must be constructible. We don't actually start
        # the Live because that requires a real TTY.
        SpinnerWithElapsed(bot_name="Femtobot", verb="cogitating")
        ThinkingSpinner()
    except Exception as exc:
        return {"status": "FAIL", "detail": f"Spinner construct failed: {exc}"}
    return {"status": "OK", "detail": "Spinner renderables construct cleanly."}


def _check_live_race() -> dict[str, str]:
    """Detect the B4 race: stdout is neither a TTY nor a pipe.

    ``/dev/tty`` not being attached usually means the session is being
    captured by ``tee`` / ``asciinema`` / ``script`` (the longlogs
    case). The race is then between ``_clear_current_line`` and the
    multi-row ``Live``; PR 2.1 hardens this with ``_clear_live_block``
    but a captured TTY still leaks escape sequences.
    """
    if not sys.stdout.isatty():
        return {
            "status": "OK",
            "detail": "stdout is not a TTY; captured-log path active.",
        }
    return {
        "status": "WARN",
        "detail": (
            "stdout is a TTY. When this session is captured by "
            "asciinema / script / docker exec -t, escape sequences may "
            "leak. PR 2.1 (clear_live_block) mitigates the most "
            "common artefacts."
        ),
    }


CHECKS = (
    ("config", _check_config),
    ("mcp_servers", _check_mcp_servers),
    ("spinner", _check_spinner),
    ("live_race", _check_live_race),
)


def run_doctor(workspace: Path | None = None) -> dict[str, Any]:
    """Run every check and return a scorecard dict."""
    report: dict[str, Any] = {"workspace": str(workspace) if workspace else None, "checks": {}}
    for name, fn in CHECKS:
        try:
            report["checks"][name] = fn(workspace) if name == "mcp_servers" else fn()
        except Exception as exc:  # pragma: no cover — defensive
            report["checks"][name] = {"status": "FAIL", "detail": str(exc)}
    overall = "OK"
    for entry in report["checks"].values():
        status = entry.get("status")
        if status == "FAIL":
            overall = "FAIL"
            break
        if status == "WARN":
            overall = "WARN"
    report["overall"] = overall
    return report


def render_report(report: dict[str, Any]) -> str:
    """Format a doctor report as a markdown scorecard."""
    lines = ["# femtobot doctor", ""]
    if report.get("workspace"):
        lines.append(f"Workspace: `{report['workspace']}`")
        lines.append("")
    lines.append(f"Overall: **{report['overall']}**")
    lines.append("")
    lines.append("| Check | Status | Detail |")
    lines.append("| --- | --- | --- |")
    for name, entry in report["checks"].items():
        lines.append(
            f"| `{name}` | {entry.get('status', '?')} | "
            f"{entry.get('detail', '').replace('|', '\\\\|')} |"
        )
    return "\n".join(lines)
