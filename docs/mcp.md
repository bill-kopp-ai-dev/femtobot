# MCP — Model Context Protocol

Femtobot treats MCP as a first-class integration point. Every tool exposed by
a registered MCP server is auto-wrapped as a Femtobot tool and made available
to the agent's loop.

This page covers:

1. The MCP server config schema (`tools.mcpServers.<name>`).
2. How server tools are exposed to Femtobot (the wrapping rules).
3. How to write a minimal MCP server that integrates cleanly.
4. The `req`-wrapper convention this ecosystem uses, and how to make your
   server resilient to client-side argument-drop bugs.

For the full MCP protocol, see <https://modelcontextprotocol.io/>.

---

## 1. Server config schema

The full schema lives in `femtobot/config/schema.py:MCPServerConfig`:

```python
class MCPServerConfig(Base):
    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: str = ""
    url: str = ""
    headers: dict[str, str] = {}
    tool_timeout: int = 30
    enabled_tools: list[str] = ["*"]
```

The camelCase JSON aliases (`toolTimeout`, `enabledTools`, `streamableHttp`)
are also accepted. See [configuration.md](./configuration.md#toolsmcpservers).

### Stdio transport

The server runs as a child process and communicates over its stdin/stdout.

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
      }
    }
  }
}
```

| Field | Description |
|---|---|
| `command` | Executable to spawn. Must be on `$PATH` or an absolute path. |
| `args` | CLI arguments. **Order matters** — `uvx` reads `--from PATH` as the package source, then runs the rest verbatim. |
| `cwd` | Working directory for the server process. **Strongly recommended** so the server can resolve its own relative imports. |
| `env` | Extra env vars merged on top of the parent's env. Use this to pass API keys, modes, allow-lists, etc. |
| `toolTimeout` | Per-tool-call timeout in **seconds** (not milliseconds — the Pydantic field is `int`, default `30`). |

### HTTP / SSE transports

```json
{
  "tools": {
    "mcpServers": {
      "remote-mcp": {
        "type": "streamableHttp",
        "url": "https://mcp.example.com/v1",
        "headers": {
          "Authorization": "Bearer ${REMOTE_MCP_TOKEN}"
        },
        "toolTimeout": 60
      }
    }
  }
}
```

| Field | Description |
|---|---|
| `type` | `"sse"` (legacy) or `"streamableHttp"` (MCP 2025 spec). `null` = auto-detect. |
| `url` | The endpoint URL. |
| `headers` | Custom headers (e.g. `Authorization`). Supports `${VAR}` substitution via the same loader that handles `config.json`. |
| `toolTimeout` | Same as stdio. |

### `enabledTools` allow-list

By default Femtobot registers **every** tool the server exposes (`["*"]`).
Narrow it:

```json
{
  "agy-mcp-server": {
    "command": "uvx",
    "args": [...],
    "enabledTools": ["agy_run_task", "agy_health", "agy_self_test"]
  }
}
```

Each entry can be either:

- The raw tool name (e.g. `agy_run_task`).
- The wrapped Femtobot name (`mcp_agy_mcp_server_agy_run_task`).

Both forms work; pick whichever you find clearer in logs.

---

## 2. How server tools get wrapped

`femtobot/agent/tools/mcp.py` implements a `MCPToolWrapper` that:

1. On agent startup, calls the server's `tools/list` method.
2. For each tool, creates a `Tool` instance whose `name` is
   `mcp_<sanitized_server>_<sanitized_tool>` (e.g.
   `mcp_agy_mcp_server_agy_run_task`).
3. Injects the wrapped tools into the registry so the prompt sees them.
4. On call, sends `tools/call` to the server with the original arguments.

Tools/resources/prompts from the server are all wrapped:

| Server concept | Femtobot prefix |
|---|---|
| Tools | `mcp_<server>_<tool>` |
| Resources | `mcp_<server>_resource_<resource>` |
| Prompts | `mcp_<server>_prompt_<prompt>` |

See [tools.md](./tools.md#mcp-wrapped-tools) for the runtime perspective.

---

## 3. Writing a minimal MCP server that integrates cleanly

The simplest possible FastMCP server:

```python
# src/my_server/server.py
from fastmcp import FastMCP

mcp = FastMCP("my-mcp-server")

@mcp.tool()
async def hello(req: HelloRequest) -> dict:
    """Greet the user."""
    return {"message": f"Hello, {req.name}!"}
```

Add it to Femtobot's config:

```json
{
  "tools": {
    "mcpServers": {
      "my-mcp-server": {
        "command": "uvx",
        "args": ["--from", "/abs/path/my-mcp", "fastmcp", "run", "src/my_server/server.py"],
        "cwd": "/abs/path/my-mcp",
        "toolTimeout": 30
      }
    }
  }
}
```

On the next `femtobot agent` start, you'll see `mcp_my_mcp_server_hello` in
the prompt.

---

## 4. The `req` wrapper convention

This ecosystem (Femtobot, the antigravity and claude-code servers, several
internal tools) standardized on a single-key argument envelope:

```python
@mcp.tool()
async def my_tool(req: MyRequest) -> dict:
    # the model sends: {"req": {"param_a": "...", "param_b": 123}}
    ...
