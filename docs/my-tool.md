# Self Tool (`my`)

The `self` tool (formerly "my tool") lets the agent sense and adjust its own
runtime state. It's an internal introspection mechanism — every other tool acts
on the outside world, this one acts on Femtobot itself.

The tool is implemented in [`femtobot/agent/tools/self.py`](../femtobot/agent/tools/self.py).
It's gated by `tools.my.enable` (default `true`).

---

## Actions

The tool accepts two actions, each with two accepted names:

| Alias pair | Verb | Mutates state? |
|---|---|---|
| `inspect` / `check` | Read a config value, runtime attribute, or sub-object | No |
| `modify` / `set` | Write a config value or runtime attribute | **Yes** — disabled by default |

### `inspect` / `check` — read state

```text
self(action="check")
# → Full snapshot of inspectable runtime state (filtered against BLOCKED / READ_ONLY)
```

Drill into a specific key:

```text
self(action="check", key="model")
# → "minimax/MiniMax-M2.7"

self(action="check", key="workspace")
# → "/home/bill/Codes/CLI-router-project/.femtobot/workspace"

self(action="check", key="tools")
# → ["read_file", "write_file", "apply_patch", "exec", "grep", ...]
```

The `key` argument walks dotted paths, so `key="providers.openai.api_key"` is
also valid (though `api_key` is filtered — see [Security](#security)).

### `modify` / `set` — write state

```text
self(action="set", key="temperature", value=0.3)
# → Confirms the change and returns the new value

self(action="modify", key="botName", value="Percival")
# → Same thing
```

The modify action is **disabled by default**. To enable it, set
`tools.my.allowSet: true` in `config.json`:

```json
{ "tools": { "my": { "enable": true, "allowSet": true } } }
```

> **Even with `allowSet: true`, the BLOCKED / READ_ONLY / _SENSITIVE_NAMES
> lists below still apply.** `allowSet` only controls whether the modify
> action is callable at all — it does not bypass attribute-level protection.

---

## Practical Scenarios

### Self-diagnosis

```text
User: "Which model are you using?"
Agent: Let me check my configuration.
→ self(action="check", key="model")
```

### Workspace location before a write

```text
Agent: Let me check where my workspace is located before I write the file.
→ self(action="check", key="workspace")
```

### Adjusting temperature mid-session (with allowSet)

```text
User: "Be more creative on the next answer."
Agent: Lowering the temperature constraint.
→ self(action="set", key="temperature", value=0.4)
```

### Listing available tools

```text
User: "What can you actually do here?"
→ self(action="check", key="tools")
```

---

## Security

The `self` tool is one of the highest-risk tools in the agent, because it can
poke at the runtime. Femtobot enforces **three layered protections**, defined
as class-level frozensets in `MyTool`:

### 1. `BLOCKED` — completely off-limits

Cannot be inspected *or* modified. These names simply do not exist from the
agent's perspective:

| Category | Blocked names |
|---|---|
| Core infrastructure | `bus`, `provider`, `_running`, `tools` |
| Config management | `_runtime_vars` |
| Subsystems | `runner`, `sessions`, `consolidator`, `dream`, `auto_compact`, `context`, `commands` |
| Sensitive runtime state | `_mcp_servers`, `_mcp_stacks`, `_pending_queues`, `_session_locks`, `_background_tasks` |
| Security boundaries | `restrict_to_workspace`, `channels_config`, `_concurrency_gate`, `_unified_session`, `_extra_hooks` |

### 2. `READ_ONLY` — inspectable, not modifiable

Even if `allowSet` is `true`, these cannot be written:

| Name | Why |
|---|---|
| `_current_iteration` | Updated by the runner only — agent self-mutation would desync the loop. |
| `exec_config` | Inspect for diagnostics (e.g. check sandbox), modify blocked. |
| `web_config` | Inspect for diagnostics, modify blocked. |
| `workspace_sandbox` | Read-only view of workspace enforcement level. |

### 3. `_SENSITIVE_NAMES` — filtered from any sub-dict

These sub-field names are redacted from any nested response, regardless of
which parent they appear under:

```
api_key, token, password, secret, authorization, …
```

So even if you call `self(action="check", key="providers")`, the `apiKey`
fields of every provider come back as `"<redacted>"`. This prevents the agent
from exfiltrating credentials into its prompt or output stream.

### 4. `_DENIED_ATTRS` — Python introspection guard

Names that would let the agent bypass the above by reaching into Python's
introspection machinery:

```
__class__, __dict__, __bases__, __subclasses__, __mro__,
__init__, __new__, __reduce__, __getstate__, __setstate__, __del__,
__call__, __getattr__, __setattr__, __delattr__,
__code__, __globals__, __wrapped__, __closure__, …
```

This is defense-in-depth against prompt-injection attacks that try to
traverse the object graph to reach sensitive state.

---

## Best practices for orchestrator builders

- **Leave `allowSet: false`** unless you have a concrete need. The agent can
  still inspect; that is usually enough.
- **If you enable `allowSet`**, log every `modify` action and review for
  privilege escalation patterns (the agent changing its own tool registry,
  blocking its own audit hooks, etc.).
- **Treat the `self` tool as an admin surface.** When running Femtobot as a
  service, consider whether to expose it at all (the WebSocket channel
  surfaces all tools; the OpenAI HTTP API does not, by default — but if you
  wire MCP servers into the API path, the `self` tool will be reachable).

---

## See also

- [configuration.md](./configuration.md#toolsmy) — `tools.my.enable` and `tools.my.allowSet`
- [security.md](./security.md) — the broader security model (SSRF, command
  guard, workspace policy)
- [architecture.md](./architecture.md) — where the `self` tool sits in the
  agent loop