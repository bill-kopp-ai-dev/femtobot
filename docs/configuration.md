# Configuration

Config file: `.femtobot/config.json` (relative to the instance directory).
The default instance directory is located at `~/.femtobot/` unless overridden via
the `FEMTOBOT_HOME` environment variable or the `--suffix` / `--folder-path`
CLI arguments. See [multiple-instances.md](./multiple-instances.md).

The full Pydantic schema lives in [`femtobot/config/schema.py`](../femtobot/config/schema.py).
This page documents every field, its default, and what it controls.

---

## Environment Variables

| Variable | Effect |
|---|---|
| `FEMTOBOT_HOME` | Base path where femtobot looks for instance directories. Setting `FEMTOBOT_HOME=/opt/femtobot` causes the default config to live at `/opt/femtobot/.femtobot/config.json`. |
| `FEMTOBOT_*` | Any `config.json` value can be overridden by an env var matching `FEMTOBOT_<UPPER_SNAKE_CASE_PATH>`. For example, `FEMTOBOT_AGENTS__DEFAULTS__PROVIDER=openrouter` overrides `agents.defaults.provider`. Reserved keys (`_`, `-`) are replaced with `_`. |

`config.json` also supports inline env-var references of the form `"${VAR}"` —
see [Environment variable interpolation](#environment-variable-interpolation).

---

## Top-level layout

```json
{
  "agents":      { ... },
  "channels":    { ... },
  "providers":   { ... },
  "api":         { ... },
  "gateway":     { ... },
  "tools":       { ... },
  "modelPresets": {}
}
```

---

## `agents.defaults`

Configures the core agent behavior — provider, model, generation limits,
dream consolidation, and so on.

| Field | Type | Default | Description |
|---|---|---|---|
| `workspace` | str | `"~/.femtobot/workspace"` | Agent workspace directory. Relative paths resolve against the instance directory. |
| `modelPreset` | str \| null | `null` | Name of a preset under [`modelPresets`](#modelpresets). If set, overrides `model`/`provider`/etc. The name `"default"` is reserved and always resolves to the implicit defaults block. |
| `model` | str | `"anthropic/claude-opus-4-5"` | Model identifier passed to the provider. |
| `provider` | str | `"auto"` | One of the registered provider names, or `"auto"` for prefix-based detection. |
| `maxTokens` | int | `8192` | Max tokens the model may emit per turn. |
| `contextWindowTokens` | int | `65536` | Total context window the agent budgets against. |
| `contextBlockLimit` | int \| null | `null` | Optional hard cap on the number of context blocks. |
| `temperature` | float | `0.1` | Sampling temperature. |
| `fallbackModels` | list | `[]` | Ordered fallback chain. Each entry is either a string preset name or an inline `InlineFallbackConfig` (`{model, provider, maxTokens?, contextWindowTokens?, temperature?, reasoningEffort?}`). |
| `maxToolIterations` | int | `200` | Per-turn tool-call budget. After this, the loop finalizes the response. |
| `maxConcurrentSubagents` | int (≥1) | `1` | Concurrency cap for sub-agent fan-out. |
| `maxToolResultChars` | int | `16000` | Per-tool-result size cap before truncation in the prompt. |
| `providerRetryMode` | `"standard"` \| `"persistent"` | `"standard"` | Retry strategy. `"persistent"` keeps retrying across the session's lifetime. |
| `toolHintMaxLength` | int (20–500) | `40` | Truncation length for tool-call hints in the CLI. |
| `reasoningEffort` | str \| null | `null` | One of `low`, `medium`, `high`, `adaptive`, `none` — only honored by providers that support extended thinking. |
| `timezone` | str | `"UTC"` | IANA timezone used for date rendering and cron interpretation (e.g. `"America/Sao_Paulo"`). |
| `botName` | str | `"Femtobot"` | Display name shown in CLI prompts (`"Femtobot is thinking..."`). |
| `botIcon` | str | `"🐈"` | Short icon or emoji rendered next to the bot name. Empty string suppresses it. |
| `unifiedSession` | bool | `false` | If `true`, all channels share a single session per instance (multi-device single-user mode). |
| `disabledSkills` | list[str] | `[]` | Skill names to exclude from loading (e.g. `["summarize"]`). |
| `sessionTtlMinutes` | int (≥0) | `0` | If `>0`, idle sessions past this threshold are compacted by `AutoCompact` (see [memory.md](./memory.md)). `0` disables. |
| `maxMessages` | int (≥0) | `120` | Maximum number of messages replayed from session history into the prompt. |
| `consolidationRatio` | float (0.1–0.95) | `0.5` | Target fraction of context budget retained after compaction (e.g. `0.5` → keep ~50%). |
| `dream` | object | see below | Periodic long-term memory consolidation job (see [memory.md](./memory.md)). |

### `agents.defaults.dream`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Register the periodic Dream consolidation job on startup. |
| `intervalH` | int (≥1) | `2` | Hours between Dream runs. |
| `cron` | str \| null | `null` | Legacy cron override. Excluded from JSON serialization. |
| `modelOverride` | str \| null | `null` | Override the model for Dream sessions (placeholder). |
| `maxBatchSize` | int (≥1) | `20` | **Deprecated.** No longer used. |
| `maxIterations` | int (≥1) | `15` | **Deprecated.** No longer used. |
| `annotateLineAges` | bool | `true` | **Deprecated.** No longer used. |

---

## `channels`

The `channels` block holds two kinds of fields: top-level UX flags that govern
how all channels render output, and one (or, in the future, more) sub-channel
config blocks. Currently the **only** supported sub-channel is `websocket`.

### Top-level UX flags

| Field | Type | Default | Description |
|---|---|---|---|
| `sendProgress` | bool | `true` | Stream agent progress text to the channel. |
| `sendToolHints` | bool | `false` | Stream tool-call hints (e.g. `$ cd … && npm test`). |
| `showReasoning` | bool | `true` | Surface model reasoning when the channel implements it. |
| `extractDocumentText` | bool | `true` | Extract text from document attachments before sending them to the model. |
| `sendMaxRetries` | int (0–10) | `3` | Max delivery attempts (initial send included). |
| `transcriptionProvider` | str | `"groq"` | Voice transcription backend: `"groq"` or `"openai"`. |
| `transcriptionLanguage` | str \| null | `null` | Optional ISO-639-1 hint for audio transcription (e.g. `"en"`, `"pt"`). |

### `channels.websocket`

See [websocket.md](./websocket.md) for the full reference. Quick recap of the
most common knobs:

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 8765,
      "websocketRequiresToken": false
    }
  }
}
```

---

## `providers`

Femtobot ships with **33 registered providers** (see
[`femtobot/providers/registry.py`](../femtobot/providers/registry.py)). Each
entry is a `ProviderConfig`:

```json
{
  "providers": {
    "<name>": {
      "apiKey": "<key>",
      "apiBase": "https://...",
      "apiType": "auto",
      "extraHeaders": {},
      "extraBody": {}
    }
  }
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `apiKey` | str \| null | `null` | Bearer key sent as `Authorization: Bearer <key>` (or whatever the provider expects). |
| `apiBase` | str \| null | `null` | Base URL for OpenAI-compatible endpoints. Omit for native Anthropic / Google endpoints. |
| `apiType` | `"auto"` \| `"chat_completions"` \| `"responses"` | `"auto"` | API surface. **Only `providers.openai` may use a value other than `"auto"`** — enforced by `_validate_api_type_scope`. |
| `extraHeaders` | dict[str, str] \| null | `null` | Per-request headers (e.g. `APP-Code` for AiHubMix). |
| `extraBody` | dict \| null | `null` | Per-request body fields merged into every call. |

### Registered providers

`custom`, `anthropic`, `openai`, `openrouter`, `huggingface`, `skywork`,
`deepseek`, `groq`, `zhipu`, `dashscope`, `vllm`, `ollama`, `lmStudio`,
`atomicChat`, `ovms`, `gemini`, `moonshot`, `minimax`, `minimaxAnthropic`,
`mistral`, `stepfun`, `xiaomiMimo`, `longcat`, `antLing`, `aihubmix`,
`siliconflow`, `novita`, `volcengine`, `volcengineCodingPlan`, `byteplus`,
`byteplusCodingPlan`, `qianfan`, `nvidia`.

Set `agents.defaults.provider` to the exact name you populated.

Example — regional MiniMax gateway:

```json
{
  "agents":   { "defaults": { "provider": "minimax", "model": "MiniMax-M2.7" } },
  "providers": {
    "minimax": {
      "apiKey": "sk-cp-...",
      "apiBase": "https://api.minimax.io/v1"
    }
  }
}
```

---

## `api`

Settings for `femtobot serve` (the OpenAI-compatible HTTP surface — see
[openai-api.md](./openai-api.md)).

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | str | `"127.0.0.1"` | Bind address. Safer default is local-only. |
| `port` | int | `8900` | TCP port. |
| `timeout` | float | `120.0` | Per-request timeout in seconds. |

---

## `gateway`

Settings for `femtobot gateway` (the simplified headless gateway used for
health checks and the A2A roadmap).

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | str | `"127.0.0.1"` | Bind address. |
| `port` | int | `18790` | TCP port. |
| `heartbeat.enabled` | bool | `true` | Run the heartbeat job. |
| `heartbeat.intervalS` | int | `1800` | Seconds between heartbeats. |
| `heartbeat.keepRecentMessages` | int | `8` | Number of recent messages retained in the heartbeat payload. |

---

## `tools`

### `tools.web`

| Field | Type | Default | Description |
|---|---|---|---|
| `enable` | bool | `true` | Master switch for the `web_search` and `web_fetch` tools. |
| `proxy` | str \| null | `null` | HTTP proxy URL. |
| `userAgent` | str \| null | `null` | Override the user-agent header. |
| `search.provider` | str | `"duckduckgo"` | Search backend. |
| `search.apiKey` | str | `""` | API key for the search backend (if required). |
| `search.baseUrl` | str | `""` | Base URL override. |
| `search.maxResults` | int | `5` | Cap on returned results. |
| `search.timeout` | int | `30` | Per-search timeout (seconds). |
| `fetch.useJinaReader` | bool | `true` | Use Jina Reader to extract text from arbitrary URLs. |

### `tools.exec`

Sandboxed shell configuration.

| Field | Type | Default | Description |
|---|---|---|---|
| `enable` | bool | `true` | Master switch for the `exec` tool. |
| `timeout` | int | `60` | Per-command timeout (seconds). |
| `pathAppend` | str | `""` | Extra PATH entries appended for command lookup. |
| `sandbox` | str | `""` | Sandbox backend. Empty string = no sandbox. |
| `allowedEnvKeys` | list[str] | `[]` | Env-var names that may be passed through to the child process. |
| `allowPatterns` | list[str] | `[]` | Regex allow-list (additive on top of defaults). |
| `denyPatterns` | list[str] | `[]` | Regex deny-list (additive on top of `DESTRUCTIVE_DENY_PATTERNS`). |

### `tools.my`

Self-introspection tool (see [my-tool.md](./my-tool.md)).

| Field | Type | Default | Description |
|---|---|---|---|
| `enable` | bool | `true` | Master switch. |
| `allowSet` | bool | `false` | Allow `modify`/`set` actions. Default `false` makes the tool read-only. |

### Other tools flags

| Field | Type | Default | Description |
|---|---|---|---|
| `restrictToWorkspace` | bool | `false` | Policy intent: keep tool access inside the workspace when possible. Even at `false`, sensitive operations remain gated. |
| `webuiAllowLocalServiceAccess` | bool | `true` | Permit the local web UI to call back into local services (used by `femtobot gateway`). |
| `ssrfWhitelist` | list[str] | `[]` | CIDR ranges to exempt from SSRF blocking (e.g. `["100.64.0.0/10"]` for Tailscale). See [security.md](./security.md). |

### `tools.mcpServers`

A dictionary of MCP server configs. Each entry is an `MCPServerConfig`:

| Field | Type | Default | Description |
|---|---|---|---|
| `type` | `"stdio"` \| `"sse"` \| `"streamableHttp"` \| null | `null` (auto-detect) | Transport. |
| `command` | str | `""` | Stdio: command to spawn (e.g. `"uvx"`). |
| `args` | list[str] | `[]` | Stdio: command arguments. |
| `env` | dict[str, str] | `{}` | Stdio: extra env vars. |
| `cwd` | str | `""` | Stdio: working directory for the server process. |
| `url` | str | `""` | HTTP/SSE: endpoint URL. |
| `headers` | dict[str, str] | `{}` | HTTP/SSE: custom headers. |
| `toolTimeout` | int | `30` | Per-tool-call timeout in seconds. |
| `enabledTools` | list[str] | `["*"]` | Allow-list of MCP tool names; accepts raw names or `mcp_<server>_<tool>` wrapped names. `["*"]` registers all, `[]` registers none. |

Example — two agentic engines (Antigravity + Claude Code CLI):

```json
{
  "tools": {
    "mcpServers": {
      "agy-mcp-server": {
        "command": "uvx",
        "args": [
          "--from", "/abs/path/antigravity-cli-mcp",
          "fastmcp", "run", "src/agy_mcp_server/server.py"
        ],
        "cwd": "/abs/path/antigravity-cli-mcp",
        "env": {
          "AGY_MCP_MODE": "safe",
          "AGY_MCP_ALLOWED_ROOTS": "[\"/abs/path/projects\"]"
        },
        "toolTimeout": 600
      },
      "claude-code-cli-mcp": {
        "command": "uvx",
        "args": [
          "--from", "/abs/path/claude-code-cli-mcp",
          "fastmcp", "run", "src/claude_code_mcp/server.py"
        ],
        "cwd": "/abs/path/claude-code-cli-mcp",
        "env": {
          "CLAUDE_MCP_MODE": "safe",
          "CLAUDE_MCP_ALLOWED_MODELS": "[\"sonnet\", \"opus\"]"
        },
        "toolTimeout": 600
      }
    }
  }
}
```

> **Gotcha — `req` wrapper.** Most MCP servers in this ecosystem expect
> arguments under a `req` key. For example:
>
> ```json
> { "agy_run_task": { "req": { "workspace_path": "/tmp", "prompt": "echo hi" } } }
> ```
>
> Some client transports (notably certain IDE-side wrappers) drop the `req`
> envelope and pass `{}` to the server, which then fails Pydantic validation
> with `input_value={}`. If you see this, either pin the server signature to
> accept `req: In | None = None`, or wrap the call in your orchestrator.

See [mcp.md](./mcp.md) for the full guide on writing and registering MCP
servers.

---

## `modelPresets`

A dictionary of named `ModelPresetConfig` entries. Each preset bundles a model
identifier with its generation parameters.

```json
{
  "modelPresets": {
    "fast": {
      "label": "Cheap & quick",
      "model": "openai/gpt-4o-mini",
      "provider": "openrouter",
      "maxTokens": 4096,
      "contextWindowTokens": 128000,
      "temperature": 0.2
    },
    "deep": {
      "model": "anthropic/claude-3.5-sonnet",
      "provider": "openrouter",
      "maxTokens": 8192,
      "contextWindowTokens": 200000,
      "temperature": 0.1,
      "reasoningEffort": "high"
    }
  }
}
```

To activate a preset at runtime, set `agents.defaults.modelPreset` to the key
(or pass `--preset <name>` if your orchestrator exposes that flag). The
reserved name `"default"` always resolves to the implicit block under
`agents.defaults`.

---

## Environment variable interpolation

Any string in `config.json` may reference an environment variable:

```json
{ "providers": { "openai": { "apiKey": "${OPENAI_API_KEY}" } } }
```

On load, `femtobot/config/loader.py:resolve_config_env_vars()` substitutes
`${VAR}` with the value of `os.environ["VAR"]`. Missing variables raise
`ValueError`. The walker uses `BaseModel.model_fields`, so Pydantic-private
fields survive the round-trip.

---

## Validation

`femtobot/config/loader.py:load_config()` runs `Config.model_validate(data)`
on the parsed JSON. Errors are logged and a default configuration is used as
fallback (so a typo never crashes the agent at startup, but it does mean you
silently lose your overrides — always run `femtobot status` after editing
`config.json`).

The two cross-field validators worth knowing:

1. **`websocket` — wildcard host requires auth** (see [websocket.md](./websocket.md)).
2. **`providers[*].apiType`** — only `providers.openai` may be set to anything
   other than `"auto"`; all others must stay `"auto"`.

---

## See also

- [cli-reference.md](./cli-reference.md) — `femtobot status` shows the active
  resolved values for the current instance.
- [multiple-instances.md](./multiple-instances.md) — different configs per
  instance via `--suffix` / `--folder-path`.
- [memory.md](./memory.md) — what the `dream` block actually does.
- [websocket.md](./websocket.md) — full `channels.websocket` schema.
- [mcp.md](./mcp.md) — full `tools.mcpServers` workflow.
- [security.md](./security.md) — SSRF, command guard, workspace policy.