"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone

from femtobot import __version__
from femtobot.bus.events import OutboundMessage
from femtobot.command.router import CommandContext, CommandRouter
from femtobot.utils.helpers import build_status_content
from femtobot.utils.restart import set_restart_notice_to_env


@dataclass(frozen=True)
class BuiltinCommandSpec:
    command: str
    title: str
    description: str
    icon: str
    arg_hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "arg_hint": self.arg_hint,
        }


BUILTIN_COMMAND_SPECS: tuple[BuiltinCommandSpec, ...] = (
    BuiltinCommandSpec(
        "/new",
        "New chat",
        "Stop the current task and start a fresh conversation.",
        "square-pen",
    ),
    BuiltinCommandSpec(
        "/stop",
        "Stop current task",
        "Cancel the active agent turn for this chat.",
        "square",
    ),
    BuiltinCommandSpec(
        "/restart",
        "Restart femtobot",
        "Restart the bot process in place.",
        "rotate-cw",
    ),
    BuiltinCommandSpec(
        "/status",
        "Show status",
        "Display runtime, provider, and channel status.",
        "activity",
    ),
    BuiltinCommandSpec(
        "/model",
        "Switch model preset",
        "Show or switch the active model preset.",
        "brain",
        "[preset]",
    ),
    BuiltinCommandSpec(
        "/effort",
        "Set reasoning effort",
        "Control extended thinking depth: auto, none, minimal, low, medium, maximum.",
        "gauge",
        "[level]",
    ),
    BuiltinCommandSpec(
        "/history",
        "Show conversation history",
        "Print the last N persisted conversation messages.",
        "history",
        "[n]",
    ),
    BuiltinCommandSpec(
        "/goal",
        "Start long-running goal",
        "Tell the agent to treat the request as a long-running goal.",
        "activity",
        "<goal>",
    ),
    BuiltinCommandSpec(
        "/goal complete",
        "Mark goal complete",
        "Mark the active sustained goal as completed (B6).",
        "check-circle",
        "[recap]",
    ),
    BuiltinCommandSpec(
        "/goal cancel",
        "Cancel goal",
        "Cancel the active sustained goal without finishing.",
        "x-circle",
        "[reason]",
    ),
    BuiltinCommandSpec(
        "/goal block",
        "Block goal",
        "Mark the active sustained goal as blocked pending human input.",
        "alert-octagon",
        "[reason]",
    ),
    BuiltinCommandSpec(
        "/goal status",
        "Show goal status",
        "Show the active sustained goal state, including pending asks.",
        "info",
    ),
    BuiltinCommandSpec(
        "/dream",
        "Run Dream",
        "Manually trigger memory consolidation.",
        "sparkles",
    ),
    BuiltinCommandSpec(
        "/dream-log",
        "Show Dream log",
        "Show what the last Dream consolidation changed.",
        "book-open",
    ),
    BuiltinCommandSpec(
        "/dream-restore",
        "Restore memory",
        "Revert memory to a previous Dream snapshot.",
        "undo-2",
    ),
    BuiltinCommandSpec(
        "/help",
        "Show help",
        "List available slash commands.",
        "circle-help",
    ),
    BuiltinCommandSpec(
        "/mcp",
        "Manage MCP servers",
        "Inspect, reload, or restart MCP server connections.",
        "plug",
        "[status|reload|tools <server>|restart <server>]",
    ),
    BuiltinCommandSpec(
        "/btw",
        "Ask a side question",
        "Quick question without polluting conversation history. Works mid-generation.",
        "message-circle",
    ),
    BuiltinCommandSpec(
        "/style",
        "Tweak CLI spacing",
        "Show or set per-turn CLI spacing knobs (margin_x, gap_after_turn, etc.).",
        "sliders-horizontal",
        "[set key=value ... | reset]",
    ),
    BuiltinCommandSpec(
        "/tasks",
        "Show background tasks",
        "List and manage background tasks started with Ctrl+B.",
        "list",
    ),
)


def builtin_command_palette() -> list[dict[str, str]]:
    """Return structured command metadata for UI command palettes."""
    return [spec.as_dict() for spec in BUILTIN_COMMAND_SPECS]


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    total = await loop._cancel_active_tasks(ctx.key)
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=dict(msg.metadata or {})
    )


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg
    set_restart_notice_to_env(
        channel=msg.channel,
        chat_id=msg.chat_id,
        metadata=dict(msg.metadata or {}),
    )

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "femtobot"] + sys.argv[1:])

    # Schedule via the loop's background-task registry so the task
    # is not GC'd before its 1-second sleep completes (and the
    # ``os.execv`` runs).  A naked ``asyncio.create_task`` is
    # vulnerable to PyPy / aggressive GC — see audit item 18 of
    # the v0.0.7 second-pass review.  We fall back to a direct
    # ``asyncio.create_task`` only when ``ctx.loop`` is not
    # available (defensive: tests may build a CommandContext
    # without a full AgentLoop).
    if ctx.loop is not None:
        ctx.loop._schedule_background(_do_restart())
    else:  # pragma: no cover - defensive
        asyncio.create_task(_do_restart())
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content="Restarting...",
        metadata=dict(msg.metadata or {}),
    )


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session.

    Camada 1 (1.7): rendered as a ``rich.Panel`` with 4 sections
    (context usage, session line, provider, MCP). Falls back to the
    pre-Camada-1 text formatter if Rich is unavailable or the active
    config disables the new layout.
    """
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    with suppress(Exception):
        ctx_est, _ = loop.consolidator.estimate_session_prompt_tokens(session)
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)

    # New panel-style output. Best-effort: any failure falls back to legacy
    # text formatter to guarantee a /status response.
    new_layout = True
    body: str | None = None
    with suppress(Exception):
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        from femtobot.cli.status_line import render_session_status_line

        # Section 1: context window usage
        context_window = int(getattr(loop, "context_window_tokens", 0) or 0)
        ctx_pct = (ctx_est / context_window * 100) if context_window else 0.0
        bar_width = 24
        filled = int(min(100.0, ctx_pct) / 100 * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        bar_style = "green" if ctx_pct < 70 else ("yellow" if ctx_pct < 90 else "red")
        context_block = Text()
        context_block.append(
            f"Context: {ctx_est:,} / {context_window:,} tok ", style="bold"
        )
        context_block.append(f"[{bar}] ", style=bar_style)
        context_block.append(f"{ctx_pct:.1f}%\n", style="dim")
        context_block.append(
            f"Messages: {len(session.get_history(max_messages=0))}\n", style="dim"
        )

        # Section 2: session line (from T4 helper)
        session_block = Text()
        rendered = render_session_status_line(loop)
        # Render the rich RenderableType into a string we can append.
        tmp_console = Console(record=True, width=120, color_system="standard")
        with tmp_console.capture() as cap:
            tmp_console.print(rendered)
        session_block.append(cap.get().rstrip("\n"))
        session_block.append("\n")

        # Section 3: provider
        max_tok = getattr(getattr(loop.provider, "generation", None), "max_tokens", 8192)
        provider_block = Text()
        provider_block.append(f"Provider: {loop.model}\n", style="cyan")
        provider_block.append(f"  max_output_tokens: {max_tok}\n", style="dim")

        # Section 4: MCP
        configured = sorted(getattr(loop, "_mcp_servers", {}) or {})
        connected = sorted(getattr(loop, "_mcp_stacks", {}) or {})
        missing = sorted(set(configured) - set(connected))
        mcp_block = Text()
        mcp_block.append(
            f"MCP: {len(connected)}/{len(configured)} connected\n", style="cyan"
        )
        if missing:
            mcp_block.append(f"  missing: {', '.join(missing)}\n", style="red")
        try:
            total_tools = len(getattr(loop, "tools", None).tool_names)
        except Exception:
            total_tools = 0
        mcp_block.append(f"  total_tools: {total_tools}\n", style="dim")

        body_text = Text()
        body_text.append_text(context_block)
        body_text.append_text(session_block)
        body_text.append_text(provider_block)
        body_text.append_text(mcp_block)

        console = Console(record=True, width=120)
        console.print(
            Panel(
                body_text,
                title=f"🐈 Femtobot status (v{__version__})",
                border_style="cyan",
            )
        )
        body = console.export_text(styles=False)

    if not new_layout or body is None:
        body = build_status_content(
            version=__version__,
            model=loop.model,
            start_time=loop._start_time,
            last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
            search_usage_text=None,
            active_task_count=0,
            max_completion_tokens=getattr(
                getattr(loop.provider, "generation", None), "max_tokens", 8192
            ),
        )

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=body,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Stop active task and start a fresh session."""
    loop = ctx.loop
    await loop._cancel_active_tasks(ctx.key)
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated :]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.consolidator.archive(snapshot))
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="New session started.",
        metadata=dict(ctx.msg.metadata or {}),
    )


