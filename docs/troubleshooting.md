# Troubleshooting

A practical FAQ for the failure modes you're most likely to hit when running
Femtobot. Each entry shows the symptom, the likely cause, and a concrete fix.

---

## Installation

### `uv tool install femtobot-ai` fails with "no such package"

**Cause.** You're following an older revision of the docs (or a third-party
blog post) that referenced the placeholder name `femtobot-ai`.

**Fix.**
```bash
uv tool install femtobot
```

The package name on PyPI is `femtobot`, not `femtobot-ai`. See
[quick-start.md](./quick-start.md).

### `git clone https://github.com/HKUDS/femtobot.git` gives a 404

**Cause.** Same as above — older docs referenced the upstream nanobot repo.

**Fix.**
```bash
git clone https://github.com/bill-kopp-ai-dev/femtobot.git
```

### `femtobot: command not found` after `uv tool install`

**Cause.** `uv tool install` puts binaries in `~/.local/bin` (or `%APPDATA%\uv\bin` on
Windows), which may not be on your `$PATH`.

**Fix.**
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Or run with the full path: `~/.local/bin/femtobot --version`.

### `uv run femtobot` picks up an old installation

**Cause.** You're inside the source checkout but `uv run` resolves the
package from the project first, ignoring your global install. This is usually
what you want during development.

