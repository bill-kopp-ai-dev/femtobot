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

## See also

- [quick-start.md](./quick-start.md)
- [configuration.md](./configuration.md)
- [cli-reference.md](./cli-reference.md)
- [websocket.md](./websocket.md)
- [openai-api.md](./openai-api.md)
- [mcp.md](./mcp.md)
- [security.md](./security.md)
- [deployment.md](./deployment.md)