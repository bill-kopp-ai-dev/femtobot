# Architecture

Femtobot is a CLI-first single-agent runtime. Stage 2 (A2A) will compose
multiple agents; today, the runtime is one process that loads a config, builds
an `AgentLoop`, and runs an interactive or programmatic turn loop.

This page maps the major subsystems, the data they exchange, and the failure
modes you'll encounter when extending Femtobot.

---

## High-level data flow

```
                    ┌──────────────────────────────────┐
                    │            config.json           │
                    └─────────────────┬────────────────┘
                                      │ load
                                      ▼
┌────────────┐  stdin/HTTP/WS    ┌────────────┐    chat.completions    ┌────────────┐
│   User /   │ ───────────────▶ │  Femtobot  │ ──────────────────────▶ │  Provider  │
│  Client    │                  │   main     │                        │   (LLM)    │
└────────────┘ ◀─────────────── └─────┬──────┘ ◀────────────────────── └────────────┘
                                     │
                                     │ spawns
                                     ▼
                            ┌──────────────────┐
                            │     Femtobot     │   Facade for SDK use.
                            │   (facade)       │
                            └────────┬─────────┘
                                     │ owns
                                     ▼
                            ┌──────────────────┐
                            │    AgentLoop     │   Reusable turn loop.
                            └────────┬─────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
   ┌────────┐                  ┌──────────┐                  ┌────────────┐
   │ Tools  │                  │  Memory  │                  │  Channels  │
   └────┬───┘                  └────┬─────┘                  └─────┬──────┘
        │                            │                              │
        ▼                            ▼                              ▼
   read/write/exec/grep/web/mcp   session.jsonl              CLI / WebSocket
                                  history.jsonl              (OpenAI HTTP not
                                  MEMORY.md (Git)            channel-routed)
```

A user message flows: **Client → Femtobot.main → AgentLoop → Provider → LLM**
and back. Tool calls (decided by the LLM) are dispatched by the loop to the
matching tool, results are appended to the prompt, and the loop continues
until the LLM emits a final response or hits the iteration cap.

---

## Subsystems

### 1. Config loader — `femtobot/config/`

| File | Role |
|---|---|
| `loader.py` | `load_config(path)` reads JSON, runs Pydantic validation, falls back to defaults on error (logged). Walks the model and substitutes `${VAR}` env vars. |
| `paths.py` | Resolves instance, workspace, sessions, and config paths from `FEMTOBOT_HOME` / `--suffix` / `--folder-path`. |
| `schema.py` | The Pydantic schema for everything documented in [configuration.md](./configuration.md). |

The loader is forgiving by design — a typo in `config.json` does not crash the
agent, but it does mean your overrides get silently dropped. Always run
`femtobot status` after edits.

### 2. Provider registry — `femtobot/providers/`

34 providers, indexed by `agents.defaults.provider`. Each provider knows how
to build its own request payload and parse the response. All providers
implement `BaseProvider.acomplete(messages, **kwargs)`.

| File | Role |
|---|---|
| `registry.py` | Lookup by name. Falls back to `AutoProvider` (model-prefix detection) when `provider: "auto"`. |
| `openai_compat.py` | Shared OpenAI-compatible transport (used by ~25 of the 33 providers). |
| `anthropic.py` | Native Anthropic Messages API. |
| `gemini.py` | Native Google Generative AI. |
| `<provider>.py` | One file per provider that needs custom transport. |

### 3. AgentLoop — `femtobot/agent/loop.py`

The reusable per-turn executor. Each call to `AgentLoop.run(messages)`:

1. Selects the provider based on `agents.defaults.provider`.
2. Applies generation params (`temperature`, `maxTokens`, `reasoningEffort`).
3. Sends the prompt to the provider.
4. On tool-call response: dispatches each call, captures the result, appends
   it to the prompt, and continues.
5. On text response: returns the final `RunResult`.
6. Counts toward `agents.defaults.maxToolIterations`; aborts if exceeded.

Hooks (`AgentHook`) are invoked at four points: `pre_iteration`,
`post_iteration`, `pre_tool`, `post_tool`.

### 4. Tools — `femtobot/agent/tools/`

Each tool is a class decorated with `@register_tool(name=...)`. The runner
discovers them via the registry and injects them into the prompt based on
`agents.defaults.disabledSkills`.

See [tools.md](./tools.md) for the full list and [my-tool.md](./my-tool.md)
for the special `self` tool.