def _format_preset_names(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names) if names else "(none configured)"


def _model_preset_names(loop) -> list[str]:
    names = set(loop.model_presets)
    names.add("default")
    return ["default", *sorted(name for name in names if name != "default")]


def _active_model_preset_name(loop) -> str:
    return loop.model_preset or "default"


def _command_error_message(exc: Exception) -> str:
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def _model_command_status(loop) -> str:
    names = _model_preset_names(loop)
    active = _active_model_preset_name(loop)
    return "\n".join(
        [
            "## Model",
            f"- Current model: `{loop.model}`",
            f"- Current preset: `{active}`",
            f"- Available presets: {_format_preset_names(names)}",
        ]
    )


async def cmd_model(ctx: CommandContext) -> OutboundMessage:
    """Show or switch model presets."""
    loop = ctx.loop
    args = ctx.args.strip()
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}

    if not args:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=_model_command_status(loop),
            metadata=metadata,
        )

    parts = args.split()
    if len(parts) != 1:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: `/model [preset]`",
            metadata=metadata,
        )

    name = parts[0]
    try:
        loop.set_model_preset(name)
    except (KeyError, ValueError) as exc:
        names = _model_preset_names(loop)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Could not switch model preset: {_command_error_message(exc)}\n\n"
                f"Available presets: {_format_preset_names(names)}"
            ),
            metadata=metadata,
        )

    max_tokens = getattr(getattr(loop.provider, "generation", None), "max_tokens", None)
    lines = [
        f"Switched model preset to `{loop.model_preset}`.",
        f"- Model: `{loop.model}`",
        f"- Context window: {loop.context_window_tokens}",
    ]
    if max_tokens is not None:
        lines.append(f"- Max output tokens: {max_tokens}")
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# /effort — reasoning effort control
# ---------------------------------------------------------------------------

EFFORT_LEVELS: tuple[str, ...] = (
    "auto",
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "maximum",
)


def _current_reasoning_effort(loop) -> str | None:
    """Return the active reasoning_effort from the agent runner or loop."""
    effort = getattr(getattr(loop, "runner", None), "_active_effort", None)
    if effort is not None:
        return effort
    return getattr(loop, "_reasoning_effort", None)


def _set_reasoning_effort(loop, effort: str | None) -> None:
    """Wire effort into the agent runner so the next turn picks it up."""
    if loop.runner is not None:
        loop.runner._active_effort = effort
    setattr(loop, "_reasoning_effort", effort)


async def cmd_effort(ctx: CommandContext) -> OutboundMessage:
    """Show or switch the reasoning effort level.

    Usage:
        /effort          — show current effort and available levels
        /effort <level>  — set effort to one of: auto, none, minimal, low, medium, high, maximum

    The effort level controls how much extended thinking the model uses. Higher
    levels are slower but more thorough. This does NOT persist across sessions
    (each session starts at 'auto').
    """
    loop = ctx.loop
    args = ctx.args.strip()
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}

    # Best-effort retrieval of current effort from runner or provider.
    current = _current_reasoning_effort(loop)

    if not args:
        lines = ["**Reasoning effort**"]
        if current:
            lines.append(f"  Current: `{current}`")
        else:
            lines.append("  Current: `auto` (provider default)")
        lines.append("")
        lines.append("Available levels:")
        for lvl in EFFORT_LEVELS:
            marker = " ◀ (current)" if lvl == (current or "auto") else ""
            lines.append(f"  - `{lvl}`{marker}")
        lines.append("")
        lines.append("Usage: `/effort <level>`")
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="\n".join(lines),
            metadata=metadata,
        )

    # Validate the requested level.
    normalized = args.lower()
    # Allow "high" as alias for "maximum" for ergonomics.
    if normalized == "high":
        normalized = "maximum"
    if normalized not in EFFORT_LEVELS:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Unknown effort level: `{args}`.\n\n"
                f"Available: {', '.join('`'+level+'`' for level in EFFORT_LEVELS)}"
            ),
            metadata=metadata,
        )

    _set_reasoning_effort(loop, normalized)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=f"Reasoning effort set to `{normalized}`. This applies to the next turn.",
        metadata=metadata,
    )