```

Why?

- **Forward compat.** Adding optional params to `MyRequest` is a non-breaking
  change for clients. Without the envelope, every client must be updated.
- **Schema isolation.** The Pydantic validator for `MyRequest` runs once,
  on the inner object. The client doesn't need to know about it.

The `req` parameter is the *only* argument. The model never sends anything
else. Wrap your tool like this:

```python
from pydantic import BaseModel, Field

class EchoRequest(BaseModel):
    text: str = Field(..., description="Text to echo back.")

@mcp.tool()
async def echo(req: EchoRequest) -> dict:
    return {"echo": req.text}
```

### The "args arrive as `{}`" trap

Some MCP client wrappers (notably Trae IDE and Claude Code's MCP client)
serialize arguments as `{}` when the signature has required fields. The
server then fails Pydantic validation with:

```
2 validation errors for EchoRequest
text
  Field required [type=missing, input_value={}]
```

This is a **client-side bug**, but you can defend against it by making `req`
optional:

```python
@mcp.tool()
async def echo(req: EchoRequest | None = None) -> dict:
    if req is None:
        # Client sent the bug-shape. Best-effort fallback.
        return {"echo": "(empty)"}
    return {"echo": req.text}
```

The cost: a slightly wider type. The benefit: your server works against
both well-behaved and buggy clients. Both `agy-mcp-server` and
`claude-code-cli-mcp` use this pattern.

For a deeper analysis and a JSON-RPC bypass for when the wrapper still
mangles arguments, see the `MCP_USER_GUIDE.md` of those repos.

---

## 5. Discovering tools at runtime

To list the tools Femtobot currently sees from a given server, drop into
the REPL and run:

```text
self(action="check", key="tools")
```

…or use `/tools` from the slash command list. The output includes MCP-wrapped
tools prefixed with `mcp_<server>_`. If a server is registered but its tools
don't appear, check `femtobot --verbose` for `mcp: connection` log lines.

---

## 6. Operational notes

### Process lifecycle

- The MCP server is spawned once when Femtobot starts. It's torn down on
  `Ctrl+C` / SIGTERM.
- The MCP client uses the official `mcp` Python SDK with the stdio transport
  by default. It opens two asyncio streams per server.
- There is **no auto-reconnect today** — if the server dies mid-session, the
  affected tools become unavailable until you restart Femtobot. Track this
  via `femtobot --verbose`.

### `cwd` is required for local-path servers

If your `command` is `uvx --from /abs/path/my-mcp`, the spawned process
starts in Femtobot's CWD, not the package's directory. The MCP server may
then fail to import its own local modules.

**Always set `cwd`** to the package's root directory:

```json
{
  "my-mcp-server": {
    "command": "uvx",
    "args": ["--from", "/abs/path/my-mcp", "fastmcp", "run", "src/my_server/server.py"],
    "cwd": "/abs/path/my-mcp",
    "toolTimeout": 30
  }
}
```

### `uvx --refresh` cost

`uvx --refresh` forces a full re-install on every spawn, which adds ~5–20
seconds to Femtobot's startup. Drop it for long-running agents and only
re-enable it when you've changed server source and want Femtobot to pick
up the change without a manual cache clear.

### `toolTimeout` units

The Pydantic field is `int tool_timeout = 30` — that's **seconds**, not
milliseconds. For long-running operations (a full code agent session can
take minutes), set this generously:

```json
{ "agy-mcp-server": { "toolTimeout": 600 } }
```

The env-var equivalents on the servers themselves
(`START_MCP_TIMEOUT_MS`, `RUN_MCP_TIMEOUT_MS`) are milliseconds and govern
how long the server is willing to wait internally; the Femtobot-side
`toolTimeout` is the outer cap.

---

## 7. Common patterns

### Agentic engine pair (Antigravity + Claude Code)

```json
{
  "tools": {
    "mcpServers": {
      "agy-mcp-server": {
        "command": "uvx",
        "args": ["--from", "/abs/path/antigravity-cli-mcp",
                 "fastmcp", "run", "src/agy_mcp_server/server.py"],
        "cwd": "/abs/path/antigravity-cli-mcp",
        "env": {
          "AGY_MCP_MODE": "safe",
          "AGY_MCP_ALLOWED_ROOTS": "[\"/abs/path/projects\"]"
        },
        "toolTimeout": 600
      },
      "claude-code-cli-mcp": {
        "command": "uvx",
        "args": ["--from", "/abs/path/claude-code-cli-mcp",
                 "fastmcp", "run", "src/claude_code_mcp/server.py"],
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

Femtobot then exposes the union of both servers' tools to the model. The
orchestrator prompt can bias the model toward one or the other via
`agents.defaults.fallbackModels` or system-prompt content.

### Read-only MCP server

```json
{
  "docs-mcp": {
    "command": "uvx",
    "args": ["--from", "/abs/path/docs-mcp",
             "fastmcp", "run", "src/docs_mcp/server.py"],
    "enabledTools": ["docs_search", "docs_fetch"],
    "toolTimeout": 30
  }
}
```

Even if the server exposes 20 tools, only the two listed are registered.

### Per-environment server

Use `FEMTOBOT_MCP_SERVERS__<NAME>__TOOL_TIMEOUT` env var to override
per-process without editing `config.json`:

```bash
FEMTOBOT_MCP_SERVERS__AGY_MCP_SERVER__TOOL_TIMEOUT=900 femtobot serve
```

---

## 8. Femtobot-specific patterns

The generic MCP rules above apply; this section covers Femtobot's
ergonomics layered on top.

### The `mcp-router` skill

Femtobot ships a builtin skill, [`femtobot/skills/mcp-router/SKILL.md`](../femtobot/skills/mcp-router/SKILL.md),
that teaches the agent when to delegate a coding task to a wrapped
agent (`agy_run_task` / `claude_run_task`) versus solving it locally
with `read_file`, `apply_patch`, etc.

Highlights:

- Loaded lazily (frontmatter `always: false`). The agent reads it when
  the user's request matches the skill description.
- Documents the **`mode=safe` + `confirm` gate** for both servers:
  writes require `confirm=true`, which the agent must only set after
  explicit user approval.
- Provides the **server-selection matrix**: long-horizon planning →
  agy; quick focused coding → claude; comparison → both.

You can disable the skill per-instance with:

```json
{
  "agents": { "defaults": { "disabledSkills": ["mcp-router"] } }
}
```

### Tool naming convention

MCP-wrapped tools follow `mcp_<sanitized_server>_<sanitized_tool>`:

- `agy-mcp-server` + `agy_run_task` → `mcp_agy_mcp_server_agy_run_task`
- `claude-code-cli-mcp` + `claude_run_task` →
  `mcp_claude_code_cli_mcp_claude_run_task`

Both prefixes (`agy_run_task`, `claude_run_task`) require `workspace_path`
as an absolute path that matches one of the server's
`AGY_MCP_ALLOWED_ROOTS` / `CLAUDE_MCP_ALLOWED_ROOTS`. The femtobot's
own workspace is *not* automatically on either list unless you add it
explicitly.

### Capability tags (model-facing hints)

Femtobot decorates MCP-wrapped tool hints with capability tags so the
model can see at a glance whether a tool is long-running or requires
confirmation. The hint for `agy_run_task` becomes:

```text
agy_mcp_server::agy_run_task("/abs/path") [long-running, safe-mode:confirm]
```

Currently catalogued tags:

| Tool | Tags |
|---|---|
| `agy_run_task` | `long-running`, `safe-mode:confirm` |
| `claude_run_task` | `long-running`, `safe-mode:confirm` |
| `agy_health` | `read-only`, `cheap` |
| `agy_self_test` | `read-only`, `cheap` |
| `claude_health` | `read-only`, `cheap` |

Unknown MCP tools render without tags (back-compat).

In addition to the per-hint suffix, Femtobot also injects a `## MCP
Servers in this workspace` block into the system prompt listing each
connected server and its tools with their tags, so the model can plan
its tool choice before the first call.

### Confirm gate in safe mode

When a server is started with `AGY_MCP_MODE=safe` (or `CLAUDE_MCP_MODE=safe`)
and `*_MCP_FORCE_SANDBOX_IN_SAFE_MODE=true` (the default in
[the open-cli-router reference config](../.femtobot/config.json)),
every write through `*_run_task` requires:

1. First call: `confirm: false` → server returns the proposed plan.
2. Femtobot (or the user) reviews the plan.
3. Second call: `confirm: true` → server executes.

Set `confirm: true` *only* after explicit user approval. The
`mcp-router` skill is the canonical source for this contract.

---

## 9. Security

See [security.md](./security.md#mcp-server-isolation) for the broader
threat model. Two MCP-specific points worth repeating:

- **Run the agent as a low-privilege user.** A malicious MCP server can read
  any file the agent's UID can read.
- **Always set `enabledTools` to the minimum allow-list.** Don't rely on the
  server to do the gating — it might be compromised.

---

## See also

- [configuration.md](./configuration.md#toolsmcpservers) — full
  `tools.mcpServers` schema
- [troubleshooting.md](./troubleshooting.md#mcp) — MCP failure modes
- [tools.md](./tools.md#mcp-wrapped-tools) — the runtime perspective
- [security.md](./security.md#mcp-server-isolation) — isolation guarantees
- <https://modelcontextprotocol.io/> — the MCP spec