# Contributing to Femtobot

Thanks for your interest in Femtobot! The project is small and personal; the
bar to contributing is low, but a few conventions help keep the codebase
consistent.

## Code of Conduct

By participating, you agree to abide by the spirit of the
[Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/):
be kind, assume good faith, focus on the work.

## Reporting bugs

Open an issue at <https://github.com/bill-kopp-ai-dev/femtobot/issues>.

A good bug report includes:

- The failing command (`femtobot agent -m "..."`).
- The Femtobot version (`femtobot --version`).
- The relevant section of `config.json` (redact secrets).
- Verbose logs (`femtobot --verbose`).
- Expected vs. actual behavior.

Before opening, scan [troubleshooting.md](docs/troubleshooting.md) — the most
common failure modes are already documented.

## Suggesting features

Open an issue with the `enhancement` label. Include:

- The problem you're trying to solve (not just the solution).
- A sketch of the API you'd want.
- Whether it can live as a third-party MCP server instead of being added to
  the core (often the answer is yes — see [docs/mcp.md](docs/mcp.md)).

## Development setup

```bash
git clone https://github.com/bill-kopp-ai-dev/femtobot.git
cd femtobot
uv sync
uv run femtobot --version
```

The project uses:

- **Python 3.11+** (see `pyproject.toml` for the exact floor).
- **uv** for dependency management and tool invocation.
- **Pydantic v2** for config and tool schemas.
- **FastMCP** (optional) for writing MCP servers.

## Layout

```
femtobot/
├── femtobot/
│   ├── agent/                  # AgentLoop, tools, memory
│   ├── channels/               # WebSocket (only channel today)
│   ├── command/                # Slash commands
│   ├── providers/              # 33 registered LLM providers
│   ├── api/                    # OpenAI-compatible HTTP server
│   ├── cli/                    # Typer CLI
│   ├── config/                 # Config loader + Pydantic schema
│   ├── femtobot.py             # Public Femtobot facade (SDK)
│   └── gateway/                # Headless gateway placeholder
├── docs/                       # All documentation
├── pyproject.toml
└── tests/                      # pytest
```

See [docs/architecture.md](docs/architecture.md) for the runtime data flow.

## Coding conventions

- **Type hints everywhere.** New code uses Python 3.11+ syntax (`X | None`,
  `list[X]`, not `Optional` / `List`).
- **Pydantic over dataclasses.** If a type holds structured data with
  validation, it's a `BaseModel`. Dataclasses are for internal
  value-object pipelines.
- **No untyped dicts at API boundaries.** Tool args, config values, and
  provider responses get a Pydantic model or a TypedDict.
- **Async I/O throughout.** Use `httpx.AsyncClient`, `aiofiles`, etc. No
  blocking I/O in agent-loop paths.
- **`loguru` for logging.** No `print()` in production code.
- **Tests next to behavior.** Unit tests live in `tests/`; the structure
  mirrors `femtobot/`.

## Commit messages

Conventional Commits, lower-case:

```
feat: add --config flag to femtobot serve
fix: websocketRequiresToken default rejects all connections
docs: expand configuration.md with dream block
refactor: split MessageBus into per-session locks
chore: bump fastmcp to 3.4.2
```

Scope is optional. Break unrelated changes into separate commits.

## Pull requests

1. Branch from `main`: `git checkout -b feat/your-thing`.
2. Make the change.
3. Add or update tests under `tests/`.
4. Update docs if the change is user-visible.
5. Run `uv run pytest` locally.
6. Run `uv run ruff check .` and `uv run ruff format .` (or the configured
   equivalent).
7. Open the PR with a one-paragraph summary and a screenshot / log excerpt
   for behavior changes.

The project uses squash-merge. PR titles become commit messages; keep them
in the Conventional Commits format above.

## Adding a tool

See [docs/tools.md](docs/tools.md#adding-a-new-tool). Quick recipe:

```python
# femtobot/agent/tools/my_tool.py
from femtobot.agent.tools.base import Tool

class MyTool(Tool):
    _scopes = {"core"}

    @property
    def name(self) -> str: return "my_tool"

    @property
    def description(self) -> str: return "What it does."

    @property
    def parameters(self) -> dict: return {...}

    async def run(self, *, context=None, **kwargs) -> str:
        ...
```

The `ToolLoader` picks it up automatically if `_plugin_discoverable = True`.

## Adding a provider

1. Create `femtobot/providers/my_provider.py` implementing `BaseProvider`.
2. Register it in `femtobot/providers/registry.py`.
3. Add an entry under `ProvidersConfig` in `femtobot/config/schema.py` if
   you want it to be addressable by name (otherwise use `provider: "auto"`).
4. Update [docs/configuration.md](docs/configuration.md#providers).

## Adding a slash command

1. Implement a handler in `femtobot/command/builtin.py`.
2. Register it via the `register_router` mechanism in
   `femtobot/command/router.py`.
3. Document it in [docs/cli-reference.md](docs/cli-reference.md#in-repl-commands-slash-commands).

## License

By contributing, you agree that your contributions will be licensed under the
project's [LICENSE](LICENSE).