async def cmd_btw(ctx: CommandContext) -> OutboundMessage:
    """Placeholder for /btw side-question handler.

    Full streaming integration (running during active generation) requires the
    REPL to detect /btw in-stream and call ``cli/btw.run_btw()``.
    This handler runs when /btw is used standalone (not mid-generation).
    """
    loop = ctx.loop
    args = ctx.args.strip()
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}

    if not args:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "**/btw** — Ask a quick question without affecting conversation.\n\n"
                "Usage: `/btw <your question>`\n\n"
                "Tip: /btw is most useful **during** an active response, "
                "when the model is mid-generation."
            ),
            metadata=metadata,
        )

    # Run the side-question handler.
    try:
        from femtobot.cli.btw import run_btw
        result = await run_btw(
            loop=loop,
            question=args,
            session_key=ctx.key,
            channel=ctx.msg.channel,
            chat_id="btw",
        )
        if result is not None:
            return result
    except Exception:
        pass

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="[btw] Could not process the question. Is the model connected?",
        metadata=metadata,
    )


async def cmd_tasks(ctx: CommandContext) -> OutboundMessage:
    """List background tasks started with Ctrl+B."""
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}
    # Try to read the background pool from the session context if available.
    pool = None
    try:
        from femtobot.cli.background import BackgroundPool
        pool = BackgroundPool()  # NOTE: in full integration this would be the shared instance
    except Exception:
        pass
    if pool:
        tasks = pool.status()
        if not tasks:
            content = "No background tasks."
        else:
            lines = ["**Background tasks**"]
            for t in tasks:
                lines.append(f"  - {t.summary}")
            content = "\n".join(lines)
    else:
        content = "[/tasks] Background pool not yet wired in this session."
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata=metadata,
    )


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """Manually trigger a Dream consolidation run."""
    import time

    loop = ctx.loop
    msg = ctx.msg

    async def _run_dream():
        from femtobot.agent.memory import MemoryStore

        dream_session_key = MemoryStore.dream_session_key
        build_dream_commit_message = MemoryStore.build_dream_commit_message
        prune_dream_sessions = MemoryStore.prune_dream_sessions

        store = loop.context.memory
        content = ""
        resp = None
        t0 = time.monotonic()
        try:
            result = store.build_dream_prompt()
            if result is None:
                await loop.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Dream: nothing to process.",
                    )
                )
                return
            prompt, last_cursor = result
            key = dream_session_key()
            resp = await loop.process_direct(
                prompt,
                session_key=key,
                ephemeral=True,
                tools=store.build_dream_tools(),
            )
            elapsed = time.monotonic() - t0
            # R2 (eighth-pass parity review): gate cursor advance on
            # the real git diff of the durable memory files, not on
            # the LLM's self-report.  A valid no-op Dream run (model
            # completes but edits nothing) no longer advances the
            # cursor.  If git isn't initialized (cold workspace), we
            # fall back to the LLM's self-report so the cursor
            # still progresses; once git is up the ground truth
            # takes over.
            diff_body = store.dream_content_diff()
            productive = bool(diff_body) or (
                not store.git.is_initialized()
                and MemoryStore.dream_run_completed(resp)
            )
            if productive:
                # A6: cursor advance is now tied to a successful git commit
                # via ``advance_dream_cursor_after_commit``.  If the commit
                # is a no-op (nothing to commit) or fails, the cursor stays
                # behind and the next Dream cycle reprocesses those entries.
                if diff_body:
                    commit_msg = build_dream_commit_message(
                        "dream: manual run", resp, diff_body=diff_body
                    )
                else:
                    commit_msg = build_dream_commit_message("dream: manual run", resp)
                advanced, sha = store.advance_dream_cursor_after_commit(
                    last_cursor, commit_message=commit_msg
                )
                if advanced:
                    content = (
                        f"Dream completed in {elapsed:.1f}s "
                        f"(commit {sha}, cursor advanced to {last_cursor})."
                    )
                else:
                    content = (
                        f"Dream completed in {elapsed:.1f}s but cursor was not "
                        "advanced (no commit / git not initialized); next cycle "
                        "will reprocess."
                    )
            else:
                content = (
                    f"Dream did not complete after {elapsed:.1f}s; memory cursor was not advanced."
                )
        except Exception as e:
            elapsed = time.monotonic() - t0
            content = f"Dream failed after {elapsed:.1f}s: {e}"
        finally:
            store.compact_history()
            prune_dream_sessions(loop.sessions.sessions_dir)
        await loop.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
            )
        )

    # Schedule via the loop's background-task registry so the task
    # is not GC'd before its long-running write/commit sequence
    # finishes (audit item 18 of the v0.0.7 second-pass review).
    if loop is not None:
        loop._schedule_background(_run_dream())
    else:  # pragma: no cover - defensive
        asyncio.create_task(_run_dream())
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content="Dreaming...",
    )


def _extract_changed_files(diff: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3]
        if path.startswith("b/"):
            path = path[2:]
        if path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def _format_changed_files(diff: str) -> str:
    files = _extract_changed_files(diff)
    if not files:
        return "No tracked memory files changed."
    return ", ".join(f"`{path}`" for path in files)


def _format_dream_log_content(commit, diff: str, *, requested_sha: str | None = None) -> str:
    files_line = _format_changed_files(diff)
    lines = [
        "## Dream Update",
        "",
        "Here is the selected Dream memory change."
        if requested_sha
        else "Here is the latest Dream memory change.",
        "",
        f"- Commit: `{commit.sha}`",
        f"- Time: {commit.timestamp}",
        f"- Changed files: {files_line}",
    ]
    if diff:
        lines.extend(
            [
                "",
                f"Use `/dream-restore {commit.sha}` to undo this change.",
                "",
                "```diff",
                diff.rstrip(),
                "```",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Dream recorded this version, but there is no file diff to display.",
            ]
        )
    return "\n".join(lines)


