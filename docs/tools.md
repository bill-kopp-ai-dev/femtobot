# Native Tools Reference

Femtobot ships with **13 native tools** grouped by purpose, plus MCP-wrapped
tools contributed by every server registered under `tools.mcpServers` (see
[mcp.md](./mcp.md)). All tools are implemented in
[`femtobot/agent/tools/`](../femtobot/agent/tools/).

This page describes the inputs, outputs, and gotchas of each native tool. The
JSON Schema in the tool's `parameters` property is the source of truth — what
follows is a human-friendly summary.

---

## Filesystem

### `read_file`

Read a file's contents with optional line-based pagination.

| Param | Type | Description |
|---|---|---|
| `path` | str | Absolute or workspace-relative path. |
| `limit` | int (default `2000`) | Max lines to read. |
| `from_line` | int (default `0`) | Starting line index (0-based). |

Caps: max 128,000 characters per call. PDFs auto-extracted up to 20 pages.
Binary files return an error.

### `write_file`

Create or overwrite a file.

| Param | Type | Description |
|---|---|---|
| `path` | str | Absolute or workspace-relative path. |
| `content` | str | Full file content. |

**Will refuse** paths outside the workspace if `tools.restrictToWorkspace`
is `true`.

### `edit_file`

Replace a specific span of text in a file.

| Param | Type | Description |
|---|---|---|
| `path` | str | Target path. |
| `old_text` | str | Exact text to find. |
| `new_text` | str | Replacement. |
| `replace_all` | bool (default `false`) | Replace every occurrence. |

Returns the number of replacements made (0 = no-op + warning).

### `apply_patch`

Apply a batch of structured edits.

```json
{
  "edits": [
    {"path": "src/foo.py", "action": "replace", "old_text": "x = 1", "new_text": "x = 2"},
    {"path": "src/bar.py", "action": "add", "old_text": "", "new_text": "# new file header\n"}
  ],
  "dry_run": false
}
```

| Param | Type | Description |
|---|---|---|
| `edits` | list (1–20 items) | The edits to apply. |
| `dry_run` | bool (default `false`) | Validate and summarize without writing. |

`action` is `"replace"` (must include `old_text` and `new_text`) or `"add"`
(must include `new_text`). Use `dry_run: true` first to preview multi-file
patches.

### `list_dir`

List a directory.

| Param | Type | Description |
|---|---|---|
| `path` | str | Absolute or workspace-relative path. |
| `max_entries` | int (default `500`) | Cap on returned entries. |
| `include_hidden` | bool (default `false`) | Include dotfiles. |

Returns entries as `{"name": str, "type": "file"|"dir", "size": int}`.

---

## Search

### `find_files`

Find files by path fragment, glob, or extension.

| Param | Type | Description |
|---|---|---|
| `pattern` | str | Glob (`*.py`) or substring. |
| `type` | str (optional) | File type filter (e.g. `"py"`, `"md"`). |
| `max_results` | int (default `100`) | Cap. |

Skips `.git`, `node_modules`, `__pycache__`, `.venv`, `target`, `dist`, `build`,
`.cache`, `.femtobot/workspace/sessions`.

### `grep`

Search file contents by regex.

| Param | Type | Description |
|---|---|---|
| `pattern` | str | Regex pattern. |
| `path` | str (optional) | Directory to search in (default: workspace). |
| `glob` | str (optional) | Filename glob filter. |
| `case_insensitive` | bool (default `false`) | |
| `max_results` | int (default `50`) | Cap. |
| `context` | int (default `0`) | Lines of context around each match. |

Returns matches as `{"path": str, "line": int, "text": str}`.

---

## Shell

### `exec`

Execute a shell command.

| Param | Type | Default | Description |
|---|---|---|---|
| `command` | str | required | The shell command. |
| `timeout` | int | `60` | Per-command timeout (seconds). |

Returns `{"stdout": str, "stderr": str, "exit_code": int, "duration_ms": int}`.
Large outputs are truncated to fit `agents.defaults.maxToolResultChars`.

**Command guard.** A built-in deny list (`DESTRUCTIVE_DENY_PATTERNS`) blocks
common foot-guns: `rm -rf /`, `mkfs`, `dd of=/dev/...`, `chmod -R 777 /`, etc.
You can extend via `tools.exec.denyPatterns`. The matcher is regex-based and
case-sensitive.

**Sandbox.** If `tools.exec.sandbox` is set to a backend (e.g. `bubblewrap`,
`firejail`, `docker`), commands are wrapped. Empty string = no sandbox.

**PATH injection.** Use `tools.exec.pathAppend` to add directories to `$PATH`
without polluting the agent's own environment.

### `write_stdin`

Write to the stdin of an existing exec session.

| Param | Type | Description |
|---|---|---|
| `session_id` | str | The exec session ID returned by `exec`. |
| `input` | str | The data to write. |

Useful for interactive REPLs: `exec` opens Python in a session, `write_stdin`
feeds it commands.

### `list_exec_sessions`

Return the list of active exec sessions. No parameters.