**Fix.** If you want the global install instead, run `femtobot` directly
(`which femtobot` to confirm it's the global one).

---

## Configuration

### `femtobot status` shows different values than what's in `config.json`

**Cause.** Pydantic validation failed at load time and the loader silently
fell back to defaults. A typo in a field name is the usual culprit.

**Fix.**
1. Run `femtobot status --verbose` to see the active path.
2. Check `~/.femtobot/logs/femtobot.log` for `Config validation failed:`
   lines.
3. Compare your JSON's keys against [configuration.md](./configuration.md).
   Most typos are due to wrong nesting or camelCase / snake_case confusion
   (Femtobot accepts both, but each key must be in *one* style consistently).

### Edits to `config.json` are ignored

**Cause.** The config is loaded once at process start. Restart Femtobot
after every edit.

**Fix.**
```bash
# Ctrl+C the running process, then:
femtobot agent
```

### `websocketRequiresToken` rejects every connection with 401

**Cause.** Default value is `true`; default `token` is `""`; default
`token_issue_path` is `""`. With those, the handshake fails every time.

**Fix.** Pick one:

```json
// Disable auth (loopback only)
{ "channels": { "websocket": { "websocketRequiresToken": false } } }

// Or set a static token
{ "channels": { "websocket": { "token": "percival", "websocketRequiresToken": true } } }

// Or set up issued-token flow
{ "channels": { "websocket": {
    "token_issue_path": "/webui/token",
    "token_issue_secret": "percival-issuer-secret",
    "websocketRequiresToken": true
}}}
```

See [websocket.md](./websocket.md).

---

## Provider / API

### "Provider not found" or "Only configured model 'X' is available"

**Cause.** `agents.defaults.provider` doesn't match a populated entry in
`providers`.

**Fix.** Either populate `providers.<name>.apiKey`, or change `provider` to
the one you've actually configured. Run `femtobot status` to see what
Femtobot thinks is active.

### 401 / 403 from the LLM provider

**Cause.** Wrong API key, expired key, or wrong base URL for a regional
gateway.

**Fix.**
1. Confirm the key works directly: `curl -H "Authorization: Bearer $KEY" $BASE_URL/...`.
2. For MiniMax specifically: `apiBase` must be the regional gateway URL
   (e.g. `https://api.minimax.io/v1`), not the Anthropic or Google default.
3. Set `providerRetryMode: "persistent"` if you want retries across the
   session lifetime instead of per-call.

### Rate-limited (429)

**Cause.** Free tier, or aggressive parallel requests.

**Fix.**
- Reduce `agents.defaults.maxConcurrentSubagents`.
- Set `providerRetryMode: "persistent"` (the loop will back off and retry).
- Add a delay between bursts by serializing calls in your orchestrator.

### Context window exceeded mid-turn

**Cause.** Conversation history crossed `agents.defaults.contextWindowTokens`.

**Fix.**
- Set `agents.defaults.sessionTtlMinutes > 0` so `AutoCompact` kicks in on
  idle sessions (see [memory.md](./memory.md)).
- Reduce `agents.defaults.maxMessages`.
- Use the `Consolidator` ratio: a tighter `consolidationRatio` (e.g. `0.3`)
  keeps the live context smaller.
- Long tool results can be reduced with `agents.defaults.maxToolResultChars`.

### Stream cuts off after ~60 s

**Cause.** Reverse proxy has a default timeout shorter than your model's
TTFT (time to first token) for long prompts.

**Fix.** For `nginx`:
```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 300s;
```
For `caddy`: `timeouts { read 5m }`. For AWS ALB: increase the idle timeout
on the target group.

---

## MCP

### MCP server args arrive as `{}` (Pydantic: input_value={})

**Cause.** Some MCP client wrappers (notably the IDE-side wrappers in Trae
and Claude Code) serialize tool arguments as an empty object when the
signature has required fields. This is a client-side bug, not a Femtobot
issue.

**Fix (mitigation in the server signature).** Make `req` optional:

```python
@mcp.tool()
async def agy_run_task(req: AgyRunTaskRequest | None = None) -> dict:
    ...
```

The server then accepts both shapes. See the `agy-mcp-server` and
`claude-code-cli-mcp` repos for the working pattern.

**Fix (mitigation on the Femtobot side).** If you can't change the server,
add the MCP server under `tools.mcpServers` and have Femtobot pre-process
tool calls via a hook. Or use the JSON-RPC bypass pattern documented in
`MCP_USER_GUIDE.md` of those server repos.

### MCP server takes 20+ seconds to start

**Cause.** `uvx --refresh` re-installs dependencies on every invocation.

**Fix.** Drop `--refresh` from the `args` array in `tools.mcpServers.<name>`
and let the cache stay warm. Restart the agent (`Ctrl+C` and re-run) once
after the first successful spawn.

### MCP tools don't appear in the prompt

**Cause.** Either the server crashed on spawn, or `enabledTools` is filtering
everything out.

**Fix.**
1. Run the server manually first: `uvx --from /path/to/server fastmcp run src/.../server.py`
2. Confirm it serves `tools/list` and lists at least one tool.
3. Check `femtobot --verbose` output — the MCP client logs connection state
   on startup.
4. Set `enabledTools: ["*"]` to register everything, then narrow.

---

## WebSocket channel

See [websocket.md](./websocket.md). Common cases:

| Symptom | Likely cause |
|---|---|
| `401 Unauthorized` | `websocketRequiresToken: true` with no token. |
| `Connection refused` | Wrong port, or server didn't bind. Check `femtobot --verbose`. |
| `1006 abnormal closure` | Client dropped before handshake completed. Likely a TLS mismatch if using `wss://`. |
| `4003 forbidden by allowFrom` | Client ID not in `channels.websocket.allowFrom`. |

---

## Memory

### Dream never runs

**Cause.** Either `agents.defaults.dream.enabled` is `false`, or
`dream.intervalH` is so large you haven't hit it yet, or there's no work to
do (`.dream_cursor` caught up).

**Fix.**
- Run `/dream` from the REPL to force a cycle.
- Lower `dream.intervalH` to e.g. `1` for testing.
- Check `workspace/memory/.dream_cursor` — if it equals the number of
  archive entries, there's nothing to consolidate.

### `/dream-restore <sha>` claims the commit is missing

**Cause.** The local `memory/.git/` repo was GC'd or `~/.femtobot` was wiped
since the commit.

**Fix.** No recovery — local Git is intentionally separate from the
workspace Git to keep Dream's blast radius small. Use a periodic
backup of the `.git` directory if you need long-term retention.

### `history.jsonl` grows unbounded

**Cause.** No retention policy on the archive.

**Fix.** Add a system cron that rotates the file periodically, or shrink
`agents.defaults.consolidationRatio` so each consolidation cycle absorbs more
entries into the long-term files (and produces fewer archive entries).

---

## Deployment

### systemd: `ExecStart` fails with "no such file"

**Cause.** The `ExecStart` path `/path/to/femtobot` was a placeholder.

**Fix.** Use one of:

```ini
# After `uv tool install femtobot`
ExecStart=%h/.local/bin/femtobot serve --host 127.0.0.1 --port 8900

# From a source checkout
ExecStart=/usr/bin/env -S uv run --project /opt/femtobot femtobot serve --host 127.0.0.1 --port 8900
```

See [deployment.md](./deployment.md).

### Docker: `connection refused` on `127.0.0.1:8900`

**Cause.** Inside a container, `127.0.0.1` is the container's own loopback.
The host can't reach it.

**Fix.** Run with `--host 0.0.0.0` and `-p 8900:8900`. See
[deployment.md](./deployment.md#docker).

### Logs disappear after restart

**Cause.** No persistent log destination; loguru writes to stderr by
default.

**Fix.** Set `LOGURU_FILE` env var in the systemd unit / supervisord config:

```ini
Environment=LOGURU_FILE=/home/me/.femtobot/logs/femtobot.log
```

---

## Performance

### First response is slow (10–30 s)

**Cause.** Cold provider connection, large context assembly, or first MCP
server spawn.

**Fix.**
- Pin your provider's TLS session (most clients do this transparently).
- Reduce initial context by setting `maxMessages` lower.
- Drop `--refresh` from MCP `args`.
- Consider a warm-up call in your orchestrator that you discard.

### Provider is slow on every request

**Cause.** Either your model is overloaded, or you're hitting a regional
gateway from far away.

**Fix.** Add `fallbackModels` to your config so the loop has somewhere to go
when the primary model times out.

---

## Diagnostic commands

| What you want to know | Run |
|---|---|
| Active config values | `femtobot status` |
| Verbose logs | `femtobot --verbose agent` |
| Validate a config without running | `uv run python -c "from femtobot.config.loader import load_config; load_config('/path/to/config.json'); print('OK')"` |
| Show registered tools | Inside the agent: `self(action="check", key="tools")` |
| Show memory state | Inside the agent: `/status`, `/history` |
| Force Dream | `/dream` |
| Inspect a specific provider | `self(action="check", key="providers.minimax")` |

---

## Reporting a bug

If none of the above matches your issue:

1. Run `femtobot --verbose` and capture the failing command's output.
2. Note the femtobot version: `femtobot --version`.
3. Include the relevant section of `config.json` (redact secrets).
4. Open an issue at <https://github.com/bill-kopp-ai-dev/femtobot/issues>.

---

## Issues fixed in 0.1.0-ui.1 (2026-07-18)

The following behaviours were reported during end-to-end REPL/serve
smoke-testing with the local `MiniMax-M3` provider and the
`percival-osm` MCP server. They were all fixed in `0.1.0-ui.1` —
upgrade to that version (or later) if you hit any of them.

### `/goal <task>` returns "Unknown command"

**Fixed in.** `0.1.0-ui.1` (audit 2026-07-18 v4).

**Symptom.** Typing `/goal Crie um arquivo` in the REPL or via
`femtobot agent -m "/goal ..."` produced the message
"Unknown command: /goal" instead of executing the long-task.

**Cause.** `/goal` is a context-rewriting shortcut — its handler
mutates the inbound message and returns `None`, so the rest of the
state machine processes the turn as a normal model call. The
unknown-command fallback was triggered by the `None` return value
instead of recognising the match.

**Fix.** `AgentLoop._state_command` now consults the router's
exact+prefix+priority tables to distinguish a matched shortcut that
rewrote `ctx.msg` from an actually-unknown command.

### `/btw <question>` returns "Could not process the question"

**Fixed in.** `0.1.0-ui.1` (audit 2026-07-18 v5).

**Symptom.** The `/btw` reply was a generic "Could not process the
question. Is the model connected?" notice even though the model was
connected and answering regular turns just fine.

**Cause.** `femtobot.cli.btw.run_btw` called a non-existent
`provider.generate` method. Every registered provider exposes
`chat_with_retry` (and sometimes `chat`), so the `getattr` lookup
silently failed.

**Fix.** Re-routed through `provider.chat_with_retry` (with `chat` as
fallback), extracts text via `response.content`, surfaces the
exception type + message on the error path.

### `/mcp tools <server-with-hyphen>` shows no tools

**Fixed in.** `0.1.0-ui.1` (audit 2026-07-18 v3).

**Symptom.** `/mcp status` listed 33 tools from `percival-osm`, but
`/mcp tools percival-osm` reported "No tools registered from
'percival-osm'". Same problem for any MCP server whose name contains
a hyphen.

**Cause.** The `/mcp tools <server>` prefix lookup replaced `-` with
`_`, but the tool registry preserves hyphens, so the prefix never
matched.

**Fix.** `/mcp tools` now matches both the verbatim server name and
the underscore-flattened form, and surfaces the configured server
list in the empty reply so the user can self-correct.

### `/restart` (and other priority commands) trigger "Unknown command" via `-m`

**Fixed in.** `0.1.0-ui.1` (audit 2026-07-18 v5).

**Symptom.** `femtobot agent -m /restart` printed "Unknown command:
/restart" instead of restarting the process. The interactive `femtobot
agent` REPL worked correctly.

**Cause.** The offline `process_direct` path used by `-m` only runs
through `dispatch()` (exact+prefix). Priority commands like `/restart`
and `/stop` live in the priority tier and are normally dispatched
upstream by the interactive `run()` loop.

**Fix.** `_state_command` now falls through to `dispatch_priority`
when `dispatch` returns `None`, and the unknown-command classifier
counts priority matches as "known".

### Slash commands the router didn't recognise fell through to the LLM

**Fixed in.** `0.1.0-ui.1` (audit 2026-07-18 v4).

**Symptom.** Typing `/foo`, `/tools`, `/asdf` etc. caused the LLM to
invent an answer ("here are the tools I have…") instead of telling
the user the command didn't exist.

**Cause.** `result is None` from `dispatch()` was treated as "send to
the LLM", which the model handled by hallucinating plausible
responses.

**Fix.** When the input starts with `/` and the router did not match,
a new helper `AgentLoop._reply_unknown_command` now returns a clear
"Unknown command" reply listing the first 20 registered slash
commands, plus a hint to use `/help` for the full palette.

### `femtobot status --folder-path /tmp/bogus` is silently ignored

**Fixed in.** `0.1.0-ui.1` (audit 2026-07-18 v6).

**Symptom.** Passing an explicitly-bad path to `--folder-path`
returned a status block anyway, showing the *active* instance instead
of complaining.

**Cause.** `config.loader.discover_instance_dir` walks
`[start, start.parent, cwd/.femtobot]`, so an explicitly-bad path
was treated as "no instance, look harder".

**Fix.** `status` now validates `--folder-path` up-front and exits 2
with a clear error when the path does not exist or contains no
`.femtobot` inside.

### `femtobot tools list` shows only 5 of 17 tools

**Fixed in.** `0.1.0-ui.1` (audit 2026-07-18 v6).

**Symptom.** `femtobot tools list` showed only `apply_patch`,
`edit_file`, `read_file`, `write_file`, `find_files` (or similar) and
`femtobot tools list --capability read-only` showed nothing.

**Cause.** `tools_list` called `tool_cls.create(None)` and silently
swallowed `TypeError` for every tool that needs a `ToolContext`
(`bus`, `sessions`, `provider_snapshot_loader`, …).

**Fix.** `tools_list` now builds a real `ToolContext` (with
`MessageBus`, `workspace`, the loaded `Config.tools`) and passes it
to `tool_cls.create`. The list now shows all 17 builtin tools and
`--capability read-only` returns 7.

---

## Issues fixed in 0.1.0-ui.2 (2026-07-19)

The following visual / structural bugs were reported during an
interactive `femtobot agent --ui compat` session against the
`percival-osm` MCP server (recorded in `longlogs.txt`,
2026-07-19 09:29). They were all fixed in `0.1.0-ui.2` — upgrade
to that version (or later) if you hit any of them.

### MCP server logs appear interleaved with the user input

**Fixed in.** `0.1.0-ui.2` (issue #1, B2).

**Symptom.** While typing in the REPL, lines like
`INFO mcp.server.lowlevel.server: Processing request of type
CallToolRequest` appeared on the same screen as the user's input,
making it impossible to read either stream. Also visible as
literal escape codes (`[?25l`, `[2K`) leaking into the agent's
response.

**Cause.** `mcp.client.stdio.stdio_client` defaults `errlog` to
`sys.stderr`, so every stdio-launched MCP subprocess (e.g.
`percival-osm`) inherited the femtobot's stderr. When the user
runs the CLI with `2>&1` (e.g. inside `tmux`, `script`, or a
captured session) the two streams become indistinguishable.

**Fix.** New helper `_resolve_mcp_errlog(server_name)` in
`femtobot.agent.tools.mcp` opens an append-mode, line-buffered
log file at `<instance_dir>/logs/mcp-<server>.log` (via
`femtobot.config.paths.get_logs_dir()`) and passes it as
`errlog=` to `stdio_client`. The handle is registered with
the server's `AsyncExitStack` so it is closed on disconnect.
Falls back to `subprocess.DEVNULL` if the log dir cannot be
created — never to `sys.stderr`.

**Where to find the logs.**
```bash
tail -f "$(femtobot config get --instance-dir)/logs/mcp-<server>.log"
```

### `[ 👤 You ]` header appears on top of leftover spinner frames

**Fixed in.** `0.1.0-ui.2` (issue #1, B1 / B6 / B7).

**Symptom.** The user-turn header and the first character typed by
the user were rendered on top of leftover `console.status` spinner
frames from the previous turn (the lines started with
`?[2K?[32m▰▰▰▰▱▱▱?[0m ?[2mFemtobot is cogitating…?[0m`).
Visible in any turn where the previous turn's renderer did not
shut down cleanly — e.g. mid-tool-call cancellation, runner
exception, or an interrupted `on_end`.

**Cause.** `_read_interactive_input_async` was calling
`renderer.print_input_gap()` / `renderer.print_user_box()` /
`renderer.print_input_bar()` without first force-stopping the
leftover spinner/Live from the previous turn. The legacy
`stop_for_input()` was called further up the loop, but the
timing window between REPL iterations was enough for stale
frames to survive.

**Fix.** Call `renderer.stop_for_input()` immediately before
the input-gap / user-box / input-bar sequence. This is a strict
no-op when the renderer is already idle.

### Startup MCP warning races the first user keystroke

**Fixed in.** `0.1.0-ui.2` (issue #1, B8).

**Symptom.** The first reply to a user turn contained text like
`⚠ MCP servers referenced but not configured: ['percival-osm']`
*inside* the user prompt area, because the REPL had already
blocked on `prompt_async` before `_connect_mcp` finished
publishing its `OutboundMessage`.

**Cause.** `agent_loop.run()` and the `_consume_outbound` task
were started in parallel, and the `_consume_outbound` task
allowed non-streamed background messages to be rendered only
inside the REPL loop — so any message published before the
first iteration was effectively buffered indefinitely.

**Fix.** `run_interactive` now drains up to 8 `cli:startup`
messages from the bus in a tight 0.15s-per-message loop
*before* entering the REPL. Non-startup messages are passed
through to the normal consumer.

---

## Issues fixed in 0.1.0-ui.3 (2026-07-19)

A follow-up interactive `femtobot agent --ui compat` session against
`percival-osm` (recorded in `longlogs.txt`, 2026-07-19, lines 74-102)
surfaced a new class of bug — a renderer-stable race that prints body
content from the previous turn under the next turn's `[ 👤 You ]`
prompt. Two complementary fixes shipped together in `0.1.0-ui.3`
(issue #2): PR #1 (per-turn `turn_id` tokens) and PR #2 (per-turn
`StreamRenderer` rebuild, parity layer kept). Upgrade to `0.1.0-ui.3`
or later if you hit either of these.

### Body content from the previous turn prints under the next `[ 👤 You ]` prompt

**Fixed in.** `0.1.0-ui.3` (issue #2, PR #1 + PR #2).

**Symptom.** In a `ui_parity=compat` session, the second turn onwards
shows the assistant's response being printed *underneath* the
previously-rendered `You:` prompt. The user types their next input
but the previous response continues to render around it, leaving
the screen with text from two consecutive turns interleaved. The
`nanobot` project does not exhibit this bug because it instantiates
a fresh `StreamRenderer` on every turn.

**Cause.** Two architectural decisions in `femtobot/cli/commands.py`:
- The renderer is constructed **once** before the REPL loop so the
  parity `HeaderBar` + `Welcome card` only render once.
- The `StreamRenderer` instance is then *reused* across turns,
  keeping the same `_buf`, `_live`, `_ENDED`, and `_pending_streamed_body`
  state alive between iterations. The same turn's body can be
  rendered twice (once via stream deltas and once via the
  `_print_agent_response` fallback path) when the trailing
  `_streamed=True, _stream_end_pending=True` `OutboundMessage`
  arrives at the bus out-of-order with `_stream_end`.

**Fix (PR #1 — turn-token).** Each user turn mints a fresh UUID
`metadata["_turn_id"]`. The REPL's `_consume_outbound` task drops
any `OutboundMessage` whose `_turn_id` no longer matches the
active turn, so a late-arriving body from the previous turn is
silently discarded instead of leaking under the next prompt.
Background notifications (`cli:startup`, `_progress`,
`_retry_wait`, `_runtime_control`) carry no `_turn_id` and
continue to flow through unchanged.

**Fix (PR #2 — per-turn core rebuild).** `ParityStreamRenderer`
exposes `replace_core(new_core)`, called by the REPL at the start
of every turn. The compat surface (HeaderBar, Welcome card,
input-bar markup, theme) stays stable across turns; only the
underlying `StreamRenderer` (the layer that owns `_buf`, `_live`,
`_ENDED`) is swapped for a fresh instance. This mirrors the
`nanobot` reference and removes the entire class of cross-turn
state leakage by construction.

**How to verify the fix is in your build.**
```bash
python -c "import femtobot.cli.commands as c; import inspect; \
src = inspect.getsource(c); print('PR #1 ok' if 'uuid.uuid4' in src else 'PR #1 missing'); \
print('PR #2 ok' if 'replace_core' in src else 'PR #2 missing')"
```

---

## See also

- [quick-start.md](./quick-start.md)
- [configuration.md](./configuration.md)
- [cli-reference.md](./cli-reference.md)
- [websocket.md](./websocket.md)
- [openai-api.md](./openai-api.md)
- [mcp.md](./mcp.md)
- [security.md](./security.md)
- [deployment.md](./deployment.md)