### 5. Memory — `femtobot/agent/memory.py` + `autocompact.py`

Three layers, see [memory.md](./memory.md). The summary:

```
session.jsonl  ── Consolidator ──▶  history.jsonl
                                       │
                                       ▼
                              Dream (periodic)
                                       │
                                       ▼
                  MEMORY.md / USER.md / SOUL.md (Git-tracked)
```

`AutoCompact` runs the Consolidator on idle sessions after
`sessionTtlMinutes`.

### 6. Channels — `femtobot/channels/`

Today, only `websocket.py` (and the placeholder `gateway` HTTP surface). The
Channel abstraction is small:

```python
class BaseChannel:
    def __init__(self, config: Any, bus: MessageBus): ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
```

See [websocket.md](./websocket.md). Adding a new channel is a single class
plus a registration entry in `channels/__init__.py`.

### 7. API server — `femtobot/api/server.py`

aiohttp app exposing the OpenAI-compatible surface (see
[openai-api.md](./openai-api.md)). Single agent loop, per-session locks, SSE
streaming support. Started by `femtobot serve`.

### 8. CLI — `femtobot/cli/`

Typer app with subcommands. See [cli-reference.md](./cli-reference.md). The
`agent` subcommand spawns the AgentLoop in interactive or single-shot mode;
slash commands are routed through `command/router.py`.

---

## The "Femtobot" public class

[`femtobot/femtobot.py`](../femtobot/femtobot.py) is the public facade for
SDK users:

```python
from femtobot import Femtobot
bot = Femtobot.from_config("/home/me/.femtobot/config.json")
result = await bot.run("Hello!", session_key="sdk:default")
```

Internally, it:

1. Loads and validates the config.
2. Creates a `MessageBus` (the in-process pub/sub).
3. Creates an `AgentLoop` with that bus.
4. Returns a `Femtobot` that you call `await bot.run(...)` on.

For multi-call use, create one `Femtobot` per session key. Calling `run`
concurrently on the same `Femtobot` is not safe.

---

## Concurrency model

Femtobot is **single-threaded asyncio** throughout. There are no threads, no
process pools, no GIL juggling. The trade-off is simplicity:

- The agent loop yields between awaits, so provider round-trips do not block
  other concurrent activities on the same loop.
- For CPU-bound work (e.g. file scans), use `asyncio.to_thread` and keep the
  chunks small.
- MCP servers run in subprocesses (managed by the official `mcp` SDK) and
  communicate back via stdio. The MCP client side uses `asyncio` streams.

---

## Failure modes and recovery

| Subsystem | What can fail | How Femtobot recovers |
|---|---|---|
| Config load | Bad JSON, Pydantic validation | Logged warning, falls back to defaults. Run `femtobot status` to confirm. |
| Provider API call | 401, 429, 5xx, network error | The provider client retries per `providerRetryMode` (`"standard"` or `"persistent"`). |
| Tool execution | Exception inside a tool | The loop catches it, returns the exception message to the model as the tool result, and continues. The loop does NOT abort unless the exception is in a registered critical path. |
| WebSocket disconnect | Client drops | The channel cleans up its session lock and closes gracefully. |
| MCP server crash | Server process exits | The MCP session is marked failed; tools from that server are temporarily unavailable until the next reconnect. |
| OOM | Long tool result with massive output | `agents.defaults.maxToolResultChars` truncates the result before it lands in the prompt. |

---

## Extension points

If you want to customize Femtobot without forking:

1. **New provider.** Add a file under `femtobot/providers/` implementing
   `BaseProvider`, and register it in `registry.py`.
2. **New tool.** Add a file under `femtobot/agent/tools/` implementing a
   class with a `run(**kwargs) -> str` method, decorated with
   `@register_tool(name=...)`.
3. **New channel.** Add a file under `femtobot/channels/` implementing
   `BaseChannel`, and import it in `channels/__init__.py`.
4. **New slash command.** Add a handler to
   `femtobot/command/builtin.py` and register it via the `register_router`.
5. **Hook the loop.** Pass a `hooks=[...]` list to `Femtobot.run()` or
   `AgentLoop.run()`.

---

## See also

- [configuration.md](./configuration.md) — every config knob
- [memory.md](./memory.md) — the three-layer memory architecture in detail
- [tools.md](./tools.md) — every built-in tool
- [mcp.md](./mcp.md) — the MCP integration point
- [security.md](./security.md) — the security model
- [troubleshooting.md](./troubleshooting.md) — when things break