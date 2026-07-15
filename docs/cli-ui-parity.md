# UI Parity with Claude Code v2.1.x (v0.1.0-ui.0 preview)

Starting with the `v0.1.0-ui.0` release, `femtobot agent` can render the
REPL with an aesthetic layer that mirrors Claude Code v2.1.x. The layer
is **opt-in**, **additive**, and **fall-back-safe** — the v0.0.x
experience is unchanged by default.

This document covers:

1. [What you get](#what-you-get)
2. [How to enable it](#how-to-enable-it)
3. [The three profiles](#the-three-profiles)
4. [Auto-fallback rules](#auto-fallback-rules)
5. [The permission prompt](#the-permission-prompt)
6. [Slash commands](#slash-commands)
7. [Theme support](#theme-support)
8. [Troubleshooting](#troubleshooting)

See also:

- [CLI reference](cli-reference.md) — the complete CLI flag matrix
- [plans/claude_code_cli_parity/PLAN_claude_code_cli_parity_20260715.md](../plans/claude_code_cli_parity/PLAN_claude_code_cli_parity_20260715.md) — the design plan

---

## What you get

When `ui_parity=compat`, the REPL renders:

- A **header bar** with the `__logo__` ASCII wordmark, your name (from
  `config.agents.user.name`), the active model, and the workspace path.
- A **welcome card** on the first turn (Tips + What's new, parsed from
  `CHANGELOG.md`). Hidden after the first turn; re-displayed by `/welcome`.
- A **notice block** during the preview release, pointing at the
  `/ui` slash command and the `--ui` flag.
- A **spinner with elapsed time** ("✻ Cogitating… (12s)"). The seconds
  update on the existing Rich auto-refresh — no extra thread.
- **Tool call cards** with a collapsed one-line summary by default, and a
  first-line preview of the result on `Ctrl+O` (verbose toggle).
- A **status footer** with three states: idle (`⏸ manual mode`),
  propagating (`* Propagating… (Ns · ↓ N tokens)`), and cooked
  (`✻ Cooked for Ns`).
- An **input pill bar** (Claude Code v2.1.x parity, `v0.1.0-ui.1`+) with
  a thin accent rule above and below the prompt row, a bold `❯` glyph
  in the active theme accent, and a dim placeholder ("Nova mensagem")
  shown only while the input buffer is empty.
- An **interactive permission prompt** for `risk_level=high` tools
  (`exec`, `long_task`, `complete_goal`, `ask_orchestrator`), opt-in
  via `agents.cli.permission_prompt.enabled=true`.

All of this composes **on top of** the existing
`StreamRenderer` — the runtime is unchanged. There are zero
behavioural regressions on the legacy `off` profile.

### Input pill bar (visual reference)

Below is a sketch of the prompt area under `ui_parity=compat`. The
horizontal rule is the accent color (`theme.welcome_border`, dim
when idle). While the buffer is empty, a dim placeholder ("Nova
mensagem") is shown next to the bold `❯` glyph; prompt_toolkit
redraws the bottom row on every key event.

```
 ────────────────────────────────────────────────────────────  (top rule)
 ❯ Nova mensagem                                                  (placeholder)
 ────────────────────────────────────────────────────────────  (bottom rule)
```

When the user starts typing, the placeholder disappears and the
input buffer fills that cell. The bar survives paste, history
navigation, and `Ctrl+O` (verbose toggle) without ghost artefacts.

## How to enable it

### Per-session (Q10 — does NOT persist)

```sh
femtobot agent --ui compat
# or, mid-session:
/ui compat
```

### Persistent (writes to `config.json`)

```sh
femtobot agent --ui compat   # then /style to persist, or:
# via /style (writes to config.json):
/style set ui_parity=compat
```

Or edit `config.json` directly:

```json
{
  "agents": {
    "defaults": {
      "cli": {
        "ui_parity": { "profile": "compat", "notice": true }
      }
    }
  }
}
```

### Disable the v0.0.x style (back to plain Rich)

```sh
femtobot agent --ui off
# or:
/ui off
```

## The three profiles

| Profile    | What it does                                                                                  | When to use                                                | Pipes? |
|------------|-----------------------------------------------------------------------------------------------|------------------------------------------------------------|--------|
| `off`      | Legacy `StreamRenderer` (the v0.0.x default).                                                 | Pipes, scripts, CI, or when you want the v0.0.x feel.      | ✅     |
| `compat`   | Rich `Live` + `prompt_toolkit` with the parity widgets on top (header, welcome, tool cards, …).| Interactive sessions where you want the Claude-Code look.  | auto-fallback to `off` if not a TTY |
| `full`     | **Textual TUI** — full-screen, mouse support, scrollable history.                             | Long interactive sessions, mouse-friendly terminals.      | ❌ forces TTY |

`full` is **not available in the v0.1.0-ui.0 preview** — it arrives in
the RC release `v0.1.0-ui.1`. Asking for `--ui full` on the preview
prints a one-line notice and falls back to `off`.

## Auto-fallback rules

To preserve pipe-friendliness, the resolver (`cli/renderer_factory.py`)
forces `off` when:

- `sys.stdout.isatty()` is `False` (pipe, `tee`, `docker exec` without `-t`).
- `NO_COLOR` is set (Rich loses colour codes anyway).
- `TERM=dumb` is set.
- The user requested `full` in a release where it is not yet enabled.

These rules are applied **before** the renderer is constructed — they
do not crash pipes, do not pollute the prompt with control sequences,
and do not require configuration.

## The permission prompt

When `agents.cli.permission_prompt.enabled=true`, the agent **pauses**
before calling any `risk_level=high` tool and shows a numbered prompt:

```
● Exec("rm -rf /tmp/build_artifacts")
  ⎿ Runs a shell command on your machine.

  Do you want to proceed?
❯ 1. Yes
  2. Yes, and don't ask again for Exec in this session
  3. No

  Esc to cancel · Enter to confirm default (Yes)
```

Press `1` to run once, `2` to run for the rest of the session, `3` to
refuse, or `Enter` for the default (Yes). `Ctrl+C` or `Esc` cancels
without running the tool.

### Risk taxonomy (Q4 — see `security/tool_risk.py`)

| Risk    | Tools                                                                                          | Default prompt?     |
|---------|------------------------------------------------------------------------------------------------|---------------------|
| `high`  | `exec`, `long_task`, `complete_goal`, `ask_orchestrator`                                       | **Yes** (when enabled) |
| `medium`| `apply_patch`, `write_file`, `edit_file` (inside workspace); `web_fetch` (GET)                | No (passes silently) |
| `low`   | `read_file`, `list_dir`, `find_files`, `grep`, `web_search`, `femtobot_timer`                  | No (passes silently) |

`write_file` / `edit_file` / `apply_patch` are **promoted to `high`**
when the resolved path is outside the configured workspace
(`agents.defaults.workspace`).

To also prompt for `medium` tools, set
`agents.cli.permission_prompt.high_risk_only=false`.

## Slash commands

| Command           | Description                                                  |
|-------------------|--------------------------------------------------------------|
| `/ui`             | Show the active profile + the available profiles             |
| `/ui off`         | Switch to `off` for this session                             |
| `/ui compat`      | Switch to `compat` for this session                          |
| `/ui full`        | Switch to `full` (not yet available in the preview)          |
| `/welcome`        | Re-display the welcome card mid-session                      |
| `/release-notes`  | Show the top of `CHANGELOG.md` (parsed automatically)        |

`/ui` is **per-session** — the change dies on REPL exit. To persist,
use `/style set ui_parity=...` (writes to `config.json`).

## Theme support

The parity widgets reuse the existing `CliTheme` palette plus three
new tokens (set per-theme in `cli/theme.py`):

| Token                | Default (terracotta-claude) | Used by                          |
|----------------------|------------------------------|----------------------------------|
| `welcome_border`     | `#d77757`                    | Welcome card + What's new box    |
| `permission_accent`  | `#b1b9f9`                    | Permission prompt number highlight|
| `tool_card_border`   | `#fd5db1`                    | Tool call card border            |

The 4 bundled themes (`terracotta-claude`, `solarized-light`,
`cyber-dark`, `monochrome`) all carry sane defaults; pick
`/style set theme=cyber-dark` for the neon look, etc.

## Troubleshooting

| Symptom                                                | Likely cause                                  | Fix                                                |
|--------------------------------------------------------|-----------------------------------------------|----------------------------------------------------|
| REPL ignores `--ui compat`                             | Pipe / no TTY / `NO_COLOR`                    | Run in a real terminal                              |
| `full` returns "arrives in v0.1.0-ui.1"                | Preview release — `full` not available yet    | Use `compat` (or wait for the RC)                   |
| Welcome card always present                            | `/welcome` was called, marker is sticky       | `/ui off` then `/ui compat` (resets session)        |
| Permission prompt fires on every tool                  | `permission_prompt.enabled=true`              | Set `permission_prompt.enabled=false`               |
| Permission prompt fires on `read_file` / `web_search`  | `permission_prompt.high_risk_only=false`      | Set `high_risk_only=true`                           |
| `Textual` import error                                 | `textual` not installed                       | `uv sync --extra tui` (only matters for `full`)     |
| Header bar shows `<your-name>` literally              | User has not personalised the config          | `/style set user.name="Bill Kopp"`                  |

---

## Roadmap (per the plan)

- **v0.1.0-ui.0 (this preview)** — `compat` opt-in, `full` not yet available.
- **v0.1.0-ui.1 (RC)** — `compat` becomes the default; `full` (Textual) opt-in.
- **v0.1.0-ui.2 (GA)** — bugfixes from RC review, smoke matrix across 5 terminals.

See the [design plan](../plans/claude_code_cli_parity/PLAN_claude_code_cli_parity_20260715.md)
for the full reasoning, the per-tool risk taxonomy, and the
acceptance criteria.