def _format_dream_restore_list(commits: list) -> str:
    lines = [
        "## Dream Restore",
        "",
        "Choose a Dream memory version to restore. Latest first:",
        "",
    ]
    for c in commits:
        lines.append(f"- `{c.sha}` {c.timestamp} - {c.message.splitlines()[0]}")
    lines.extend(
        [
            "",
            "Preview a version with `/dream-log <sha>` before restoring it.",
            "Restore a version with `/dream-restore <sha>`.",
        ]
    )
    return "\n".join(lines)


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """Show what the last Dream changed.

    Default: diff of the latest commit (HEAD~1 vs HEAD).
    With /dream-log <sha>: diff of that specific commit.
    """
    store = ctx.loop.consolidator.store
    git = store.git

    if not git.is_initialized():
        if store.get_last_dream_cursor() == 0:
            msg = "Dream has not run yet. Run `/dream`, or wait for the next scheduled Dream cycle."
        else:
            msg = "Dream history is not available because memory versioning is not initialized."
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=msg,
            metadata={"render_as": "text"},
        )

    args = ctx.args.strip()

    if args:
        # Show diff of a specific commit
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        if not result:
            content = (
                f"Couldn't find Dream change `{sha}`.\n\n"
                "Use `/dream-restore` to list recent versions, "
                "or `/dream-log` to inspect the latest one."
            )
        else:
            commit, diff = result
            content = _format_dream_log_content(commit, diff, requested_sha=sha)
    else:
        # Default: show the latest commit's diff
        commits = git.log(max_entries=1)
        result = git.show_commit_diff(commits[0].sha) if commits else None
        if result:
            commit, diff = result
            content = _format_dream_log_content(commit, diff)
        else:
            content = "Dream memory has no saved versions yet."

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """Restore memory files from a previous dream commit.

    Usage:
        /dream-restore          — list recent commits
        /dream-restore <sha>    — revert a specific commit
    """
    store = ctx.loop.consolidator.store
    git = store.git
    if not git.is_initialized():
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Dream history is not available because memory versioning is not initialized.",
        )

    args = ctx.args.strip()
    if not args:
        # Show recent commits for the user to pick
        commits = git.log(max_entries=10)
        if not commits:
            content = "Dream memory has no saved versions to restore yet."
        else:
            content = _format_dream_restore_list(commits)
    else:
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        changed_files = _format_changed_files(result[1]) if result else "the tracked memory files"
        new_sha = git.revert(sha)
        if new_sha:
            content = (
                f"Restored Dream memory to the state before `{sha}`.\n\n"
                f"- New safety commit: `{new_sha}`\n"
                f"- Restored files: {changed_files}\n\n"
                f"Use `/dream-log {new_sha}` to inspect the restore diff."
            )
        else:
            content = (
                f"Couldn't restore Dream change `{sha}`.\n\n"
                "It may not exist, or it may be the first saved version with no earlier state to restore."
            )
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


_HISTORY_DEFAULT_COUNT = 10
_HISTORY_MAX_COUNT = 50
_HISTORY_MAX_CONTENT_CHARS = 200


def _format_history_message(msg: dict) -> str | None:
    """Format a single history message for display. Returns None to skip."""
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content") or ""
    if isinstance(content, list):
        parts = [
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ]
        content = " ".join(parts)
    content = str(content).strip()
    if not content:
        return None
    if len(content) > _HISTORY_MAX_CONTENT_CHARS:
        content = content[:_HISTORY_MAX_CONTENT_CHARS] + "…"
    label = "👤 You" if role == "user" else "🤖 Bot"
    return f"{label}: {content}"


async def cmd_history(ctx: CommandContext) -> OutboundMessage:
    """Show the last N messages of the current session (default 10, max 50).

    Usage: /history [count]
    """
    count = _HISTORY_DEFAULT_COUNT
    if ctx.args.strip():
        try:
            count = max(1, min(int(ctx.args.strip()), _HISTORY_MAX_COUNT))
        except ValueError:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="Usage: /history [count] — e.g. /history 5 (default: 10, max: 50)",
                metadata=dict(ctx.msg.metadata or {}),
            )

    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    history = session.get_history(max_messages=0)
    visible = [_format_history_message(m) for m in history]
    visible = [m for m in visible if m is not None]
    recent = visible[-count:]

    if not recent:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No conversation history yet.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    header = f"Last {len(recent)} message(s):\n"
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=header + "\n".join(recent),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def _iso_now_ms() -> str:
    """ISO-8601 UTC timestamp with millisecond precision."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


_GOAL_PROMPT_TEMPLATE = """The user declared a sustained objective for this thread.

Inspect or clarify if needed, then call `long_task` with the refined objective (and optional short ui_summary). Work proceeds as normal assistant turns using your usual tools. When the objective is fully done and verified, call `complete_goal` with a brief recap. If the user later cancels or changes direction, still call `complete_goal` with an honest recap (then `long_task` again only after there is no active goal). Do not use `long_task` / `complete_goal` for trivial one-shot answers.

