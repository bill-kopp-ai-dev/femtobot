# Quick Start

Welcome to femtobot! For more detailed overview information, please check the main [README.md](../README.md).

## Installation

> **Note:** The package name on PyPI and the source repository are both `femtobot` /
> `bill-kopp-ai-dev/femtobot`. Earlier revisions of this guide referenced
> `femtobot-ai` and `HKUDS/femtobot` — those were placeholders and will not
> resolve to a working install.

**Install with uv (Recommended, isolated CLI tool):**
```bash
uv tool install femtobot
```

**Install with pip (user site):**
```bash
pip install --user femtobot
```

**Install from source (recommended for development):**
```bash
git clone https://github.com/bill-kopp-ai-dev/femtobot.git
cd femtobot
uv sync
```

After installing from source, prefer `uv run femtobot …` so the local checkout is used
verbatim (no need to reinstall after every edit):

```bash
uv run femtobot --version
```

## Your First Run

**1. Initialize the instance**

Set up your default configuration and workspace. The first run creates
`.femtobot/config.json` plus `workspace/` next to the current working directory:

```bash
femtobot onboard
```

If you cloned the source and want to run against the local checkout, prefix every
command with `uv run` (`uv run femtobot onboard`).

**2. Set your API key**

The generated `config.json` ships with `apiKey: null` for every provider. Pick one
provider, set its `apiKey` (and `apiBase` if it's a regional gateway), and make
sure `agents.defaults.provider` matches:

```json
{
  "agents": { "defaults": { "provider": "openrouter", "model": "anthropic/claude-3.5-sonnet" } },
  "providers": {
    "openrouter": { "apiKey": "sk-or-...", "apiBase": "https://openrouter.ai/api/v1" }
  }
}
```

See [configuration.md](./configuration.md) for the full schema and the list of
33 registered providers.

**3. Chat with the agent**

Start an interactive chat session:

```bash
femtobot agent
```

Or send a single message directly:

```bash
femtobot agent -m "Hello femtobot!"
```

That's it! You have a working CLI-first AI agent.

## Where to go next

- [configuration.md](./configuration.md) — full `config.json` reference
- [cli-reference.md](./cli-reference.md) — every command and flag
- [multiple-instances.md](./multiple-instances.md) — run `.femtobot`,
  `.femtobot_dev`, `.femtobot_billing` in parallel
- [openai-api.md](./openai-api.md) — `femtobot serve` exposes an OpenAI-compatible
  endpoint for A2A and local integrations
- [websocket.md](./websocket.md) — the `websocket` channel for custom clients
- [mcp.md](./mcp.md) — wiring Model Context Protocol servers into the agent
- [troubleshooting.md](./troubleshooting.md) — common pitfalls (MCP args dropping,
  websocket 401, provider auth, etc.)