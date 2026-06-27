# Femtobot Documentation

This folder is the canonical documentation for Femtobot. If you're new, start
with [quick-start.md](./quick-start.md), then come back here.

## Pick your path

| I want to… | Read |
|---|---|
| Install Femtobot and chat with it | [quick-start.md](./quick-start.md) |
| Configure my `config.json` properly | [configuration.md](./configuration.md) |
| Drive Femtobot from a Python script | [python-sdk.md](./python-sdk.md) |
| Expose it as an OpenAI-compatible HTTP service | [openai-api.md](./openai-api.md) |
| Build a custom MCP server and plug it in | [mcp.md](./mcp.md) |
| Stream to my own WebSocket client | [websocket.md](./websocket.md) |
| Run multiple instances side by side | [multiple-instances.md](./multiple-instances.md) |
| Understand the memory system (Consolidator, AutoCompact, Dream) | [memory.md](./memory.md) |
| Understand the runtime internals | [architecture.md](./architecture.md) |
| Know every built-in tool | [tools.md](./tools.md) |
| Use the introspection tool safely | [my-tool.md](./my-tool.md) |
| Deploy to production (Docker, systemd, reverse proxy) | [deployment.md](./deployment.md) |
| Understand the security model | [security.md](./security.md) |
| Fix a problem | [troubleshooting.md](./troubleshooting.md) |
| Browse every CLI flag and slash command | [cli-reference.md](./cli-reference.md) |

## Cross-cutting references

- Repo-level changes and version history: [../CHANGELOG.md](../CHANGELOG.md)
- Contributing conventions: [../CONTRIBUTING.md](../CONTRIBUTING.md)
- Top-level overview: [../README.md](../README.md)

## How these docs are organized

The pages split into three rough layers:

1. **User docs** — [quick-start](./quick-start.md), [configuration](./configuration.md),
   [cli-reference](./cli-reference.md), [tools](./tools.md), [my-tool](./my-tool.md),
   [memory](./memory.md).
2. **Integration docs** — [python-sdk](./python-sdk.md), [openai-api](./openai-api.md),
   [websocket](./websocket.md), [mcp](./mcp.md), [multiple-instances](./multiple-instances.md).
3. **Operational docs** — [architecture](./architecture.md), [security](./security.md),
   [deployment](./deployment.md), [troubleshooting](./troubleshooting.md).

Each page cross-links to related pages in the same layer and to the
prerequisite pages below it.

## Conventions used in these docs

- Code blocks are runnable unless explicitly marked `# pseudocode`.
- "Default" always means the Pydantic schema default — see
  [configuration.md](./configuration.md) for the source of truth.
- "Provider" always means a registered LLM provider (33 today).
- "Tool" always means a registered Femtobot tool (13 native + MCP-wrapped).
- "Channel" always means an external transport (only `websocket` today).
- Square-bracket links `[label](path)` use relative paths from the current
  file. If you rename a file, grep for the path first — there are many
  cross-links.

## Where to report a bug

<https://github.com/bill-kopp-ai-dev/femtobot/issues>. Include the output of
`femtobot --version` and `femtobot --verbose` for the failing command. See
[troubleshooting.md](./troubleshooting.md#reporting-a-bug) for the format.