Goal:
{goal}
"""


async def cmd_goal(ctx: CommandContext) -> OutboundMessage | None:
    """Bootstrap a sustained goal and hand it off to the agent as one turn.

    M1 of long-task-by-default: the slash command itself writes the
    ``goal_state`` blob (active) into session metadata, sets the
    ``goal_requested`` flag, and emits ``GoalStateChanged``.  The agent
    receives a goal-ready context instead of a "please call long_task"
    prompt.
    """
    from femtobot.bus.goal_events import publish_goal_state_changed
    from femtobot.session.goal_state import (
        GOAL_STATE_KEY,
        MAX_GOAL_OBJECTIVE_CHARS,
        discard_legacy_goal_state_key,
        is_self_contained_objective,
        normalize_goal_status,
        reset_goal_continuation_marker,
    )

    goal = ctx.args.strip()
    if not goal:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: /goal <long-running task description>",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )
    if ctx.session is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "Cannot start a goal in this chat — no active session is bound. "
                "Send a regular message first so a session is created, then "
                "send `/goal <long-running task description>` again."
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )
    if len(goal) > MAX_GOAL_OBJECTIVE_CHARS:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Goal is too long ({len(goal)} chars). "
                f"Please keep the objective under {MAX_GOAL_OBJECTIVE_CHARS} characters."
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    require_self_containment = True
    loop_obj = getattr(ctx, "loop", None)
    long_task_cfg = getattr(loop_obj, "long_task_config", None)
    if long_task_cfg is not None:
        require_self_containment = bool(
            getattr(long_task_cfg, "require_objective_self_containment", True)
        )
    if require_self_containment and not is_self_contained_objective(goal):
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "The goal looks like an open-ended question rather than a "
                "bounded task. Reframe it as a concrete, verifiable objective "
                "(e.g. 'Refactor module X to use Y' or 'Add tests for Z') and "
                "send `/goal <objective>` again."
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    md = dict(ctx.session.metadata or {})
    epoch_now = time.time()
    iso_now = _iso_now_ms()
    blob = {
        "status": normalize_goal_status("active") or "active",
        "objective": goal,
        "created_at": iso_now,
        "source": "/goal",
    }
    md[GOAL_STATE_KEY] = blob
    md["goal_started_at"] = epoch_now
    discard_legacy_goal_state_key(md)
    reset_goal_continuation_marker(md)
    ctx.session.metadata = md

    # Persist the new goal blob to disk so a crash before the next turn
    # doesn't lose the bootstrap.  Without this save, the goal would
    # only be visible after the next inbound triggers the loop's own
    # ``sessions.save`` call.
    if getattr(ctx, "loop", None) is not None and getattr(ctx.loop, "sessions", None) is not None:
        try:
            ctx.loop.sessions.save(ctx.session)
        except Exception:
            # Persistence is best-effort — the loop's regular save path
            # will catch up on the next turn.
            pass

    ctx.msg.metadata = {
        **dict(ctx.msg.metadata or {}),
        "original_command": "/goal",
        "original_content": ctx.raw,
        "goal_requested": True,
        "goal_started_at": epoch_now,
    }
    ctx.msg.content = _GOAL_PROMPT_TEMPLATE.format(goal=goal)

    publish_goal_state_changed(
        session_key=getattr(ctx.session, "session_key", None),
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        session_metadata=md,
    )
    return None


async def cmd_goal_complete(ctx: CommandContext) -> OutboundMessage | None:
    """Rewrite ``/goal complete [recap]`` to mark the active goal as completed (B6).

    The user invokes this slash command when the sustained goal started
    by ``/goal <objective>`` is done.  We don't talk to a real
    ``complete_goal`` tool here (the agent is the one to call that);
    instead, we mutate the session metadata so the runner wall
    timeout falls back to the default and the active-goal predicate
    stops returning True.  We also stash the recap as a tool_result
    tag so the LLM sees a clear "goal complete" boundary.
    """
    from femtobot.bus.goal_events import publish_goal_state_changed
    from femtobot.session.goal_state import (
        GOAL_STATE_KEY,
        clear_goal_waiting,
        discard_legacy_goal_state_key,
        parse_goal_state,
    )

    recap = ctx.args.strip()
    if ctx.session is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "No active session — cannot mark a goal complete. "
                "Start one with `/goal <objective>` first."
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    md = dict(ctx.session.metadata or {})
    blob = parse_goal_state(md.get(GOAL_STATE_KEY))
    if not isinstance(blob, dict) or blob.get("status") != "active":
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "No active goal to mark complete. Use `/goal <objective>` "
                "to start a new one."
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    # B6: flip the status to ``completed`` and record the recap.
    blob["status"] = "completed"
    blob["completed_at"] = _iso_now_ms()
    if recap:
        blob["recap"] = recap
    md[GOAL_STATE_KEY] = blob
    discard_legacy_goal_state_key(md)
    clear_goal_waiting(md)
    ctx.session.metadata = md

    # Persist terminal-state changes to disk so /goal status survives
    # a process restart even before the next inbound.
    if getattr(ctx, "loop", None) is not None and getattr(ctx.loop, "sessions", None) is not None:
        try:
            ctx.loop.sessions.save(ctx.session)
        except Exception:
            pass

    publish_goal_state_changed(
        session_key=getattr(ctx.session, "session_key", None),
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        session_metadata=md,
    )

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=(
            "Goal marked complete. Returning to default per-turn "
            "behavior; runner wall timeout is back to "
            "FEMTOBOT_LLM_TIMEOUT_S."
        ),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_goal_cancel(ctx: CommandContext) -> OutboundMessage | None:
    """``/goal cancel [reason]`` — terminate the active goal without finishing."""
    from femtobot.bus.goal_events import publish_goal_state_changed
    from femtobot.session.goal_state import (
        GOAL_STATE_KEY,
        clear_goal_waiting,
        discard_legacy_goal_state_key,
        parse_goal_state,
    )

    reason = ctx.args.strip()
    if ctx.session is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No active session — cannot cancel a goal.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    md = dict(ctx.session.metadata or {})
    blob = parse_goal_state(md.get(GOAL_STATE_KEY))
    if not isinstance(blob, dict) or blob.get("status") != "active":
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No active goal to cancel.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    blob["status"] = "cancelled"
    blob["cancelled_at"] = _iso_now_ms()
    if reason:
        blob["cancel_reason"] = reason
    md[GOAL_STATE_KEY] = blob
    discard_legacy_goal_state_key(md)
    clear_goal_waiting(md)
    ctx.session.metadata = md

    if getattr(ctx, "loop", None) is not None and getattr(ctx.loop, "sessions", None) is not None:
        try:
            ctx.loop.sessions.save(ctx.session)
        except Exception:
            pass

    publish_goal_state_changed(
        session_key=getattr(ctx.session, "session_key", None),
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        session_metadata=md,
    )

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="Goal cancelled." + (f" Reason: {reason}" if reason else ""),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_goal_block(ctx: CommandContext) -> OutboundMessage | None:
    """``/goal block [reason]`` — mark the goal as blocked pending human input."""
    from femtobot.bus.goal_events import publish_goal_state_changed
    from femtobot.session.goal_state import (
        GOAL_STATE_KEY,
        discard_legacy_goal_state_key,
        parse_goal_state,
    )

    reason = ctx.args.strip()
    if ctx.session is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No active session — cannot block a goal.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    md = dict(ctx.session.metadata or {})
    blob = parse_goal_state(md.get(GOAL_STATE_KEY))
    if not isinstance(blob, dict) or blob.get("status") != "active":
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No active goal to block.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    blob["status"] = "blocked"
    blob["blocked_at"] = _iso_now_ms()
    md[GOAL_STATE_KEY] = blob
    discard_legacy_goal_state_key(md)
    if reason:
        md["goal_block_reason"] = reason
    ctx.session.metadata = md

    if getattr(ctx, "loop", None) is not None and getattr(ctx.loop, "sessions", None) is not None:
        try:
            ctx.loop.sessions.save(ctx.session)
        except Exception:
            pass

    publish_goal_state_changed(
        session_key=getattr(ctx.session, "session_key", None),
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        session_metadata=md,
    )

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="Goal marked blocked." + (f" Reason: {reason}" if reason else ""),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_goal_status(ctx: CommandContext) -> OutboundMessage:
    """``/goal status`` — print the active goal state, if any."""
    if ctx.session is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No active session.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    from femtobot.session.goal_state import (
        GOAL_STATE_KEY,
        goal_block_reason,
        goal_elapsed_s,
        goal_id,
        goal_started_at,
        goal_waiting_on,
        parse_goal_state,
    )
    from femtobot.session.pending_asks import count_pending_asks, list_pending_asks

    md = ctx.session.metadata or {}
    blob = parse_goal_state(md.get(GOAL_STATE_KEY))
    if not isinstance(blob, dict) or blob.get("status") != "active":
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No active goal.",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    objective = str(blob.get("objective") or "").strip()
    summary = str(blob.get("ui_summary") or "").strip()
    elapsed = goal_elapsed_s(md)
    started = goal_started_at(md)
    gid = goal_id(md)
    waiting = goal_waiting_on(md)
    pending = count_pending_asks(md)
    asks = list_pending_asks(md)

    lines = []
    if gid:
        lines.append(f"Goal id: `{gid}`")
    lines.append(f"Status: `active` (elapsed {elapsed:.1f}s)")
    if started:
        # ``goal_started_at`` is an epoch float; surface it as an
        # ISO-8601 UTC string so a human reading the slash-command
        # output can parse the wall-clock time directly.
        from datetime import datetime, timezone

        iso_started = (
            datetime.fromtimestamp(started, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        lines.append(f"Started at (UTC): `{iso_started}`")
    if summary:
        lines.append(f"Summary: {summary}")
    if objective:
        body = objective if len(objective) <= 600 else objective[:600].rstrip() + "…"
        lines.append("Objective:")
        lines.append(body)
    if waiting:
        lines.append(f"Waiting on: `{waiting}`")
    if pending:
        lines.append(f"Pending asks: {pending}")
        for a in asks:
            if a.status.value == "pending":
                lines.append(f"  - `{a.correlation_id}` → {a.question}")
    reason = goal_block_reason(md)
    if reason:
        lines.append(f"Block reason: {reason}")

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_help_text(),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = ["🐈 femtobot commands:"]
    for spec in BUILTIN_COMMAND_SPECS:
        command = spec.command
        if spec.arg_hint:
            command = f"{command} {spec.arg_hint}"
        lines.append(f"{command} — {spec.description}")
    return "\n".join(lines)


async def cmd_mcp(ctx: CommandContext) -> OutboundMessage | None:
    """Manage MCP server connections.

    Subcommands (handled in order, default = status):

    * ``/mcp status`` — list configured + connected servers, highlight missing
    * ``/mcp reload`` — hot-reload MCP servers from config.json
    * ``/mcp tools <server>`` — list tools registered from a specific server
    * ``/mcp restart <server>`` — force-reload a single server

    Refs: FEMTOBOT_MCP_IMPROVEMENT_PLAN.md Fase 5.
    """
    loop = ctx.loop
    msg = ctx.msg
    raw = (ctx.args or msg.content or "").strip()
    # Split off the first token as the subcommand.
    tokens = raw.split()
    # If the first token starts with "/", the user typed "/mcp status" — the
    # router already stripped "/mcp ", so tokens[0] is "status".
    sub = (tokens[0].lower() if tokens else "status").lstrip("/")

    def _reply(content: str) -> OutboundMessage:
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=content,
            metadata=dict(msg.metadata or {}),
        )

    # ``/mcp status`` — show configured vs connected.
    if sub == "status":
        configured = sorted(getattr(loop, "_mcp_servers", {}) or {})
        connected = sorted(getattr(loop, "_mcp_stacks", {}) or {})
        missing = sorted(set(configured) - set(connected))
        lines = [
            "MCP server status:",
            f"  configured: {', '.join(configured) or '(none)'}",
            f"  connected:  {', '.join(connected) or '(none)'}",
        ]
        if missing:
            lines.append(f"  missing:    {', '.join(missing)}")
        try:
            total_tools = len(getattr(loop, "tools", None).tool_names)
        except Exception:
            total_tools = "?"
        lines.append(f"  total tools registered: {total_tools}")
        return _reply("\n".join(lines))

    # ``/mcp reload`` — hot-reload MCP servers from config.
    if sub == "reload":
        from femtobot.agent.tools.mcp import request_mcp_reload

        result = await request_mcp_reload(loop.bus)
        if isinstance(result, dict):
            content = f"MCP reload: {result.get('message', 'unknown')}"
            if result.get("failed"):
                content += f" (failed: {', '.join(result['failed'])})"
        else:
            content = "MCP reload: requested"
        return _reply(content)

    # ``/mcp tools <server>`` — list tools registered from a server.
    if sub == "tools":
        server = tokens[1] if len(tokens) > 1 else None
        if not server:
            return _reply("Usage: /mcp tools <server>")
        prefix = f"mcp_{server.replace('-', '_')}_"
        registry = getattr(loop, "tools", None)
        try:
            tools = sorted(
                n for n in registry.tool_names if n.startswith(prefix)
            )
        except Exception:
            tools = []
        if not tools:
            return _reply(f"No tools registered from '{server}'.")
        return _reply(
            f"Tools from '{server}':\n  " + "\n  ".join(tools)
        )

    # ``/mcp restart <server>`` — force-reload a single server.
    if sub == "restart":
        server = tokens[1] if len(tokens) > 1 else None
        if not server:
            return _reply("Usage: /mcp restart <server>")
        # Hot-reload the whole stack — fine for restart-of-all; a per-server
        # endpoint can be added if needed.
        from femtobot.agent.tools.mcp import request_mcp_reload

        result = await request_mcp_reload(loop.bus)
        if isinstance(result, dict):
            content = f"MCP restart for '{server}': {result.get('message', 'unknown')}"
        else:
            content = f"MCP restart for '{server}': requested"
        return _reply(content)

    # Unknown subcommand.
    return _reply(
        f"Unknown /mcp subcommand: {sub!r}. Use: status|reload|tools <server>|restart <server>"
    )


# ---------------------------------------------------------------------------
# /style — CLI spacing tweaks (Camada 5 P1-P3)
# ---------------------------------------------------------------------------
# Lets the user inspect and override the per-turn spacing knobs at runtime
# without restarting femtobot or editing the config file. The next turn
# rebuilds its ``TurnSpacingRenderer`` from the live config, so changes
# take effect on the *next* agent reply (not retroactively).
#
# Examples
# --------
#   /style                       -> show all current values
#   /style set margin_x=6        -> set one knob
#   /style set margin_x=6 gap_after_turn=2
#   /style reset                 -> revert to schema defaults
# ---------------------------------------------------------------------------


# Map of slash-command-facing keys -> (config attribute, parser).
# Bounds are enforced here too (so a bad value never reaches the schema).
_STYLE_KEYS: dict[str, tuple[str, str]] = {
    "margin_x":         ("margin_x", "int"),
    "gap_after_turn":   ("gap_after_turn", "int"),
    "gap_before_input": ("gap_before_input", "int"),
    "role_header":      ("role_header", "literal"),
    "user_separator":   ("user_separator", "bool"),
    "turn_box":         ("turn_box", "bool"),
}

_STYLE_LITERALS = ("always", "minimal", "off")


def _style_format_current(cli_cfg) -> list[str]:
    """Return a markdown-formatted listing of the current spacing values."""
    lines: list[str] = ["**CLI spacing (live)**"]
    for key, (attr, _kind) in _STYLE_KEYS.items():
        value = getattr(cli_cfg, attr, None)
        lines.append(f"  - `{key}` = `{value}`")
    lines.append("")
    lines.append(
        "Override with `/style set key=value` (e.g. "
        "`/style set margin_x=6 gap_after_turn=2`)."
    )
    lines.append("Revert with `/style reset`.")
    return lines


def _style_parse_value(key: str, raw: str):
    """Validate and coerce a user-supplied value for the given key.

    Returns the coerced value, or raises ``ValueError`` on bad input.
    """
    if key not in _STYLE_KEYS:
        raise ValueError(
            f"Unknown key: {key!r}. Valid keys: {', '.join(_STYLE_KEYS)}"
        )
    attr, kind = _STYLE_KEYS[key]
    if kind == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer (got {raw!r})") from None
        # Clamp using the schema bounds.
        from femtobot.config.schema import (
            CLI_MAX_GAP,
            CLI_MAX_INPUT_GAP,
            CLI_MAX_MARGIN,
            CLI_MIN_GAP,
            CLI_MIN_INPUT_GAP,
            CLI_MIN_MARGIN,
        )
        bounds = {
            "margin_x": (CLI_MIN_MARGIN, CLI_MAX_MARGIN),
            "gap_after_turn": (CLI_MIN_GAP, CLI_MAX_GAP),
            "gap_before_input": (CLI_MIN_INPUT_GAP, CLI_MAX_INPUT_GAP),
        }
        lo, hi = bounds[attr]
        if value < lo or value > hi:
            raise ValueError(
                f"{key}={value} is out of bounds. Allowed range: [{lo}, {hi}]"
            )
        return value
    if kind == "literal":
        value = raw.strip().lower()
        if value not in _STYLE_LITERALS:
            raise ValueError(
                f"{key} must be one of {', '.join(_STYLE_LITERALS)} (got {raw!r})"
            )
        return value
    if kind == "bool":
        normalized = raw.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{key} must be a boolean (true/false, got {raw!r})")
    raise ValueError(f"Unhandled kind for {key!r}: {kind}")


async def cmd_style(ctx: CommandContext) -> OutboundMessage:
    """Show or set CLI spacing knobs (Camada 5).

    Usage:
        /style                  — list all current values
        /style set key=value    — set one or more knobs (space-separated)
        /style reset            — restore schema defaults
    """
    loop = ctx.loop
    args = ctx.args.strip()
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "markdown"}

    config = getattr(loop, "_config", None)
    if config is None or not hasattr(config, "agents"):
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "/style is unavailable: the active loop is not carrying a "
                "Config reference (legacy AgentLoop?)."
            ),
            metadata=metadata,
        )

    cli_cfg = config.agents.defaults.cli
    from femtobot.config.schema import (
        CLI_DEFAULT_GAP_AFTER_TURN,
        CLI_DEFAULT_GAP_BEFORE_INPUT,
        CLI_DEFAULT_MARGIN_X,
        CLI_DEFAULT_ROLE_HEADER_MODE,
        CLI_DEFAULT_TURN_BOX,
        CLI_DEFAULT_USER_SEPARATOR,
    )

    def _reset() -> None:
        cli_cfg.gap_after_turn = CLI_DEFAULT_GAP_AFTER_TURN
        cli_cfg.role_header = CLI_DEFAULT_ROLE_HEADER_MODE
        cli_cfg.user_separator = CLI_DEFAULT_USER_SEPARATOR
        cli_cfg.margin_x = CLI_DEFAULT_MARGIN_X
        cli_cfg.gap_before_input = CLI_DEFAULT_GAP_BEFORE_INPUT
        cli_cfg.turn_box = CLI_DEFAULT_TURN_BOX

    # No-arg form: just show the current values.
    if not args:
        lines = _style_format_current(cli_cfg)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="\n".join(lines),
            metadata=metadata,
        )

    parts = args.split()
    sub = parts[0].lower()

    if sub == "reset":
        _reset()
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "CLI spacing reset to schema defaults. Next turn will pick "
                "them up."
            ),
            metadata=metadata,
        )

    if sub != "set":
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Unknown subcommand: {sub!r}. Use `/style`, "
                "`/style set key=value ...`, or `/style reset`."
            ),
            metadata=metadata,
        )

    if len(parts) < 2:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: `/style set key=value [key=value ...]`",
            metadata=metadata,
        )

    # Parse and apply.
    applied: list[str] = []
    failed: list[str] = []
    for token in parts[1:]:
        if "=" not in token:
            failed.append(f"  - {token!r}: missing '=' (expected key=value)")
            continue
        key, _, raw_val = token.partition("=")
        key = key.strip()
        raw_val = raw_val.strip()
        try:
            value = _style_parse_value(key, raw_val)
        except ValueError as exc:
            failed.append(f"  - {token!r}: {exc}")
            continue
        setattr(cli_cfg, _STYLE_KEYS[key][0], value)
        applied.append(f"  - `{key}` = `{value}`")

    if failed and not applied:
        header = "No changes applied:"
    elif failed and applied:
        header = "Some changes applied; failures:"
    else:
        header = "Changes queued (effective on next turn):"

    lines = [header, *applied, *failed]
    # Always re-print the active values so the user sees the post-state.
    lines.append("")
    lines.extend(_style_format_current(cli_cfg))
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# v0.1.0-ui.0+ — UI parity slash commands (T8)
# ---------------------------------------------------------------------------


async def cmd_ui(ctx: CommandContext) -> OutboundMessage:
    """Show or change the active UI parity profile (per-session, Q10).

    Usage:
        /ui             — show the current profile
        /ui off         — switch to the legacy Rich Live renderer
        /ui compat      — switch to the Claude-Code parity renderer
        /ui full        — Textual TUI (not available in the preview)

    The change is **per-session**: it mutates the in-memory
    ``Config.agents.defaults.cli.ui_parity.profile`` but does NOT
    persist to ``config.json``. Use ``/style set ui_parity=...`` to
    persist.
    """
    args = ctx.args.strip()
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "markdown"}
    config = getattr(ctx.loop, "_config", None)
    if config is None or not hasattr(config, "agents"):
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="/ui is unavailable: the active loop is not carrying a Config reference.",
            metadata=metadata,
        )

    ui_cfg = config.agents.defaults.cli.ui_parity

    if not args:
        lines = [
            f"Currently using: ui_parity={ui_cfg.profile}",
            "Available profiles:",
            "  1. off    — legacy Rich Live renderer",
            "  2. compat — Claude-Code parity (Rich Live + header + tool cards)",
            "  3. full   — Textual TUI (arrives in v0.1.0-ui.1 / RC)",
            "",
            "Note: changes are per-session and reset on REPL exit.",
            "To persist, use `/style set ui_parity=compat` (writes to config.json).",
        ]
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="\n".join(lines),
            metadata=metadata,
        )

    requested = args.lower().split()[0]
    if requested not in ("off", "compat", "full"):
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Unknown profile: {requested!r}. Use `/ui off|compat|full`."
            ),
            metadata=metadata,
        )

    ui_cfg.profile = requested
    if requested == "full":
        extra = (
            "\n\nNote: `full` (Textual TUI) is not available in the v0.1.0-ui.0 "
            "preview. It will fall back to `off` until the RC release."
        )
    else:
        extra = ""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=(
            f"Switched ui_parity to {requested!r} for this session.{extra}"
        ),
        metadata=metadata,
    )


async def cmd_welcome(ctx: CommandContext) -> OutboundMessage:
    """Re-display the welcome card (Q3).

    By default the welcome card is shown only on the first turn and
    hidden afterwards. ``/welcome`` brings it back mid-session.
    """
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "markdown"}
    # Defer to the parity renderer's ``show_welcome_card`` if a parity
    # renderer is active; otherwise emit a static text body so the
    # command works on the legacy profile too.
    renderer = globals().get("_ACTIVE_RENDERER") or globals().get("_ui_active_renderer")
    if renderer is not None and hasattr(renderer, "show_welcome_card"):
        renderer.show_welcome_card(force=True)
        content = "Welcome card re-rendered."
    else:
        # Legacy profile: emit a static welcome card with a short tip list.
        from io import StringIO

        from rich.console import Console

        from femtobot.cli.parity_widgets import render_welcome_card
        from femtobot.cli.theme import get_theme
        buf = StringIO()
        console = Console(file=buf, force_terminal=False, width=120, color_system=None)
        console.print(
            render_welcome_card(
                tips=[
                    "Run /init to create a FEMTO.md file with instructions for Femto",
                    "Try /ui compat to enable the Claude-Code parity renderer",
                    "Toggle verbose transcript with Ctrl+O",
                ],
                whats_new=[
                    "Added welcome card + header bar (v0.1.0-ui preview)",
                    "Added elapsed-time spinner",
                ],
                theme=get_theme("terracotta-claude"),
            )
        )
        content = buf.getvalue()
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata=metadata,
    )


async def cmd_release_notes(ctx: CommandContext) -> OutboundMessage:
    """Print the top of the CHANGELOG (Q6 — parsed automatically)."""
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "markdown"}
    from pathlib import Path

    from femtobot.cli.parity_widgets import parse_changelog
    changelog_path = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
    entries = parse_changelog(changelog_path, max_entries=1, max_bullets=8)
    if not entries:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Could not parse {changelog_path}. The file may be missing or "
                "unparseable; see `git log -- CHANGELOG.md` instead."
            ),
            metadata=metadata,
        )
    head = entries[0]
    lines = [f"# Release notes — {head.version}", ""]
    for b in head.bullets:
        lines.append(f"- {b}")
    lines.append("")
    lines.append(f"Full history: {changelog_path}")
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata=metadata,
    )


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/model", cmd_model)
    router.prefix("/model ", cmd_model)
    router.exact("/history", cmd_history)
    router.prefix("/history ", cmd_history)
    router.exact("/goal", cmd_goal)
    router.prefix("/goal ", cmd_goal)
    # B6: `/goal complete` and `/goal complete <recap>` mark the active
    # sustained goal as completed.  Registered as exact + prefix so the
    # full string is matched before the generic ``/goal`` prefix.
    router.exact("/goal complete", cmd_goal_complete)
    router.prefix("/goal complete ", cmd_goal_complete)
    # M1 of long-task-by-default: cancel/block/status routes.  Same exact+prefix
    # pattern as ``/goal complete`` — exact match takes priority over the
    # generic ``/goal`` prefix above.
    router.exact("/goal cancel", cmd_goal_cancel)
    router.prefix("/goal cancel ", cmd_goal_cancel)
    router.exact("/goal block", cmd_goal_block)
    router.prefix("/goal block ", cmd_goal_block)
    router.exact("/goal status", cmd_goal_status)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.exact("/effort", cmd_effort)
    router.prefix("/effort ", cmd_effort)
    router.exact("/btw", cmd_btw)
    router.prefix("/btw ", cmd_btw)
    router.exact("/style", cmd_style)
    router.prefix("/style ", cmd_style)
    router.exact("/tasks", cmd_tasks)
    router.exact("/help", cmd_help)
    router.exact("/mcp", cmd_mcp)
    router.prefix("/mcp ", cmd_mcp)
    # v0.1.0-ui.0+ — UI parity commands (T8). Per-session state only.
    router.exact("/ui", cmd_ui)
    router.prefix("/ui ", cmd_ui)
    router.exact("/welcome", cmd_welcome)
    router.exact("/release-notes", cmd_release_notes)
