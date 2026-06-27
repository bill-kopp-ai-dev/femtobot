# Changelog

All notable changes to Femtobot will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Pre-1.0 (i.e., all current versions) treats breaking changes as minor bumps
> and minor changes as patches. The first 1.0 release will lock the API.

## [Unreleased]

### Added
- Documentation overhaul:
  - [docs/configuration.md](docs/configuration.md) now covers every field of
    `config.json` (60+ knobs across agents, channels, providers, api, gateway,
    tools, model presets).
  - [docs/python-sdk.md](docs/python-sdk.md) shows the in-process
    `Femtobot.from_config()` API alongside the OpenAI-server and CLI paths.
  - [docs/cli-reference.md](docs/cli-reference.md) documents every
    subcommand, every flag, and every slash command.
  - [docs/websocket.md](docs/websocket.md) covers the full schema and warns
    about the `websocketRequiresToken` default trap.
  - [docs/memory.md](docs/memory.md) explains the three-layer memory model,
    the Consolidator → AutoCompact → Dream pipeline, and every config knob.
  - [docs/openai-api.md](docs/openai-api.md) adds streaming, session
    semantics, and the no-auth caveat.
  - [docs/deployment.md](docs/deployment.md) gets a working systemd unit
    with a real `ExecStart` path, a supervisord alternative, a caddy/nginx
    reverse-proxy example, and health-check guidance.
  - [docs/my-tool.md](docs/my-tool.md) documents the `modify` action, the
    BLOCKED/READ_ONLY/`_SENSITIVE_NAMES`/`_DENIED_ATTRS` protection layers.
  - New docs: [architecture.md](docs/architecture.md),
    [tools.md](docs/tools.md), [security.md](docs/security.md),
    [troubleshooting.md](docs/troubleshooting.md), [mcp.md](docs/mcp.md).
  - Root-level [CHANGELOG.md](CHANGELOG.md) and
    [CONTRIBUTING.md](CONTRIBUTING.md).

### Fixed
- `docs/quick-start.md` install commands: `uv tool install femtobot-ai` →
  `uv tool install femtobot`; `git clone HKUDS/femtobot` →
  `git clone bill-kopp-ai-dev/femtobot`.
- `docs/websocket.md` example no longer ships a config that produces 401 on
  every connection (the `websocketRequiresToken: true` + empty token trap).
- `docs/deployment.md` systemd `ExecStart` no longer points at the
  non-existent `/path/to/femtobot` placeholder.
- `docs/python-sdk.md` no longer claims the Python API is "wait for stable
  release" — `Femtobot.from_config()` has been working since v0.0.2.

## [0.0.2] — 2025-11-XX

Initial public alpha.

### Added
- Core CLI commands: `onboard`, `status`, `agent`, `serve`, `gateway`.
- OpenAI-compatible HTTP surface under `femtobot serve`.
- WebSocket channel (`femtobot.channels.websocket`).
- 33 registered LLM providers.
- 13 native tools (filesystem, search, shell, web, self, message).
- MCP client integration with stdio and HTTP transports.
- Three-layer memory model: session messages → `history.jsonl` →
  Git-backed `MEMORY.md`/`USER.md`/`SOUL.md`, with the Consolidator, the
  AutoCompact idle compaction, and the periodic Dream job.
- Multiple-instance support via `--suffix` / `--folder-path` /
  `FEMTOBOT_HOME`.

[Unreleased]: https://github.com/bill-kopp-ai-dev/femtobot/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/bill-kopp-ai-dev/femtobot/releases/tag/v0.0.2