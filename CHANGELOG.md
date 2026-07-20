# Changelog

All notable changes to Femtobot will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Pre-1.0 (i.e., all current versions) treats breaking changes as minor bumps
> and minor changes as patches. The first 1.0 release will lock the API.

## [0.1.0-ui.1] — 2026-07-18

> Patch release — second round of end-to-end REPL/serve smoke-testing
> on top of `0.1.0-ui.0`. Closes **11 bugs** (A-K) surfaced during
> interactive testing with the local `MiniMax-M3` provider and the
> `percival-osm` MCP server. No behavioural change for users running
> with default config; all fixes are scoped to previously-broken paths.

### Fixed

#### Slash-command dispatch (`AgentLoop._state_command`)

- **`/goal <task>` now works** in the offline `process_direct` path
  (was masked as "Unknown command" because the context-rewriting
  shortcut returns `None`). `_state_command` now consults the router's
  exact+prefix+priority tables to distinguish "matched shortcut that
  rewrote ctx.msg" from "actually unknown command". Regression:
  `tests/test_audit_2026_07_18_v4_fixes.py::test_classify_priority_command`.
- **Unknown slash commands** (`/foo`, `/tools`, …) now surface a
  friendly "Unknown command" reply listing the registered palette
  instead of silently falling through to the LLM (which would happily
  invent an answer like "here are the tools I have…").
  New helper: `AgentLoop._reply_unknown_command`. Regression:
  `tests/test_cmd_unknown_command.py`.
- **`/restart` (and other priority commands)** in `femtobot agent -m`
  no longer trigger "Unknown command: /restart" — the offline path now
  also falls through to `dispatch_priority` when `dispatch` returns
  `None`. Regression: `tests/test_audit_2026_07_18_v4_fixes.py`.

#### `/btw` side-question (`femtobot.cli.btw`)

- **`/btw <question>`** was silently failing because `run_btw` called
  a non-existent `provider.generate`. Rewired to the canonical
  `provider.chat_with_retry` (with `chat` as fallback), extracts text
  via `response.content`, and surfaces the exception type + message
  on the error path so the user can self-diagnose. `_btw_elapsed_s`
  is now stamped on both success and error replies. Tests in
  `tests/cli/test_btw.py` and `tests/test_audit_2026_07_18_v5_fixes.py`.

#### `/mcp` subcommands (`femtobot.command.builtin.cmd_mcp`)

- **`/mcp tools percival-osm`** (any server with a hyphen in its
  name) now lists the registered tools correctly. The previous
  prefix lookup flattened `-` to `_` while the tool registry
  preserves hyphens, so the prefix never matched. Fix: try both
  verbatim and underscore-flattened prefixes, and surface the
  configured server list in the empty reply. Regression:
  `tests/test_cmd_mcp.py`.

#### CLI surface (`femtobot.cli.commands`)

- **`femtobot status --folder-path /tmp/nope`** now exits 2 with a
  clear error instead of silently falling back to the nearest
  `.femtobot` on disk. Root cause: `discover_instance_dir` walks
  `[start, start.parent, cwd/.femtobot]`, so an explicitly-bad path
  was treated as "look harder". Fix validates the path up-front.
  Regression: `tests/test_audit_2026_07_18_v6_fixes.py`.
- **`femtobot tools list`** now lists all 17 builtin tools (was 5).
  The old code called `tool_cls.create(None)` and silently swallowed
  `TypeError` for every tool that needs a `ToolContext` (MCP-backed,
  config-dependent). Fix builds a real `ToolContext` with
  `MessageBus`, `workspace`, and the loaded `Config.tools`.
  `--capability read-only` now returns 7 (was 0). Regression:
  `tests/test_audit_2026_07_18_v6_fixes.py`.

### Verified (no fixes required)

- **`femtobot serve`** — `POST /v1/chat/completions` (sync + SSE
  stream), `GET /v1/models`, error path (HTTP 400 on malformed
  body). Per-session context isolation verified end-to-end with
  `session_id` keys `sessionA` / `sessionB`.
- **`exec` tool** — exit codes and stderr correctly surfaced for
  missing paths, permission denied, `command not found` (exit 127),
  and successful runs.
- **`/goal` auto-completion** — when the model autonomously calls
  `complete_goal` before the user types `/goal complete`, the
  follow-up command correctly reports "No active goal".

### Test suite

- **1403/1403 tests pass** (1398 → 1403). Six new test files
  pin the fixes down:
  `test_audit_2026_07_18_v3_fixes.py`, `…_v4_fixes.py`,
  `…_v5_fixes.py`, `…_v6_fixes.py`, `test_cmd_unknown_command.py`,
  plus updates to `test_cmd_mcp.py` and `tests/cli/test_btw.py`.

### Upgrade notes

- Drop-in replacement for `0.1.0-ui.0`. No config migration needed.
- Users on `0.1.0a0` (pre-UI-parity) get the parity-layer fixes on
  top of the CLI fixes; the `ui_parity=off` default keeps behaviour
  identical to `0.1.0-ui.0` for those not opting into the new
  parity profiles.

## [0.1.0-ui.2] — 2026-07-19

> Patch release — third round, addressing the **9 visual / structural
> bugs** surfaced by the interactive `femtobot agent --ui compat`
> session recorded in `longlogs.txt` (2026-07-19 09:29) against the
> `percival-osm` MCP server. Closes issue #1. No behavioural change
> for users running with default config; all fixes are scoped to
> the interactive REPL surface.

### Fixed

#### Interactive TUI — `femtobot cli commands._read_interactive_input_async`

- **B1 / B6 / B7 — spinner & `Live` racing the user prompt**: the
  renderer could still be running a leftover `Live` display or a
  `console.status` spinner from a previous turn that did not stop
  cleanly (mid-tool-call cancellation, runner exception, etc.).
  The legacy profile was rendering `[ 👤 You ]` and the user's
  input on top of those leftover frames, producing interleaved
  output like `?[2K?[32m▰▰▰▰▱▱▱?[0m ?[2mFemtobot is cogitating…?[0m`.
  Fix: call `renderer.stop_for_input()` immediately before
  `print_input_gap()` / `print_user_box()` so any leftover
  spinner is force-stopped before the prompt header is rendered.
  Regression: `tests/test_longlogs_issue1_fixes.py`.

#### MCP stdio subprocess stderr (`femtobot.agent.tools.mcp`)