---

## Web

### `web_search`

Search the public web.

| Param | Type | Default | Description |
|---|---|---|---|
| `query` | str | required | Search query. |
| `max_results` | int | `5` | Cap. |
| `provider` | str | `"duckduckgo"` | Backend override. |
| `api_key` | str | `""` | API key for paid backends. |

Default backend is DuckDuckGo HTML scraping — no key required, but rate
limited. For higher volume, set `tools.web.search.provider` and the
corresponding `apiKey` in `config.json`.

### `web_fetch`

Fetch and extract text from a URL.

| Param | Type | Default | Description |
|---|---|---|---|
| `url` | str | required | Target URL. |
| `max_chars` | int | `20000` | Cap on extracted text. |
| `use_jina_reader` | bool | `true` | Use Jina Reader for robust extraction. |

SSRF protection: requests to private IP ranges (RFC 1918, link-local, loopback)
are denied unless the host is in `tools.ssrfWhitelist` or matches `127.0.0.1`.
See [security.md](./security.md).

---

## Self (introspection)

### `my`

Read and adjust runtime configuration. See [my-tool.md](./my-tool.md) for the
full surface area and the security layers that protect it.

| Param | Type | Description |
|---|---|---|
| `action` | str | `"inspect"` / `"check"` (read) or `"modify"` / `"set"` (write). |
| `key` | str (optional) | Dotted path (e.g. `"temperature"`, `"providers.openai"`). |
| `value` | any (optional) | New value when `action=modify`. |

---

## Channels

### `message`

Send a message back to the user via a configured channel.

| Param | Type | Description |
|---|---|---|
| `content` | str | The message text. |
| `channel` | str (optional) | Target channel name. Default: the current one. |

Used by the agent to push status / progress without waiting for the final
response. See [cli-reference.md](./cli-reference.md) for the
`channels.sendProgress` config knob that controls whether these are emitted
at all.

---

## MCP-wrapped tools

Any tool exposed by an MCP server registered under `tools.mcpServers` is
auto-rewrapped as a Femtobot tool. The wrapping prefix is
`mcp_<sanitized_server_name>_<sanitized_tool_name>`.

For example, an MCP server named `agy-mcp-server` that exposes `agy_run_task`
becomes:

```text
mcp_agy_mcp_server_agy_run_task
```

You can restrict which tools get registered per server via
`tools.mcpServers.<name>.enabledTools` in `config.json`. See
[mcp.md](./mcp.md) and [configuration.md](./configuration.md#toolsmcpservers).

---

## Disabled skills

To remove a built-in tool from the registry, add its name to
`agents.defaults.disabledSkills`:

```json
{ "agents": { "defaults": { "disabledSkills": ["exec", "web_fetch"] } } }
```

Disabled tools disappear from the prompt entirely — the model never sees them
and never tries to call them.

---

## Bundled skills

Femtobot ships a built-in skill that helps the agent decide when to
delegate a coding task to an MCP-wrapped agent (`agy_run_task` /
`claude_run_task`) versus solving it locally:

| Skill | Purpose | Loaded by default? |
|---|---|---|
| `mcp-router` | Decides between local tools and MCP delegation. Documents the `confirm` gate for safe-mode writes. | No (opt-in via description match) |

Source: [`femtobot/skills/mcp-router/SKILL.md`](https://github.com/bill-kopp-ai-dev/femtobot/blob/main/femtobot/skills/mcp-router/SKILL.md).

The skill is discovered by `SkillsLoader` and summarized in the system
prompt under `## Skills Summary`. Its `metadata.femtobot.always: false`
frontmatter means the agent reads it lazily — only when the task profile
matches the skill's description.

For details on how MCP-wrapped tools compose with skills, see
[mcp.md § "Femtobot-specific patterns"](./mcp.md#femtobot-specific-patterns).

---

## Adding a new tool

1. Create `femtobot/agent/tools/my_tool.py` with a class implementing
   `Tool`:

```python
from femtobot.agent.tools.base import Tool

class MyTool(Tool):
    _scopes = {"core"}

    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "What my tool does (one sentence, model-facing)."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "..."},
            },
            "required": ["input"],
        }

    async def run(self, *, input: str, context=None) -> str:
        return f"Echo: {input}"
```

2. The `ToolLoader` discovers classes that subclass `Tool` and are
   `_plugin_discoverable = True` (the default). It registers them
   automatically on agent startup.

3. Test by calling `femtobot agent -m "Use my_tool with input=hi"`.

For tools that need runtime references (e.g. the `self` tool), set
`_plugin_discoverable = False` and wire them in
`femtobot/agent/runner.py` manually.

---

## See also

- [my-tool.md](./my-tool.md) — the special `self` tool
- [mcp.md](./mcp.md) — adding tools via MCP servers
- [configuration.md](./configuration.md#tools) — `tools.*` config knobs
- [security.md](./security.md) — SSRF, command guard, workspace policy
- [architecture.md](./architecture.md) — where the tool registry sits in the
  agent loop