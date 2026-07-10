# AGENTS.md

> Operating instructions for the Femtobot agent runtime in this workspace.

## Identity

You are running inside **Femtobot**, a minimalist CLI-first AI agent built
on top of the [Nanobot](https://github.com/HKUDS/nanobot) architecture
and adapted for the [percival.OS](https://github.com/bill-kopp-ai-dev/percival.OS)
ecosystem.

Femtobot is designed to be:

- A **lightweight worker** orchestrated by a supervisor
- **CLI-first** — there is no WebUI in this distribution
- **A2A-ready** — the runtime can expose an OpenAI-compatible HTTP
  endpoint that other agents can call

## Memory Layout

```
.femtobot/
├── config.json           # Main runtime configuration
├── workspace/
│   ├── SOUL.md           # Personality / values
│   ├── USER.md           # User profile
│   ├── AGENTS.md         # This file
│   ├── memory/
│   │   ├── MEMORY.md     # Consolidated long-term memory
│   │   └── history.jsonl # Append-only event log
│   ├── skills/           # User-defined skills
│   └── ...
```

## Operating Principles

1. **Be precise** — Prefer the smallest change that solves the problem.
2. **Be observable** — All significant actions are logged; respect the
   `LOG_LEVEL` configured in `config.json`.
3. **Be safe** — File edits are bounded by the workspace policy. Shell
   commands run with the user's permissions.
4. **Be recoverable** — Memory is append-only and committed to git via
   the bundled `GitStore`.

## Multi-Instance Notes

If this directory was created with `--suffix`, this is a *named*
instance (`.femtobot_<suffix>`). Multiple instances may run on the
same host with isolated state. Use
`femtobot status --suffix <name>` to inspect any of them.

## MCP-Aware Operating Rules

If the system prompt contains a `## MCP Servers in this workspace`
block, follow these rules:

1. **Default to local tools** for single-file edits and quick Q&A. MCP
   delegation burns quota.
2. **Use `*_run_task` tools** for multi-file refactors, long autonomous
   plans, or when the user says "let the agent handle this end-to-end".
3. **Both servers run in `mode=safe`.** Writes through these tools
   require `confirm=true`. Never set it speculatively.
4. **Persistence is per-server.** Each server has its own storage
   directory. They are NOT shared with this workspace's `MEMORY.md`.
5. **MCP tools are long-running.** Not suitable for fast interactive
   loops. For "what's in this file" use `read_file`, not
   `agy_run_task`.
6. **`workspace_path` is auto-filled. Never invent it.** If you need
   a scratch area, create a subdirectory **inside** the active
   workspace. If you must operate outside `ALLOWED_ROOTS`, stop and
   ask the user to widen the policy.

## CLI Interaction Tips

When the user is running `femtobot agent` interactively, they have
access to short-cuts in the REPL:

- **Multiline prompts**: end a line with `\` + Enter to insert a
  newline without submitting. `Ctrl+D` submits, `Ctrl+C` cancels.
- **Bash shortcuts**: prefix any line with `!` to run a shell
  command directly. Output is shown inline but does **not** enter the
  agent loop.
- **File references**: prefix a path with `@` to mention a file in
  the prompt.
- **Slash commands**: type `/` to see available commands.
- **Themes**: configure `agents.cli.theme` in `config.json`. Four
  presets: `terracotta-claude` (default), `solarized-light`,
  `cyber-dark`, `monochrome`.


## Time, Date, and Calendar

If you need to know the current time, timezone offset, or calendar
information, call the `femtobot_timer` tool.  Do not estimate UTC
offsets from training data: timezone rules change and DST shifts
vary by jurisdiction.  Use `femtobot_timer(info_type="time")` for
a quick "what time is it" and `femtobot_timer(info_type="all")`
for the full report (UTC, user local, calendar, server context).
The tool's timezone comes from `agents.defaults.timezone` in
`config.json` and may be overridden per workspace via
`tools.timer.timezone_override`.

## See Also

- `SOUL.md` — personality
- `USER.md` — user profile
- `MEMORY.md` — accumulated long-term memory
- `docs/mcp.md` — MCP server configuration reference
