"""``femtobot sessions`` CLI subcommands.

CLI/WebUI parity v0.1.8 (twelfth-pass Issues 1, 3, 4): the Femtobot
runtime had ``SessionManager.delete_session`` defined but never
called anywhere, and there was no command-line surface for session
management.  This module fills the gap with three subcommands:

* ``femtobot sessions list`` — show every persisted session with
  size, last-active, and message count.
* ``femtobot sessions show <key>`` — print the session's metadata
  and recent messages.
* ``femtobot sessions delete <key>`` — remove the session file
  (and any legacy copies) plus in-memory cache.

Default workspace is the canonical one resolved by
``femtobot.config.loader``.  Override with ``--workspace PATH``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from femtobot.config.loader import load_config
from femtobot.session.manager import SessionManager

console = Console()

sessions_app = typer.Typer(
    name="sessions",
    help="Manage conversation session files (v0.1.8).",
    add_completion=False,
)


def _make_manager(workspace: Path | None) -> tuple[Path, SessionManager]:
    """Resolve the workspace and build a SessionManager over it.

    When ``workspace`` is ``None`` we delegate to the active
    Femtobot ``Config`` and use its ``workspace_path`` helper so
    the runtime, the Agent loop and the CLI all agree on which
    directory to read from.
    """
    if workspace is None:
        cfg = load_config()
        resolved = cfg.workspace_path
    else:
        resolved = workspace
    return resolved, SessionManager(workspace=resolved)


def _format_size(n: int) -> str:
    """Format a byte count as a short human-readable string."""
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.2f}MB"


def _format_dt(value: object) -> str:
    """Render an updated_at value the CLI table way."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str):
        return value
    return "-"


@sessions_app.command(name="list")
def list_sessions_cmd(
    workspace: Path | None = typer.Option(
        None, "--workspace", "-w",
        help="Workspace directory (defaults to resolved Femtobot workspace).",
    ),
) -> None:
    """List every persisted session, newest first."""
    ws, mgr = _make_manager(workspace)

    rows = mgr.list_sessions()
    if not rows:
        console.print("[dim]No sessions found in[/dim]", str(ws / "sessions"))
        raise typer.Exit(0)

    rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    table = Table(title=f"sessions ({len(rows)})", show_lines=False)
    table.add_column("key", style="cyan", overflow="fold")
    table.add_column("size", justify="right", style="magenta")
    table.add_column("updated_at", style="green")
    table.add_column("messages", justify="right")
    table.add_column("summary", style="dim")

    for row in rows:
        path = ws / "sessions" / f"{SessionManager.safe_key(str(row.get('key') or ''))}.jsonl"
        size = path.stat().st_size if path.exists() else 0
        title = (
            (row.get("metadata") or {}).get("title")
            if isinstance(row.get("metadata"), dict)
            else None
        )
        table.add_row(
            str(row.get("key", "?")),
            _format_size(size),
            _format_dt(row.get("updated_at")),
            str(row.get("message_count", "?")),
            str(title)[:60] if title else "-",
        )
    console.print(table)


@sessions_app.command(name="show")
def show_session_cmd(
    key: str = typer.Argument(..., help="Session key (e.g. cli:direct)."),
    workspace: Path | None = typer.Option(
        None, "--workspace", "-w",
        help="Workspace directory (defaults to resolved Femtobot workspace).",
    ),
) -> None:
    """Print metadata + the last messages of a session."""
    ws, mgr = _make_manager(workspace)

    payload = mgr.read_session_file(key)
    if payload is None:
        console.print(f"[red]![/red] No session file found for key '{key}'.")
        raise typer.Exit(1)

    console.print(f"[bold]Session:[/bold] [cyan]{payload.get('key', key)}[/cyan]")
    console.print(f"[bold]Created:[/bold] {payload.get('created_at', '?')}")
    console.print(f"[bold]Updated:[/bold] {payload.get('updated_at', '?')}")
    msgs = payload.get("messages") or []
    console.print(f"[bold]Messages:[/bold] {len(msgs)}")
    console.print("[dim]--- last 5 messages ---[/dim]")
    for msg in msgs[-5:]:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        snippet = content.replace("\n", " ")[:160]
        console.print(f"  [bold cyan]{role}[/bold cyan] {snippet}")


@sessions_app.command(name="delete")
def delete_session_cmd(
    key: str = typer.Argument(..., help="Session key (e.g. cli:direct)."),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the confirmation prompt.",
    ),
    workspace: Path | None = typer.Option(
        None, "--workspace", "-w",
        help="Workspace directory (defaults to resolved Femtobot workspace).",
    ),
) -> None:
    """Remove a session file (workspace + legacy paths) and cache."""
    ws, mgr = _make_manager(workspace)


    # Print a preview so the user knows what will go.
    candidates = [
        mgr._get_session_path(key),
        mgr._get_legacy_session_path(key),
    ]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        console.print(f"[dim]No session file exists for '{key}'. Nothing to delete.[/dim]")
        raise typer.Exit(0)

    console.print(f"[bold]About to delete session '[cyan]{key}[/cyan]':[/bold]")
    for path in existing:
        console.print(f"  - {path}")

    if not yes:
        confirm = typer.confirm("Proceed?", default=False)
        if not confirm:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    deleted = mgr.delete_session(key)
    if deleted:
        console.print(f"[green]✓[/green] Deleted session '{key}'.")
    else:
        console.print(f"[red]![/red] Failed to delete session '{key}'.")
        raise typer.Exit(1)