- **B2 — MCP logs leaking into femtobot stderr**: `mcp.client.stdio
  .stdio_client` defaults `errlog` to `sys.stderr`, so the MCP
  subprocess (e.g. `percival-osm`) inherited the femtobot's stderr
  and its `INFO mcp.server.lowlevel.server: Processing request of
  type CallToolRequest` lines were interleaved with the user's TUI
  input (also visible as `[?25l` cursor-hide escapes mixed into
  the agent's response). Fix: route each server's stderr to a
  per-server rotating log file at
  `<instance_dir>/logs/mcp-<server>.log` via the new
  `_resolve_mcp_errlog` helper; falls back to `subprocess.DEVNULL`
  when the log dir cannot be resolved (never `sys.stderr`).
  New path helper: `femtobot.config.paths.get_logs_dir()`.
  Regression: `tests/test_longlogs_issue1_fixes.py`.

#### Startup MCP warnings (`run_interactive`)

- **B8 — startup warnings racing the first prompt**: `agent_loop
  ._connect_mcp` publishes `OutboundMessage(channel="cli",
  chat_id="startup", …)` for any MCP server configured-but-
  disconnected or referenced-but-unconfigured. Before this fix the
  warnings raced with the first user keystroke because the REPL
  was already blocking on `prompt_async`. Fix: drain up to 8
  `cli:startup` messages from the bus inside `run_interactive`
  *before* the REPL loop starts, with a 0.15s timeout per message.
  Regression: `tests/test_longlogs_issue1_fixes.py`.

### Verified (no fixes required)

- All 12 surface endpoints of `percival-osm` (`osm_geocode`,
  `osm_find_place[_detailed]`, `osm_find_address`,
  `osm_find_nearby[_detailed]`, `osm_navigate`, `osm_directions`,
  `osm_get_health`, `osm_get_version`, plus the 2 resources and
  3 prompts) respond correctly end-to-end against the live MCP
  server.
- Resource `osm://security/nanobot-policy` returns the placeholder
  in this installation; the fix lives in the `percival-osm` server
  (packaging `nanobot-policy.md`), not in femtobot.
- The `RuntimeWarning: coroutine 'Context.info' was never awaited`
  warnings originate inside the `percival-osm` server's handlers
  (need `await ctx.info(...)`); they no longer reach the femtobot
  TUI once B2 is fixed.

### Test suite

- **1408/1408 tests pass** (1403 → 1408). New file:
  `tests/test_longlogs_issue1_fixes.py` (5 tests covering B1, B2,
  B8 plus a structural invariant check).

### Upgrade notes

- Drop-in replacement for `0.1.0-ui.1`. No config migration needed.
- MCP server logs that used to land in the user's terminal now
  live under `<instance_dir>/logs/mcp-<server>.log`. To watch
  them in real time: `tail -f "$(femtobot config get
  --instance-dir)/logs/mcp-<server>.log"`.
- The 2 outstanding server-side bugs (`await ctx.info()` and
  `nanobot-policy.md` packaging) are tracked in issue #1 but
  are owned by the `percival-osm` repository, not femtobot.

## [0.1.0-ui.3] — 2026-07-19

> Patch release — fourth round, addressing a **renderer-stable race**
> surfaced by a follow-up interactive `femtobot agent --ui compat`
> session recorded in `longlogs.txt` (2026-07-19, lines 74-102). Closes
> issue #2. Two complementary fixes ship together: (PR #1) per-turn
> `turn_id` tokens age out late-arriving `OutboundMessage`s, and
> (PR #2) the underlying `StreamRenderer` is rebuilt every turn so
> per-turn state (`_buf` / `_live` / `_ENDED`) can never bleed across
> the `[ 👤 You ]` boundary. Mirrors the `nanobot/cli/commands.py`
> reference where a fresh `StreamRenderer` is instantiated per turn.
> No behavioural change for users running with default config; all
> fixes are scoped to the `ui_parity=compat` profile.

### Fixed

#### Interactive TUI — `femtobot.cli.commands.run_interactive`

- **PR #1 — Turn-token guard against late-arriving bodies**: in
  `ui_parity=compat` mode the renderer was reused across turns (so
  the parity `HeaderBar` and `Welcome card` only render once). That
  shared state combined with two concurrent body surfaces (stream
  deltas vs. `_print_agent_response` fallback) produced a race:
  the trailing `_streamed=True, _stream_end_pending=True`
  `OutboundMessage` of turn *N* could deliver *after* the REPL had
  already printed the `[ 👤 You ]` header of turn *N+1*, leaking
  previous-turn body content under the user's input row. Fix: every
  user turn now mints a fresh UUID `metadata["_turn_id"]`; the REPL
  consumers drop any `OutboundMessage` whose `_turn_id` does not
  match the active turn. Background notifications (`cli:startup`,
  `_progress`, `_retry_wait`, `_runtime_control`) carry no
  `_turn_id` and continue to flow through unchanged.
  Regression: `tests/test_longlogs_issue2_fixes.py` (3 turn-token
  tests including the simulated-bus race scenario).

#### Interactive TUI — `femtobot.cli.parity_stream`

- **PR #2 — Per-turn `StreamRenderer` rebuild, parity layer kept**:
  a new `ParityStreamRenderer.replace_core(new_core)` lets the REPL
  swap the underlying `StreamRenderer` on every turn while keeping
  the parity surface (HeaderBar / Welcome card / input-bar markup /
  theme) stable. This matches `nanobot/cli/commands.py`'s per-turn
  renderer construction and removes the entire class of state
  leakage (the `_buf`, `_live`, `_ENDED` triple) that caused B1/B6/B7
  in issue #1 to recur across turns. New spins of the
  `ThinkingSpinner` render the `<bot_name> is <verb>…` line
  immediately after the user submits — matching the original v0.0.x
  UX. Regression: `tests/test_longlogs_issue2_fixes.py` (4 renderer
  rebuild tests including the `replace_core` delegation contract).

### Test suite

- **1415/1415 tests pass** (1408 → 1415). New file:
  `tests/test_longlogs_issue2_fixes.py` (7 tests covering turn-token
  drop semantics, simulated-bus race, `replace_core` API, per-turn
  rebuild contract, and a bundle check that both fixes coexist).

### Upgrade notes

- Drop-in replacement for `0.1.0-ui.2`. No config migration needed.
- The `[ 👤 You ]` prompt now reliably appears **before** any
  body of the previous turn completes rendering. If your session was
  relying on the old interleaving as a visual cue (e.g. you checked
  the on-screen text for "is the response finished?"), use the new
  `✻ Cooked for Ns` footer as the authoritative "turn done" signal
  (parity profile) or the spinner clearing in the legacy profile.
- Operators on `ui_parity=full` (Textual TUI) are unaffected — the
  rebuild path skips when `replace_core` is missing.

## [0.1.0-ui.4] — 2026-07-20

> Patch release — **regression fix**. A new follow-up interactive
> session (recorded in 2026-07-20 10:08 screenshots, issue #3)
> surfaced a regression introduced by `0.1.0-ui.3`'s PR #2
> per-turn `StreamRenderer` rebuild. The PR #2 attempt to mirror
> `nanobot`'s per-turn renderer construction **leaked the previous
> Rich `Live` and `ThinkingSpinner`**: two `Live` displays competed
> for the same `sys.stdout`, producing raw ANSI byte sequences in
> the middle of the response, spinner state interleaving between
> turns, and markdown tables rendered as one ANSI-fragment per
> character. This release reverts PR #2 in full and relies
> exclusively on PR #1 (the turn-token guard from `0.1.0-ui.3`) to
> close the original issue #2 race.

### Reverted

#### Interactive TUI — `femtobot.cli.parity_stream`

- **`ParityStreamRenderer.replace_core(new_core)` removed**. The
  per-turn core swap created a second Rich `Console` and a second
  `Live` display on every turn. Because `_make_console()`
  (`stream.py:71-82`) builds a new Console with
  `force_terminal=sys.stdout.isatty()` and `_start_spinner()`
  (`stream.py:236`) immediately spawns a new `Live`, every
  `replace_core` left the previous core's spinner thread running.
  Two `Live` displays iterating against the same stdout produced
  the raw escape fragments seen in the issue #3 screenshots.

#### Interactive TUI — `femtobot.cli.commands.run_interactive`

- **Per-turn `StreamRenderer` instantiation removed** (the
  `new_core = StreamRenderer(...)` block). Replaced with a
  comment explaining why the rebuild path is closed off, and
  referencing issue #3. The renderer is now stable across
  turns, matching the original v0.0.x design intent where the
  parity `HeaderBar` + `Welcome card` only render once.

### Fixed (carry-over from 0.1.0-ui.3 PR #1, now sole race fixer)

- The **turn-token guard** (`commands.py:_is_for_current_turn`)
  remains in place and is now the **only** mechanism preventing
  the longlogs.txt 2026-07-19 issue #2 race. Each user turn
  mints a UUID `_turn_id`; the consumer drops any
  `OutboundMessage` whose `_turn_id` does not match the active
  turn. Background notifications (no `_turn_id`) remain
  unaffected.

### Test suite

- **1415/1415 tests pass** (was 1416 in `0.1.0-ui.3`; one issue
  #2 test was consolidated into one asserting both the
  presence of PR #1 and the absence of PR #2).
- **Updated** `tests/test_longlogs_issue2_fixes.py`:
    - `test_parity_renderer_has_no_replace_core` — asserts
      `ParityStreamRenderer.replace_core` does NOT exist.
    - `test_replace_core_swaps_underlying_renderer` —
      repurposed to verify `ParityStreamRenderer._base` is the
      same `StreamRenderer` instance passed to the constructor
      (no swap) and that `replace_core` is absent.
    - `test_turn_token_guard_present_and_replace_core_absent`
      — bundle check; the consumer-side guard must be present
      AND the renderer-side rebuild path must be absent.
    - The previous `test_run_interactive_rebuilds_core_per_turn`
      and `test_both_fixes_present` were rewritten/merged into
      the bundle check.

### Upgrade notes

- Drop-in replacement for `0.1.0-ui.3`. **If you installed
  `0.1.0-ui.3`, upgrade immediately** — `0.1.0-ui.3` leaks Rich
  `Live` displays on the second turn onwards.
- Operators on `ui_parity=full` (Textual TUI) and `ui_parity=off`
  (legacy `print_agent_response`) are unaffected — both
  profiles never consumed `replace_core`.

## [Unreleased]

### Femtobot 1.0 — PydanticAI migration (Phases 0-9)

> **Scope:** lays the PydanticAI 1.31 + Logfire 3.25 foundation
> alongside the legacy AgentLoop. The legacy CLI, parity layer,
> providers, and agent loop remain the production code path; the new
> `FemtobotAgent` is opt-in. No breaking changes in this branch.
> See `docs/migration-from-0.1.x.md` for the per-phase breakdown.

#### Added
- **PydanticAI 1.31 + Logfire 3.25** as runtime deps (Phase 0).
- `femtobot/observability/logfire_setup.py` with opt-in `configure()`,
  `instrument_pydantic_ai()`, `instrument_httpx()` helpers (Phases 0+6).
- `femtobot/agent/deps.py` (`FemtobotDeps`) and
  `femtobot/agent/output.py` (`FemtobotOutput` typed response model
  with empty/internal-leakage validators) (Phase 1).
- `femtobot/agent/femtobot_agent.py` — `FemtobotAgent` factory with
  `_build_model()` dispatcher (OpenAI / Anthropic / Bedrock / Gemini)
  and `build_system_prompt()` (Phases 1+5).
- `femtobot/agent/toolsets/femtobot_timer.py` — pilot migration of the
  legacy `FemtobotTimerTool` to a PydanticAI `Tool` (Phase 1).
- `femtobot/agent/toolsets/_combined.py` — `combined_toolset(config)`
  aggregator and `FemtobotAgent.use_combined_toolset=True` opt-in
  (Phase 3).
- `femtobot/agent/runner_helpers.py` —
  `persist_tool_result` / `post_run_autocompact` / `post_run_session_save`
  scaffolds (Phase 4).
- `docs/observability.md` — full Logfire / OTel env-var reference
  (Phase 6).
- `tests/observability/test_logfire_setup.py` — hermetic CI guard
  (Phase 6).
- `tests/agent/test_runner_helpers.py` — no-op fallback coverage
  (Phase 4).

#### Removed
- Six isolated parity-layer files with no external callers:
  `cli/suggestion.py`, `cli/mouse.py`, `cli/fullscreen.py`,
  `cli/transcript.py`, `cli/virtual_transcript.py`, `cli/voice.py`
  (plus their tests) — Phase 2.

#### Changed
- Lazy-loading of `femtobot.*` submodules in `femtobot/__init__.py`
  now recognises the package's valid submodule set instead of caching
  `AttributeError` lookups (Phase 0).
- `_build_model()` extends to all four native PydanticAI providers
  with actionable `RuntimeError`s for missing optional SDKs (Phase 5).

#### Not removed (deferred — would cascade-break the 1340-test suite)
- `cli/parity_stream.py`, `cli/parity_widgets.py`, `cli/textual_app.py`,
  `cli/keybindings.py`, `cli/renderer_factory.py`, `cli/plugins/*`,
  `cli/whimsy.py`, `cli/status_line.py`.
- `agent/loop.py` (2179 LOC), `agent/runner.py` (1895 LOC),
  `agent/tools/*.py` legacy tool ABCs.
- `providers/*.py` legacy provider implementations and
  `providers/registry.py`.
- `bus/runtime_events.py`, `bus/progress.py`,
  `agent/progress_hook.py`.

A dedicated future branch with parallel test-parity scaffolding will
land the full replacement. This branch intentionally keeps the legacy
code path as the production path.

## [0.1.0-ui.0] — 2026-07-15

> Preview release — opt-in UI parity layer that aligns the Femtobot
> `agent` REPL with the Claude Code v2.1.x aesthetic. **No behavioural
> regression** by default: `ui_parity=off` keeps the v0.1.x behaviour
> exactly. The `compat` profile is the new opt-in path; `full` (Textual
> TUI) arrives in the RC `v0.1.0-ui.1`. Design plan:
> [`plans/claude_code_cli_parity/PLAN_claude_code_cli_parity_20260715.md`](plans/claude_code_cli_parity/PLAN_claude_code_cli_parity_20260715.md).

### Added
* **`agents.cli.ui_parity` config block** — opt-in profile selector
  (`off | compat | full`) with auto-fallback to `off` on pipes /
  `NO_COLOR` / `TERM=dumb`. Default in this preview is `off` (no
  behaviour change). See `docs/cli-ui-parity.md`.
* **`agents.cli.permission_prompt` config block** — interactive
  permission prompts before tool calls, opt-in. Only `risk_level=high`
  tools (`exec`, `long_task`, `complete_goal`, `ask_orchestrator`)
  trigger a prompt by default; `medium` tools can be opted in via
  `high_risk_only=false`.
* **`agents.user.name` config field** — display name used by the
  parity header bar and welcome card. Seeded with the
  `<your-name>` placeholder by `build_default_onboard_config()`
  so users can grep for it and personalise via
  `/style set user.name="Bill Kopp"`.
* **`security/tool_risk.py`** — per-tool risk taxonomy (high / medium
  / low). New module: the v0.1.x code did not classify tools by
  risk, so this is **new work**, not a re-use of an existing
  catalogue. Unknown tools default to `medium` (conservative
  mid-point). Path-based escalation promotes in-workspace writes
  to `high` when the target is outside `agents.defaults.workspace`.
* **`femtobot/cli/parity_widgets.py`** — Rich renderables for the
  parity layer: `HeaderBar` (using the `__logo__` ASCII wordmark
  from `femtobot/__init__.py`), `WelcomeCard` with parsed
  `CHANGELOG.md` "What's new" (Q6), `ToolCard` (collapsed by
  default, first-line heuristic preview per Q7), `SpinnerWithElapsed`
  (no extra thread — reuses the existing Rich `Live` auto-refresh,
  per rev. F5), `StatusFooterParity`, and `InputPill`.
* **`femtobot/cli/parity_stream.py`** — `ParityStreamRenderer`, a
  drop-in wrapper around `StreamRenderer` that composes the
  parity widgets on top of the legacy rendering pipeline. Same
  `on_delta / on_end / on_tool_call / on_trace` interface; the
  agent loop is unchanged.
* **`femtobot/cli/renderer_factory.py`** — `build_renderer(config)`
  returns the right renderer for the active profile. Pipes and
  `NO_COLOR` force `off`; `full` is not yet available in this
  preview and falls back with a one-line notice.
* **`femtobot/cli/permission_prompt.py`** — per-session
  `PermissionCollector`. Self-contained (does not depend on
  `session/pending_asks.py` — that is an async cross-process
  correlation mechanism, not a synchronous REPL prompt, per
  rev. F2). Numbered prompt: `1` Yes / `2` Yes-always-for-session
  / `3` No / `Esc` Cancel.
* **`--ui` flag on `femtobot agent`** — per-session profile
  selector: `femtobot agent --ui compat` (does not persist to
  `config.json`; use `/style set ui_parity=compat` for that).
* **Slash commands** — `/ui` (show / swap profile per-session,
  Q10), `/welcome` (re-display the welcome card mid-session,
  Q3), `/release-notes` (parsed top-of-CHANGELOG, Q6).
* **`docs/cli-ui-parity.md`** — dedicated documentation page
  covering the visual specification, the risk taxonomy, the
  permission flow, and a troubleshooting matrix.
* **CLI theme tokens** — `welcome_border`, `permission_accent`,
  `tool_card_border` added to all four bundled themes
  (`terracotta-claude`, `solarized-light`, `cyber-dark`,
  `monochrome`).

### Tests
* 126 new tests across:
  - `tests/cli/test_ui_parity_config.py` (11)
  - `tests/security/test_tool_risk.py` (30)
  - `tests/cli/test_theme.py` (+6 for parity tokens)
  - `tests/cli/test_parity_widgets.py` (28)
  - `tests/cli/test_renderer_factory.py` (14)
  - `tests/cli/test_parity_stream.py` (9)
  - `tests/cli/test_permission_prompt.py` (16)
  - `tests/cli/test_ui_slash_commands.py` (9)
  - `tests/test_helpers_user_name.py` (3)
* **Total:** 1164 passing (up from 1038 in v0.1.8), no regressions.

### Notes
* The Textual TUI (`ui_parity=full`) is **not** in this preview.
  It is scheduled for the RC `v0.1.0-ui.1`. The factory emits a
  one-line notice and falls back to `off` if `full` is requested.
* `permission_prompt` does not write to `config.json`. The
  "Yes, and don't ask again" answer is per-session (Q10) — it
  resets when the REPL exits.

## [0.1.8] — 2026-07-10

> Lote P: Twelfth-pass Session-Manager parity push (Issues 1-6 closed,
> 9 tests novos, novo CLI ``sessions`` command group).  Compat 100%
> com v0.1.7.

### Added
* **`femtobot sessions` CLI command group** em
  [cli/sessions.py](femtobot/cli/sessions.py).  Sub-commands:
  - ``femtobot sessions list`` — list every persisted session with
    size, updated_at, message_count, and metadata-title.
  - ``femtobot sessions show <key>`` — print metadata + last 5
    messages of one session.
  - ``femtobot sessions delete <key>`` — remove the session file
    (workspace + legacy paths) and in-memory cache.  Confirmação
    via typer.confirm (skip com ``--yes``).
  Resolves a long-standing gap: v0.0.7-v0.1.7 had ``SessionManager
  .delete_session`` defined but never called by anyone.  Femtobot
  agora dá ao usuário uma forma explícita de prune os .jsonl files
  que vão acumulando em ``workspace/sessions/``.

### Fixed
- **(Issue 2) `delete_session` removes workspace + legacy paths**.
  Antes o método só apagava o workspace path e ignorava os legacy
  paths (v0.1.7).  Agora remove ambos os locations, evitando
  ghost copies de sessões migradas — match upstream nanobot.

- **(Issue 6) Stem round-trip stability**: O proposto base64-tag
  encoding (``_storage_key`` / ``_decode_storage_key``) foi **revertido**
  para manter compat com os 8 arquivos já existentes em
  ``workspace/sessions/`` (escritos com a convenção ``:``->``_``
  legacy).  Opt-in helpers (``_storage_key``,
  ``_decode_storage_key``) ficam como alias / escape hatches para
  uma migration futura em v0.2.

### Tests
- 1 novo arquivo de test (9 testes de regressão):
  - `tests/test_session_management.py` — cobre Issues 1-5
    (CLI wiring, 3-path delete, public surface, list/show
    commands, edge cases).

- 2 stale tests fixos incidentalmente:
  - `tests/test_agents_template_mcp.py::test_template_mcp_section_contains_expected_rules`
  - `tests/test_agents_template_mcp.py::test_template_mcp_section_warns_against_speculative_confirm`
  Ambos tinham path hardcoded antigo
  (``/home/bill/Codes/CLI-router-project/femtobot/...``) e
  expectativas sobre template anterior.  Atualizados para o novo
  path + nova convenção ``*_run_task`` + confirmação de que o
  template advoga ``confirm=true`` (não ``confirm=false``).

### Validation
- Suite: **718 passed, 0 failed** (9 testes a mais que v0.1.7,
  +2 stale tests fixos incidentalmente).
- Ruff: **All checks passed!**.
- Smoke test:
  ``femtobot sessions list`` retorna as 8 sessões reais com size
  correto (2.78MB para cli:direct, 487-514B para os outros);
  ``femtobot sessions delete cli:smoke --yes`` apaga o .jsonl;
  ``femtobot sessions show cli:smoke`` prints last 5 messages.

### Migration
Compat 100% com v0.1.7.  Mudanças:
- novo CLI command group ``sessions``.
- ``delete_session`` agora também remove legacy paths.

## [0.1.7] — 2026-07-10

> Lote O: Eleventh-pass CLI parity push (full parity, 7 issues all closed,
> 15 tests novos).  Compat 100% com v0.1.6.

### Fixed / Restored from nanobot (CLI parity)
- **(Issue 1) `femtobot onboard` wizard is now opt-in only** em
  [cli/commands.py](femtobot/cli/commands.py).  Removido o
  auto-trigger ``if wizard or (sys.stdin.isatty() and ...)`` que
  derrubava o usuário em prompts interativos a cada invocation
  num TTY.  Agora o wizard só roda com a flag explícita
  ``--wizard``.  Em non-TTY (CI/pipe), ``--wizard`` cai com
  warning em vez de bloquear.
- **(Issue 2) Welcome header 2-line** em
  [cli/onboard_wizard.py](femtobot/cli/onboard_wizard.py).
  Explica o que o wizard faz e quantos prompts rodam, antes do
  primeiro input.
- **(Issue 3) Main menu (Quick Start / Exit)** em
  [cli/onboard_wizard.py](femtobot/cli/onboard_wizard.py).
  Usuário pode abortar antes de responder qualquer prompt.
- **(Issue 4) API-key prefix confirmation** em
  [cli/onboard_wizard.py](femtobot/cli/onboard_wizard.py).
  Echo dos primeiros 4 chars do key após captura, para pegar
  paste-with-extra-spaces bugs.
- **(Issue 5) Silent exception swallowing removido** em
  [cli/commands.py](femtobot/cli/commands.py).  O bloco
  ``try: load_config(config_file); except: pass`` no wizard_result
  branch foi removido.  Config in-memory tem precedência quando o
  wizard produziu mutação.
- **(Issue 6) `_CURATED_MODELS` data-driven from registry** em
  [cli/onboard_wizard.py](femtobot/cli/onboard_wizard.py).
  Adicionado fallback registry-derived para provedores não
  hardcoded.  `_env_key_for` agora lê `env_key` do ProviderSpec
  primeiro, antes do pequeno dict hardcoded.  Adicionar novo
  provider no registry já surface automaticamente no wizard.
- **(Issue 7) Suffix validation moves before wizard** em
  [cli/commands.py](femtobot/cli/commands.py).  Order agora é:
  validate → resolve_dir → write_config → wizard.  Antes o
  usuário respondia prompt de provider e só então recebia
  "Invalid suffix".

### Tests
- 1 novo arquivo de test (15 testes de regressão):
  - `tests/test_cli_parity.py` — cobre os 7 issues +2 helpers

### Validation
- Suite: **709 passed, 0 failed** (15 testes a mais que v0.1.6).
- Ruff: **All checks passed!**.
- Smoke test: ``femtobot onboard`` agora roda silencioso e
  mostra "Next Steps" sem entrar no wizard.  ``femtobot
  onboard --wizard`` ainda funciona.

### Migration
Compat 100% com v0.1.6.  Mudança principal é UX: usuário
precisa digitar ``--wizard`` explicitamente para entrar no
wizard interativo.

## [0.1.6] — 2026-07-10

> Lote N: Ninth-pass feature add — port ``nano_timer`` from nanobot.
> Compat 100% com v0.1.5 (apenas additiva).

### Added
- **`femtobot_timer` tool** em
  [agent/tools/time.py](femtobot/agent/tools/time.py).  Fornece
  UTC + horário local do usuário + calendar (weekday, week-of-year,
  day-of-year) + contexto server/user timezone.  Porta
  ``nano_timer`` do nanobot com adaptações Femtobot:
    - Renomeado de ``nano_timer`` para ``femtobot_timer``
      (decisão de branding v0.1.6).
    - Output dos dias da semana em inglês only
      (Femtobot não tem subsistema i18n; não reusamos o pt-BR
      fallback do nanobot).
    - Inclui ``tools.timer.timezone_override`` opcional (per-workspace
      override de timezone sem tocar ``agents.defaults.timezone``).
- **`TimerToolConfig`** em
  [config/schema.py](femtobot/config/schema.py).  Registrado em
  :class:`ToolsConfig` via lazy-import.  Default: ``enable=True``,
  ``timezone_override=None``.
- **Auto-discovery**: zero mudança em ``ToolLoader`` — o módulo
  ``time.py`` é auto-descoberto porque seu nome não está em
  ``_SKIP_MODULES``.
- **`_resolve_server_tz` helper** (verbatim port do nanobot):
  lida com o edge case ``TZ=Asia/Tokyo`` POSIX timestamps onde
  ``tzinfo.key`` é ``None``.
- **`_format_offset` helper**: suporta offsets not-aligned
  (India UTC+5:30, Nepal UTC+5:45, Chatham UTC+12:45).
- **AGENTS.md** section em [templates/AGENTS.md](femtobot/templates/AGENTS.md)
  (e workspace live): instrui o agente a chamar ``femtobot_timer``
  ao invés de estimar UTC offsets do training data.

### Documentation
- [docs/nano_timer_implementation_plan.md](docs/nano_timer_implementation_plan.md):
  implementation plan otimizado para Femtobot (382 linhas).

### Tests
- 1 novo arquivo de test (24 testes de regressão):
  - `tests/test_timer_tool.py` — 24 tests cobrindo:
    - Tool metadata (name, description, config_key, config_cls)
    - Configuration glue (enabled, create, default config)
    - ContextAware (set_context records channel/chat_id)
    - `_format_offset` (whole-hour, partial-hour, None)
    - `_resolve_server_tz` (returns tuple)
    - Happy paths (info_type=time/all/calendar/timezone)
    - Fallback paths (invalid timezone, empty timezone, unknown info_type, None info_type)
    - DST + Asia/Tokyo + invalid input handling
    - Auto-discovery (ToolLoader picks up ``time.py``)
    - JSON Schema shape (``parameters`` returns valid schema)

### Validation
- Suite: **694 passed, 0 failed** (24 testes a mais que v0.1.5).
- Ruff: **All checks passed!**.
- Smoke test: ``femtobot agent --message "what time is it?"``
  retorna "08:34 (America/Sao_Paulo, UTC-03:00)" — tool está sendo
  chamada em runtime.

### Migration
Compat 100% com v0.1.5.  Apenas additiva.

## [0.1.5] — 2026-07-10

> Lote M: Eighth-pass Dream parity close-out (R1-R6 all closed, 20 tests
> novos).  Compat 100% com v0.1.4.

### Fixed / Restored from nanobot
- **(R1) `_render_current_memory_files`** em
  [agent/memory.py](femtobot/agent/memory.py).  Dream prompt agora
  embed a current contents de `SOUL.md`, `USER.md`, e
  `memory/MEMORY.md` como ground truth, evitando hallucinated
  audit records.
- **(R2) `dream_content_diff` + git-ground-truth gate** em
  [agent/memory.py](femtobot/agent/memory.py) e
  [command/builtin.py](femtobot/command/builtin.py).
  `_run_dream` agora gate cursor advance no git diff real (não
  mais LLM self-report).  `build_dream_commit_message` aceita
  `diff_body` keyword para ancorar a commit message no delta
  real.
- **(R3) `_has_compactable_idle_tail`** em
  [agent/autocompact.py](femtobot/agent/autocompact.py).  Sessions
  com tail que cabe no recent-suffix window não são re-arquivadas
  redundantemente após heartbeat/internal tick.
- **(R4) `_is_internal_history_session` + `read_recent_history_for_prompt`** em
  [agent/memory.py](femtobot/agent/memory.py).  Cron, dream, e
  heartbeat sessions são filtrados fora do Dream history tail.
- **(R5) Per-file truncation** em
  [agent/memory.py](femtobot/agent/memory.py).  `_DREAM_FILE_EMBED_CAP`
  (8000 chars) com rate-limited warning.
- **(R6) Workspace override + truncation** em
  [agent/memory.py](femtobot/agent/memory.py).  Override em
  `workspace/prompts/dream.md` com `_DREAM_PROMPT_MAX_CHARS`
  (32000 chars) cap.

### Added (New Helpers)
- **`GitStore.summarize_working_tree`** em
  [utils/gitstore.py](femtobot/utils/gitstore.py).  Helper que
  retorna unified diff vs HEAD para paths específicas, com
  `_WORKING_TREE_DIFF_MAX_CHARS` cap e binary-file fallback.

### Tests
- 1 novo arquivo de test (20 testes de regressão):
  - `tests/test_dream_parity.py` (R1-R6 + F1-F3) — 20 tests

### Validation
- Suite: **670 passed, 0 failed** (20 testes a mais que v0.1.4).
- Ruff: **All checks passed!**.
- Smoke test: ``femtobot agent --message "ping"`` retorna "pong"
  diretamente.

### Migration
Compat 100% com v0.1.4.  Nenhuma quebra de API.

## [0.1.4] — 2026-07-10

> Lote L: Eighth-pass nanobot-parity hardening (3 helpers + 1 doc-only
> improvement, 21 tests novos).  Compat 100% com v0.1.3.

### Fixed / Adopted from nanobot
- **(W2) `_strip_placeholder_assistant_messages` + `_strip_malformed_tool_calls`** em
  [agent/runner.py](femtobot/agent/runner.py).  Adoção de paridade com
  nanobot `ContextGovernor.strip_placeholder_assistant_messages` /
  `strip_malformed_tool_calls`.  Defende contra dois padrões de
  corrupção de session que o bare `_drop_orphan_tool_results` não
  pegava: compaction placeholders (``[Previous assistant message
  omitted.]``) e tool_calls com `name=None`/`""`.  Aplicado na
  pipeline de governance (happy path) e no `try/except` minimal repair.
- **(W4) `_has_injection_content` helper** em
  [agent/runner.py](femtobot/agent/runner.py).  Adoção de paridade
  com nanobot.  A versão inline anterior (`text.strip()`) não
  tratava `None` (caía em `str(None)` = `"None"`, truthy) nem listas
  vazias.  Agora trata `None`, strings, listas, e tipos arbitrários
  corretamente.
- **(W5) `_build_goal_continue_message` com callable handling** em
  [agent/runner.py](femtobot/agent/runner.py).  Adoção de paridade
  com nanobot.  O spec field `goal_continue_message` agora aceita
  `str | Callable[[], str] | None` (era só `str | None`).  Um
  callable quebrado é logado e cai no default prompt, em vez de
  derrubar o run.

### Documented (no code change)
- **(W1) `capped_out` flag documentado** em
  [agent/runner.py](femtobot/agent/runner.py).  Investigamos
  migrar para o idiomático `for/else` do Python (que o nanobot
  usa com `for iteration in range(N)`) mas o Femtobot tem 4
  `break` statements em vez de 1, e o iterator é
  `itertools.count()` (infinito) para suportar a goal-extension
  dinâmica.  Por isso o `for/else` do nanobot não se aplica
  diretamente: o `else` nunca executa naturalmente num iterador
  infinito.  Mantemos o flag `capped_out` (do fix C1/v0.1.2) que
  é a solução minimal correta.  Um comentário no source
  documenta a rationale.

### Added
- 1 novo arquivo de test (21 testes de regressão):
  - `tests/test_runner_nanobot_parity.py` (W1, W2, W4, W5) — 21 testes

### Tests
- Suite: **650 passed, 0 failed** (21 testes a mais que v0.1.3).
- Ruff: **All checks passed!**.

### Migration
Compat 100% com v0.1.3.

## [0.1.3] — 2026-07-09

> Lote K: Seventh-pass hotfix (1 critical bug fix, 3 tests novos).
> Compat 100% com v0.1.2.

### Fixed
- **(K1, CRITICAL) Agent runner sobrescrevia `final_content` em todo break** em
  [agent/runner.py](femtobot/agent/runner.py).

  O loop `for iteration in itertools.count():` tinha 3 `break` statements
  (LLM error, empty response, final response), e o post-loop código
  assumia que **todo** break era por cap exhaustion. O post-loop
  então sobrescrevia `final_content` com o template
  `max_iterations_message.md` e setava `stop_reason = "max_iterations"`,
  **mesmo quando o modelo tinha produzido uma resposta válida**.

  **Sintoma**: o Femtobot respondia com "I reached the maximum number
  of tool call iterations (200) without completing the task" para
  perguntas triviais como "ping" ou "Who are you?" — porque o modelo
  M3 respondia em 1 iteração, o loop fazia o `break` legítimo
  (final response), e o post-loop overwrite escondia a resposta.

  **Fix**: nova flag `capped_out` (default False) é setada para True
  apenas no break por cap exhaustion. O post-loop finalize path é
  agora wrapped em `if capped_out:` para que os outros breaks
  (final response, empty response, LLM error) retornem a resposta
  do modelo corretamente.

### Reduced
- **`AGENTS.md`** (de 220 linhas / ~12k chars para 76 linhas / ~3k chars)
  para reduzir o system prompt de ~60k → ~51k chars. Não é o fix
  principal (K1 é), mas reduz custo por iteração.

### Added
- 1 novo arquivo de test (3 testes de regressão):
  - `tests/test_runner_early_exit.py` (K1) — 3 testes

### Tests
- Suite: **629 passed, 0 failed** (3 testes a mais que v0.1.2).
- Ruff: **All checks passed!**.

### Migration
Compat 100% com v0.1.2.

## [0.1.2] — 2026-07-09

> Lote J: Sixth-pass hardening (4 fixes, 9 tests novos).
> Compat 100% com v0.1.1.

### Fixed
- **(J1, HIGH) `apply_patch` rollback perdia permissões** em
  [tools/apply_patch.py](femtobot/agent/tools/apply_patch.py).
  `write_bytes` restaurava conteúdo mas perdia chmod bits.
  **Fix:** backup agora salva `stat_result`; rollback chama
  `path.chmod(stat.S_IMODE(st.st_mode))`.
- **(J3, HIGH) `Femtobot._sdk_locks` GC race** em
  [femtobot.py](femtobot/femtobot.py).  Lock em
  `WeakValueDictionary` podia ser GC'd entre
  `_acquire_session_lock` return e `lock.acquire()`.  **Fix:**
  strong reference local `_keep_alive = lock`.
- **(J8, MEDIUM) `_format_messages` KeyError** em
  [agent/memory.py](femtobot/agent/memory.py).
  `message['role']` levantava KeyError em entry sem role.
  **Fix:** `message.get('role', 'unknown')` com fallback
  para `str()` se não for string.
- **(J14, LOW) `Femtobot.run` lock_timeout_s sem validação** em
  [femtobot.py](femtobot/femtobot.py).  NaN/inf passava
  silenciosamente, `asyncio.wait_for(..., nan)` levanta
  `ValueError` indistinguível de timeout real.  **Fix:**
  validação com `math.isfinite() and >= 0` antes do lock
  path.

### Not Fixed (Falsos Positivos ou Fora de Escopo)
- **J2 (path traversal `\`)** — o regex `r"[\\/]+"` já
  divide corretamente. Verificado com casos de teste.
- **J4-J7, J9-J13, J15** — analisados, mas requerem refator
  maiores ou estão cobertos por outras camadas.

### Added
- 1 novo arquivo de test (9 testes de regressão):
  - `tests/test_sixth_pass_fixes.py` (J1, J3, J8, J14) — 9 testes

### Tests
- Suite: **626 passed, 0 failed** (9 testes a mais que v0.1.1).
- Ruff: **All checks passed!**.

### Migration
Compat 100% com v0.1.1.

## [0.1.1] — 2026-07-09

> Lote I: Fifth-pass hardening (5 fixes, 9 tests novos).
> Compat 100% com v0.1.0.

### Fixed
- **(I1, CRITICAL) `OpenAICompatProvider` recebia `spec=None`** em
  [providers/factory.py](femtobot/providers/factory.py).  Toda a
  lógica provider-specific (prompt caching, model prefix stripping,
  thinking style, tool-ID sanitization, env vars) estava
  silenciosamente desabilitada.  **Fix:** factory agora resolve
  o spec via `find_by_name(provider_name)` e passa ao construtor.
  Anotação do parâmetro `spec` mudou de `None` para `ProviderSpec | None`.
- **(I2, HIGH) `_setup_env` nunca era chamado** em
  [providers/openai_compat_provider.py](femtobot/providers/openai_compat_provider.py).
  `spec.env_key` e `spec.env_extras` eram dead code.  **Fix:**
  chamado de `__init__` quando `api_key is not None`.
- **(I3, MEDIUM) `append_transcript_object` noop** em
  [channels/websocket.py](femtobot/channels/websocket.py).  Era
  `pass` e logava warning em cada chamada.  **Fix:** noop com
  docstring explicativa, caller agora loga em debug.
- **(I4, HIGH) `ServerConnection.close()` não awaited** em
  [channels/websocket.py](femtobot/channels/websocket.py).  websockets
  v13+ mudou a API; close ficou async.  **Fix:** `await` com
  `asyncio.wait_for(timeout=1.0)`, gather de todos os closes.
- **(I5, HIGH) `find_legal_message_start` over-clearing** em
  [utils/helpers.py](femtobot/utils/helpers.py).  `declared.clear()`
  apagava IDs legítimos ao encontrar orphan.  **Fix:** apenas
  avançar `start`, preservar `declared`.

### Added
- 2 novos arquivos de test (9 testes de regressão):
  - `tests/test_provider_spec_wiring.py` (I1, I2) — 4 testes
  - `tests/test_find_legal_message_start.py` (I5) — 5 testes

### Tests
- Suite: **617 passed, 0 failed** (9 testes a mais que v0.1.0).
- Ruff: **All checks passed!**.

### Migration
Compat 100% com v0.1.0.

## [0.1.0] — 2026-07-09

> Lote H: Fourth-pass hardening (5 fixes, 13 tests novos).
> Compat 100% com v0.0.9. Bump minor para marcar o primeiro
> release pós-multi-rodada de hardening.

### Fixed
- **(H1, CRITICAL) `self.agents_config` nunca era inicializado** em
  [agent/loop.py](femtobot/agent/loop.py) e [agent/context.py](femtobot/agent/context.py).
  Os métodos `notify_mcp_startup_failures` e
  `include_mcp_context` liam `self.agents_config.defaults.X` mas o
  atributo nunca era setado em `__init__`.  O `try/except Exception`
  silenciosamente engolia `AttributeError`, desabilitando 2 feature
  flags em produção.  Tests passavam porque monkey-patchavam o
  atributo.  **Fix:** `__init__` agora inicializa
  `self.agents_config = AgentsConfig()`; `from_config` substitui
  com `config.agents`; `ContextBuilder` recebe o live flag.
- **(H2, HIGH) `int(os.environ.get(...))` sem try/except** em
  [agent/loop.py](femtobot/agent/loop.py).  `FEMTOBOT_MAX_CONCURRENT_REQUESTS=many`
  crashava o startup com `ValueError`.  **Fix:** try/except com
  fallback ao default (3) e warning logado.
- **(H3, MEDIUM) Variable shadowing em `tools_list`** em
  [cli/commands.py](femtobot/cli/commands.py).  `suffix = ""` no
  loop for sobrescrevia o parâmetro Typer `suffix` (usado para
  localizar o instance folder).  **Fix:** renomeado inner binding
  para `cap_suffix`.
- **(H4, MEDIUM) `except BaseException` shadowing `CancelledError`** em
  [tools/mcp.py](femtobot/agent/tools/mcp.py).  O `except asyncio.CancelledError`
  acima era shadowed por `except BaseException` (superclasse).
  **Fix:** `CancelledError` re-raise após log; `Exception` (não
  `BaseException`) para erros recuperáveis.
- **(H6, HIGH) `asyncio.gather` sem `return_exceptions`** em
  [agent/runner.py](femtobot/agent/runner.py).  Uma tool que
  raise cancelava todas as peers em flight, deixando side-effects
  parciais.  **Fix:** `return_exceptions=True` + sintetizar error
  tuple para cada exception.

### Added
- 3 novos arquivos de test (13 testes de regressão):
  - `tests/test_agents_config_init.py` (H1) — 4 testes
  - `tests/test_env_var_parsing.py` (H2) — 6 testes
  - `tests/test_concurrent_tools_isolation.py` (H6) — 3 testes

### Tests
- Suite: **608 passed, 0 failed** (13 testes a mais que v0.0.9).
- Ruff: **All checks passed!**.

### Migration
Compat 100% com v0.0.9. Bump minor (0.0.9 → 0.1.0) marca a
transição pós-multi-rodada de hardening; nenhuma breaking change.

## [0.0.9] — 2026-07-09

> Lote G: Third-pass hardening (5 fixes, 39 tests novos).
> Compat 100% com v0.0.8.

### Fixed
- **(B1, CRITICAL) `api/server.py` vaza API keys em log** — `scrub_text()` aplicado antes de logar.
- **(B2, CRITICAL) `loop.py` vaza conteúdo de mensagem em log** — `scrub_text()` aplicado.
- **(B3, HIGH) `resolve_allowed_path` bypass sem `allowed_root`** — agora `restrict_to_workspace=True` enforça mesmo sem root explícito.
- **(B4, HIGH) `memory.py` history.jsonl com BOM** — `encoding="utf-8-sig"` em vez de `"utf-8"`.
- **(B5, MEDIUM) `runner.py` event detail com path absoluto** — `scrub_text()` + tratamento de `len(parts) == 1`.
- **(B7, MEDIUM) `filesystem.py` não bloqueava `/proc/self/environ`** — blocklist estendido.
- **(B8, MEDIUM) `md_commands.py` frontmatter regex pegava `---` no corpo** — regex mais restritiva com `(?:\n|$)`.
- **(C3, HIGH) Signal handler chamava `sys.exit(0)` mid-loop** — usa `threading.Event` + `call_soon_threadsafe`.
- **(C4, HIGH) `voice.py:_detect_audio_recorder` bloqueava event loop** — agora `async def` + `asyncio.to_thread`.
- **(C6, MEDIUM) `WebSocketChannel.stop` fechava com EOF** — agora envia WS close frame (code 1001).

### Added
- Novo helper `scrub_text()` em `utils/helpers.py` (regex para OpenAI/GitHub/AWS keys, Authorization headers, generic key=value, PEM blocks).
- 4 novos arquivos de test (39 testes de regressão):
  - `tests/test_scrub_text.py` — 12 testes
  - `tests/test_history_jsonl_bom.py` — 4 testes
  - `tests/test_blocked_proc_paths.py` — 7 testes
  - `tests/test_resolve_allowed_path_restrict.py` — 6 testes
  - `tests/test_voice_detect_async.py` — 4 testes
  - `tests/test_cli_signal_handler.py` — 3 testes
  - `tests/test_websocket_graceful_close.py` — 3 testes

### Tests
- Suite: **595 passed, 0 failed** (39 testes a mais que v0.0.8).
- Ruff: **All checks passed!**.

### Migration
Compat 100% com v0.0.8. Zero breaking changes.

## [0.0.8] — 2026-07-09

> Lote F: Second-pass hardening (7 fixes, 20 tests novos).
> Compat 100% com v0.0.7.

### Fixed
- **(F1) `_stream_text_buffers` leak** em [websocket.py](femtobot/channels/websocket.py) — substituído por `OrderedDict` com cap LRU (1024).
- **(F2) `session_locks` unbounded** em [server.py](femtobot/api/server.py) — `dict` → `weakref.WeakValueDictionary`.
- **(F3) `_drain_pending` docstring errada** em [loop.py](femtobot/agent/loop.py) — docstring reescrita (era "blocks", real é non-blocking).
- **(F4) `except BaseException` em runner** em [runner.py](femtobot/agent/runner.py) — trocado por `Exception`.
- **(F5) `asyncio.create_task` sem ref** em [builtin.py](femtobot/command/builtin.py) — `cmd_restart` e `cmd_dream` agora usam `_schedule_background`.
- **(F6) `assert` para narrowing** em [websocket.py](femtobot/channels/websocket.py) — `assert` substituído por `raise RuntimeError`.
- **(F7) `MessageBus` queue sem maxsize** em [queue.py](femtobot/bus/queue.py) — cap default 1024/4096, env-overridable.

### Added
- 4 novos arquivos de test (20 testes de regressão):
  - `tests/test_stream_text_buffer_cap.py` (F1) — 5 testes
  - `tests/test_api_session_locks_wvd.py` (F2) — 5 testes
  - `tests/test_websocket_stop_event_invariant.py` (F6) — 4 testes
  - `tests/test_message_bus_maxsize.py` (F7) — 6 testes

### Tests
- Suite: **556 passed, 0 failed** (20 testes a mais que v0.0.7).
- Ruff: **All checks passed!**.

## [0.0.7] — 2026-07-09

> Milestone `v0.0.7` — **Lote E: Hardening pós-release**. Revisão
> profunda do projeto (audit + ruff + smoke + race + security + 30
> testes de regressão). Apenas bugfixes e quality-of-life; **zero
> breaking changes**, **zero new features**. Compatível com v0.0.6.

> A seção `Tests` lista os arquivos de regressão; os bugs são
> referenciados como `E1..E7` nos comentários inline para
> localização rápida no `git blame`.

### Fixed
- **(E1, CRITICAL) `WebSocketChannel.gateway` não atribuído** —
  [femtobot/channels/websocket.py](femtobot/channels/websocket.py). O
  parâmetro ``gateway: GatewayServices = None`` era aceito no
  ``__init__`` mas nunca guardado em ``self.gateway``. O método
  ``_maybe_push_active_goal_state`` lia
  ``self.gateway.session_manager`` direto → ``AttributeError``
  garantido em 100% das chamadas quando o caller passava um gateway
  não-None. **Fix:** ``self.gateway = gateway`` no ``__init__``,
  mais guarda ``if self.gateway is None or self.gateway.session_manager is None``.
- **(E2, HIGH) Race em `_session_locks.setdefault`** —
  [femtobot/agent/loop.py](femtobot/agent/loop.py). Duas coroutines
  concorrentes podiam criar ``asyncio.Lock`` **diferentes** para o
  mesmo ``session_key`` via ``dict.setdefault`` (padrão TOCTOU),
  quebrando a serialização por sessão. **Fix:** novo método
  ``AgentLoop._acquire_session_lock()`` com double-check
  pattern + ``self._session_locks_lock`` (mesma técnica do
  ``Femtobot._acquire_session_lock`` já usado em B1).
- **(E3, HIGH) Kill-switch para `shell=True` em skill bodies** —
  [femtobot/cli/md_commands.py](femtobot/cli/md_commands.py). O
  ``_run_bash_inlines`` expandia ``!`rm -rf /``` (input do usuário
  ou skill body adulterada) com ``shell=True`` direto. **Fix:**
  nova env var ``FEMTOBOT_NO_BASH_INLINE=1`` como global kill-switch
  (substitui por placeholder sem chegar ao shell); toda expansão
  passa a gerar audit log com `cmd_length` + prefix do comando.
- **(E4, CRITICAL) `AgentLoop.from_config` retornava sem atribuir
  `instance`** — [femtobot/agent/loop.py](femtobot/agent/loop.py#L393)
  (F821). O snippet original fazia ``return cls(...)`` como
  expressão solta e depois ``instance._config = config`` —
  ``instance`` nunca era definido. O F821 mascarava isso como
  lint; o comando ``/style`` (que lê ``loop._config``) crashava
  em runtime. **Fix:** ``instance = cls(...)`` antes do assign.
- **(E5, HIGH) `atomic_write_text` com `from contextlib import
  suppress` no meio do try** —
  [femtobot/utils/gitstore.py](femtobot/utils/gitstore.py). O
  ``suppress`` era importado localmente dentro do try em
  ``atomic_write_text``, mas usado no bloco ``except`` logo abaixo.
  Resultado: ``UnboundLocalError`` em qualquer write que falhasse
  (deixava o ``.tmp`` órfão no disco). **Fix:** ``suppress``
  movido para o import do topo. Crítico porque todo `dream_cursor`
  / `history.jsonl` write passa por aqui.
- **(E6, MEDIUM) `RenderableType` undefined em `stream.py`** —
  [femtobot/cli/stream.py](femtobot/cli/stream.py#L164) (F821).
  Type annotation sem import. **Fix:** adicionado ao
  ``from rich.console import Console, RenderableType``.
- **(E7, MEDIUM) `Femtobot.run` `_extra_hooks` vazava em timeout**
  — [femtobot/femtobot.py](femtobot/femtobot.py). Quando
  ``lock.acquire()`` lançava ``TimeoutError``, o
  ``self._loop._extra_hooks`` (com o ``SDKCaptureHook``) **não**
  era restaurado e vazava para a próxima ``run()`` no mesmo
  Femtobot. **Fix:** try/finally aninhado garantindo o restore em
  happy path, timeout path e exception path.
- **(E8, MEDIUM) `AgentLoop._config` inexistente sem `from_config`**
  — [femtobot/agent/loop.py](femtobot/agent/loop.py). Quem
  instanciasse ``AgentLoop`` diretamente (sem ``from_config``)
  via ``__init__`` recebia ``self._config`` inexistente e
  slash commands crashavam. **Fix:**
  ``self._config: Any = None`` no ``__init__`` (default).
- **(E9, MEDIUM) `trust_env=False` quebrava HTTPS local com cert
  custom** — [femtobot/providers/openai_compat_provider.py](femtobot/providers/openai_compat_provider.py)
  (refinamento de D3). Aplicar ``trust_env=False`` a todo endpoint
  local desabilitava o ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` do
  env — quebrava setups ``https://127.0.0.1`` com self-signed
  CA. **Fix:** aplicar ``trust_env=False`` apenas quando o scheme
  é ``http://``; HTTPS local mantém ``trust_env=True`` para honrar
  a CA bundle custom.
- **(E10, LOW) `femtobot tools list` crashava em AttributeError**
  — [femtobot/cli/commands.py](femtobot/cli/commands.py). O
  ``except Exception`` mascarava um ``AttributeError`` em tools
  que falhavam no ``create(None)``. **Fix:** estreitado para
  ``(TypeError, ValueError, RuntimeError, AttributeError)``.
- **(E11, LOW) `keybindings._Handler` usava `handler_self` em vez
  de `self`** — [femtobot/cli/keybindings.py](femtobot/cli/keybindings.py)
  (N805). Nested class com rename incorreto; o método interno
  usava o nome ``handler_self``. **Fix:** renormalizado para
  ``self``.

### Added
- **(E) `ProviderConfig.region` (já em v0.0.6, refinado)** + novo
  helper ``_resolve_region`` em [femtobot/providers/bedrock.py](femtobot/providers/bedrock.py).

### Changed
- **(E) Ruff 100% limpo** — `uv run ruff check .` reporta
  `All checks passed!` (zero erros). 131 erros auto-fixados
  (imports não ordenados, blank lines com whitespace, trailing
  newlines, f-strings sem placeholders, etc.).
- **(E) `AgentLoop._acquire_session_lock` é async** — espelha
  o contrato de ``Femtobot._acquire_session_lock`` (B1).
- **(E) `E402` adicionado ao `pyproject.toml [tool.ruff.lint].ignore`**
  — re-exports de compat (ex.: ``DEFAULT_TURN_BOX``) ficam
  naturalmente abaixo das outras constantes sem warning.

### Tests
- Adicionados **30 testes de regressão** novos (não classificados
  sob os markers A/B/C/D — são puramente hardening):
  - `tests/test_websocket_channel_critical.py` (E1) — 5 testes
  - `tests/test_session_lock_race_fix.py` (E2) — 5 testes
  - `tests/test_md_commands_kill_switch.py` (E3) — 3 testes
  - `tests/test_femtobot_facade.py` (E1, E8, E11) — 8 testes
  - `tests/test_gitstore_atomic_write.py` (E5, E11) — 9 testes
- Suite total: **536 tests passing, 0 failed, 0 errors**.
- Ruff: **All checks passed**.

### Migration notes
Nenhuma. Compat 100% com v0.0.6 — todos os fixes são bugs
verdadeiros (variáveis undefined, race conditions, AttributeError
crash). Operadores que ativaram o kill-switch de E3 podem
desativar (default off).

## [0.0.6] — 2026-07-09

> Milestone `v0.0.6` — **Lote D: Provedores e cold-start** (see
> [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) §5). 2 itens (D1, D3)
> implementados; D2 (extraQuery) já coberto pelo Lote A; D4 (gateway
> A2A) deferido até o Stage 2.

### Added
- (D1) **AWS Bedrock Converse provider** (ref: nanobot v0.2.0
  #3574).  Novo ``femtobot.providers.bedrock.BedrockProvider`` que
  usa a API padronizada Bedrock Converse.  ``boto3`` é importado
  **lazy** dentro de ``_get_client`` (não no topo do módulo), então
  uma instalação vanilla do femtobot não exige ``boto3``.  Suporta
  dois caminhos de auth:
  1. SigV4 padrão via ``AWS_ACCESS_KEY_ID`` /
     ``AWS_SECRET_ACCESS_KEY`` (e cadeia boto3 padrão — IAM role,
     SSO, etc.).
  2. Atalho de session token via ``BEDROCK_API_KEY``, mapeado
     automaticamente para ``AWS_SESSION_TOKEN`` quando a cadeia
     SigV4 não está presente.
- (D1) **`ProviderConfig.region` + `ProvidersConfig.bedrock`** (D1).
  Campo ``region`` no ``ProviderConfig`` permite sobrescrever
  ``BEDROCK_REGION`` / ``AWS_REGION`` / o default ``us-east-1``.
- (D1) **`pyproject.toml` extra `bedrock = ["boto3>=1.34.0"]`** —
  instala o SDK AWS sob demanda (`pip install femtobot[bedrock]`).

### Fixed
- (D3) **Local endpoints bypass corporate proxy** (ref: nanobot
  v0.2.2 #4367).  ``OpenAICompatProvider._build_client`` agora
  cria o ``httpx.AsyncClient`` com ``trust_env=False`` quando
  ``self._is_local`` é True.  ``HTTPS_PROXY`` / ``HTTP_PROXY`` no
  ambiente são ignorados para Ollama/vLLM/etc., resolvendo o
  cenário "Ollama atrás de corp proxy".  Cloud endpoints mantêm
  o default ``trust_env=True``.

### Tests
- Adicionados 14 testes de regressão marcados ``@pytest.mark.providers``:
  - `tests/test_bedrock_d1.py` (D1) — 10 testes
  - `tests/test_proxy_bypass_d3.py` (D3) — 4 testes

## [0.0.5] — 2026-07-09

> Milestone `v0.0.5` — **Lote C: Refator de arquitetura** (see
> [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) §4). 5 itens propagados do
> nanobot v0.2.x. Foco em clareza de API para embedders (C1), plugin
> architecture (C2), extension registry (C3), capability mentions
> unificados (C4), e wizard de onboard (C5).

### Added
- (C2) **`Tool.capabilities` + `Tool.get_capabilities()`**
  (ref: nanobot v0.2.0 #3729).  Base class ``Tool`` agora expõe
  ``capabilities: list[str]`` (class-level) e o método
  ``get_capabilities()`` que adiciona ``read-only`` automaticamente
  quando ``read_only=True``.  ``ToolRegistry.by_capability(name)``
  filtra; ``ToolRegistry.capabilities()`` retorna um mapa
  capability→tools.
- (C2) **`femtobot tools list [--capability <name>]`** CLI
  (sub-app ``tools``).  Lista tools do registry; com
  ``--capability`` filtra; com ``--show-capabilities`` mostra
  tags ao lado do nome.
- (C3) **Local extension registry (`extensions.json`)** (ref:
  nanobot v0.2.1 #4046).  Novo módulo
  ``femtobot/agent/tools/extensions.py`` com
  :class:`ExtensionConfig` e :func:`load_extensions` que lê
  ``extensions.json`` do instance dir.  Suporta ``kind: cli`` e
  ``kind: http``; falha soft em JSON inválido.
- (C4) **`MCPServerConfig.capability_mentions`** (ref: nanobot
  v0.2.1 #3963).  Campo novo no schema.  Tags declaradas aqui
  fluem para ``MCPToolWrapper.get_capabilities()`` (junto com
  ``network``), expondo-as no system prompt.
- (C5) **`femtobot onboard --wizard`** (ref: nanobot v0.2.1
  #3890).  Wizard interativo (TTY-only) para escolher provider /
  model / API key.  Mutate o ``Config`` in-place e seta o novo
  preset como default.  TTY-only; CI/scripts seguem com o
  config default.

### Changed
- (C1) **`AgentLoop.from_config` documented as canonical entry
  point** (ref: nanobot v0.2.0 #3708).  Docstring expandida com
  exemplo de uso direto (sem facade) e link para ``Femtobot`` no
  :mod:`femtobot.femtobot`.  ``Femtobot.from_config`` já chama
  ``AgentLoop.from_config`` (verificado por teste).
- (C1) **`providers/registry.py::list_provider_specs()`** added
  (small additive change) so the wizard can iterate registered
  providers.

### Tests
- Adicionados 37 testes de regressão marcados ``@pytest.mark.architecture``:
  - `tests/test_agent_loop_factory_c1.py` (C1) — 4 testes
  - `tests/test_capabilities_c2.py` (C2) — 7 testes
  - `tests/test_extensions_c3.py` (C3) — 10 testes
  - `tests/test_capability_mentions_c4.py` (C4) — 7 testes
  - `tests/test_onboard_wizard_c5.py` (C5) — 9 testes

## [0.0.4] — 2026-07-09

> Milestone `v0.0.4` — **Lote B: Durabilidade e concorrência** (see
> [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) §3). 6 itens propagados do
> nanobot v0.2.x. Foco em locks de sessão, usage real, continuação
> de goal, e integridade do apply_patch.

### Added
- (B1) **Per-session lock in `Femtobot.run()`** (ref: nanobot v0.2.1
  #4104).  ``Femtobot`` agora serializa chamadas concorrentes na
  mesma ``session_key`` via ``WeakValueDictionary[str, asyncio.Lock]``.
  Timeout de 5s para aquisição; ``asyncio.TimeoutError`` é levantado
  com mensagem clara.  ``lock_timeout_s=0`` desabilita o lock
  (escape hatch).  Compatível com a lock do servidor API que já
  existia.
- (B3) **Forward real LLM usage in `/v1/chat/completions`** (ref:
  nanobot v0.2.2 #4310).  ``Femtobot.run().usage`` carrega o dict
  de usage do provider; ``_chat_completion_response`` no
  ``api/server.py`` normaliza o dict (prompt/completion/total) e
  popula ``response.usage``.  Compat: quando o provider não
  retorna usage, o placeholder de zeros é mantido.
- (B6) **`/goal complete` slash command** (ref: nanobot v0.2.0
  #3788).  Novo handler ``cmd_goal_complete`` em
  ``command/builtin.py`` que muta ``session.metadata[GOAL_STATE_KEY]``
  para ``status="completed"`` + ``completed_at`` + ``recap``
  opcional.  O runner wall timeout volta ao default
  (``FEMTOBOT_LLM_TIMEOUT_S``).

### Fixed
- (B2) **Don't desiste while a goal is active** (ref: nanobot v0.2.1
  #3999, #4127).  Novo campo ``AgentRunSpec.goal_iteration_extra_budget``
  (default 50).  Quando ``max_iterations`` é esgotado e
  ``goal_active_predicate()`` retorna True, o loop ganha
  ``extra_budget`` iterações antes de finalizar.  Quando o extra
  budget também esgota, finaliza normalmente — sem loop infinito.

### Verified
- (B4) **`apply_patch` line-separated additions** (ref: nanobot
  v0.2.2 #4266).  Audit + 5 testes de regressão confirmam que
  ``action: "add"`` preserva o ``\n`` final e mantém múltiplas
  linhas distintas (sem collapse).
- (B5) **Archived summary lives in the system prompt** (ref: nanobot
  v0.2.0 #3711).  Audit + 3 testes confirmam que
  ``build_system_prompt(session_summary=...)`` injeta o summary
  como bloco ``[Archived Context Summary]`` no system prompt (não
  como mensagem), melhorando o cache hit em providers com KV cache.

### Tests
- Adicionados 27 testes de regressão marcados ``@pytest.mark.durability``:
  - `tests/test_session_lock_b1.py` (B1) — 5 testes
  - `tests/test_usage_b3.py` (B3) — 5 testes
  - `tests/test_apply_patch_b4.py` (B4) — 5 testes
  - `tests/test_context_b5_system_summary.py` (B5) — 3 testes
  - `tests/test_goal_complete_b6.py` (B6) — 5 testes
  - `tests/test_runner_b2_goal_budget.py` (B2) — 4 testes

## [0.0.3] — 2026-07-09

> Milestone `v0.0.3` — **Lote A: Estabilidade e segurança** (see
> [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) §2). 14 itens propagados do
> nanobot v0.2.x.  Tudo gated por env var ou opt-in; backward-compat
> preservada com v0.0.2.

### Security
- (A2) **Reject unsafe MCP HTTP URLs before TCP probe**
  (ref: nanobot v0.2.2 #4123).  ``_preflight_check_mcp_url`` chama
  ``validate_url_target`` antes do ``_probe_http_url``.  ``http://169.254.169.254/``
  e afins são rejeitados no startup do MCP sem tentar conectar.
- (A3) **Validate redirect targets in web_fetch**
  (ref: nanobot v0.2.1 #3928).  Já estava implementado via
  ``_get_with_safe_redirects`` / ``_stream_with_safe_redirects``;
  audit confirmou cobertura de cada hop de redirect.
- (A4) **Block IPv6-mapped IPv4 addresses in SSRF guard**
  (ref: nanobot v0.2.1 #4086).  ``::ffff:0:0/96`` adicionado a
  ``_BLOCKED_NETWORKS`` como defense-in-depth sobre o
  ``_normalize_addr`` já existente.

### Fixed
- (A1) **Optional fail-fast on invalid config**
  (gated by ``FEMTOBOT_STRICT_CONFIG_LOAD``, default ``false``).  Em
  strict mode, ``JSONDecodeError`` / ``pydantic.ValidationError`` em
  campo obrigatório aborta com ``SystemExit(2)`` e mensagem clara.
  Em lenient mode (default), o loader continua caindo no default mas
  escala o log para ``error`` em JSON inválido / required-field
  inválido.  Novo subcomando CLI ``femtobot config validate [--strict]``.
- (A6) **dream_cursor advances only after commit succeeds**
  (ref: nanobot v0.2.0 #3631).  Novo
  ``MemoryStore.advance_dream_cursor_after_commit`` faz o
  ``git.auto_commit`` primeiro e só avança o cursor se a SHA voltar
  não-vazia; crash mid-Dream agora reprocessa os entries.
- (A7) **Atomic write for ``.dream_cursor`` + corruption detection**
  (ref: nanobot v0.2.0 #3606).  ``set_last_dream_cursor`` usa
  ``atomic_write_text`` (tempfile + ``os.replace`` + fsync do dir).
  Cursor corrompido na leitura é detectado e renomeado para
  ``*.corrupt-<ts>`` na próxima carga.
- (A8) **Soft workspace boundary with retry-throttle**
  (ref: nanobot v0.2.0 #3614).  Opt-in via
  ``FEMTOBOT_SOFT_WORKSPACE_BOUNDARY=true``.  Primeiros 3 strikes por
  sessão viram warning string retornada à LLM; após isso vira hard-fail
  novamente para não entrar em loop infinito.  Limite configurável via
  ``FEMTOBOT_SOFT_WORKSPACE_BOUNDARY_STRIKES``.
- (A9) **AutoCompact/Consolidator race fix**
  (ref: nanobot v0.2.1 #3881).  Já existia via
  ``Consolidator._locks`` (``WeakValueDictionary[session_key,
  asyncio.Lock]``); audit confirmou que ambos os caminhos pegam o
  mesmo lock por ``session_key``.
- (A10) **Ignore malformed history entries + monotonic cursor**
  (ref: nanobot v0.2.2 #4315, #4256).  Linhas JSONL malformadas
  geram warning one-shot com índice; cursor que regride é recusado com
  ``ValueError`` + log ``error``.

### Added
- (A5) **Log primary error before fallback** (ref: nanobot v0.2.0
  #4385).  ``FallbackProvider`` agora loga kind/code/status/content do
  erro primário antes de tentar fallback, e expõe
  ``on_primary_error`` callback para observability.
- (A11) **extraQuery config for OpenAI-compat providers**
  (ref: nanobot v0.2.2 #4217).  Novo campo ``extraQuery`` em
  ``ProviderConfig`` que vira query string da ``apiBase`` (azure-style
  ``?api-version=``, etc.).  Doc em
  [docs/configuration.md](./docs/configuration.md).
- (A12) **Sanitize Anthropic tool-use IDs**
  (ref: nanobot v0.2.2 #4356).  IDs que não casam
  ``^[a-zA-Z0-9_-]{1,64}$`` são sanitizados (substituição de
  caracteres inválidos + fallback hash determinístico).
- (A13) **Image placeholders no longer leak local path**
  (ref: nanobot v0.2.2 #4401).  ``image_placeholder_text`` retorna
  ``[image omitted]`` em vez de ``[image: /abs/path]``; o path não
  vaza mais em transcripts / logs / cloud upstream calls.
- (A14) **Recognize arrearage / 欠费 / payment_required as fallbackable**
  (ref: nanobot v0.2.1 #4048).  Tokens adicionados a
  ``_FALLBACK_ERROR_TOKENS`` no ``FallbackProvider``; o
  ``_ARREARAGE_ERROR_MESSAGE`` já existia no runner e continua
  exibindo mensagem amigável ao usuário.

### Tests
- Adicionados 51 testes de regressão marcados ``@pytest.mark.security``:
  - `tests/test_security_a4_ipv6_mapped.py` (A4)
  - `tests/test_mcp_a2_unsafe_url.py` (A2)
  - `tests/test_workspace_a8_soft_boundary.py` (A8)
  - `tests/test_config_loader_a1.py` (A1)
  - `tests/test_fallback_provider_a5_a14.py` (A5 + A14)
  - `tests/test_memory_a6_a7_a10.py` (A6 + A7 + A10)
  - `tests/test_providers_a11_a12.py` (A11 + A12)
  - `tests/test_helpers_a13.py` (A13)


- Documentation overhaul:
  - [docs/configuration.md](docs/configuration.md) now covers every field of
    `config.json` (60+ knobs across agents, channels, providers, api, gateway,
    tools, model presets).
  - [docs/python-sdk.md](docs/python-sdk.md) shows the in-process
    `Femtobot.from_config()` API alongside the OpenAI-server and CLI paths.
  - [docs/cli-reference.md](docs/cli-reference.md) documents every
    subcommand, every flag, and every slash command.
  - [docs/websocket.md](docs/websocket.md) covers the full schema and warns
    about the `websocketRequiresToken` default trap.
  - [docs/memory.md](docs/memory.md) explains the three-layer memory model,
    the Consolidator → AutoCompact → Dream pipeline, and every config knob.
  - [docs/openai-api.md](docs/openai-api.md) adds streaming, session
    semantics, and the no-auth caveat.
  - [docs/deployment.md](docs/deployment.md) gets a working systemd unit
    with a real `ExecStart` path, a supervisord alternative, a caddy/nginx
    reverse-proxy example, and health-check guidance.
  - [docs/my-tool.md](docs/my-tool.md) documents the `modify` action, the
    BLOCKED/READ_ONLY/`_SENSITIVE_NAMES`/`_DENIED_ATTRS` protection layers.
  - New docs: [architecture.md](docs/architecture.md),
    [tools.md](docs/tools.md), [security.md](docs/security.md),
    [troubleshooting.md](docs/troubleshooting.md), [mcp.md](docs/mcp.md).
  - Root-level [CHANGELOG.md](CHANGELOG.md) and
    [CONTRIBUTING.md](CONTRIBUTING.md).

### Fixed
- `docs/quick-start.md` install commands: `uv tool install femtobot-ai` →
  `uv tool install femtobot`; `git clone HKUDS/femtobot` →
  `git clone bill-kopp-ai-dev/femtobot`.
- `docs/websocket.md` example no longer ships a config that produces 401 on
  every connection (the `websocketRequiresToken: true` + empty token trap).
- `docs/deployment.md` systemd `ExecStart` no longer points at the
  non-existent `/path/to/femtobot` placeholder.
- `docs/python-sdk.md` no longer claims the Python API is "wait for stable
  release" — `Femtobot.from_config()` has been working since v0.0.2.

## [0.0.2] — 2025-11-XX

Initial public alpha.

### Added
- Core CLI commands: `onboard`, `status`, `agent`, `serve`, `gateway`.
- OpenAI-compatible HTTP surface under `femtobot serve`.
- WebSocket channel (`femtobot.channels.websocket`).
- 33 registered LLM providers.
- 13 native tools (filesystem, search, shell, web, self, message).
- MCP client integration with stdio and HTTP transports.
- Three-layer memory model: session messages → `history.jsonl` →
  Git-backed `MEMORY.md`/`USER.md`/`SOUL.md`, with the Consolidator, the
  AutoCompact idle compaction, and the periodic Dream job.
- Multiple-instance support via `--suffix` / `--folder-path` /
  `FEMTOBOT_HOME`.

[Unreleased]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.8...HEAD
[0.1.8]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.9...v0.1.0
[0.0.9]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.8...v0.0.9
[0.0.8]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.7...v0.0.8
[0.0.7]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.6...v0.0.7
[0.0.6]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/bill-kopp-ai-dev/femtobot/releases/tag/v0.0.2