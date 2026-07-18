# Migration from 0.1.x to 1.0

> **Status:** Phase 8 hardening. Valid as of commit `504bd49` (Fase 5).
> Update this document as each subsequent phase lands.

## TL;DR

- `config.json` is auto-migrated. Nothing changes on disk.
- The CLI surface is unchanged (same subcommands and flags).
- A new PydanticAI-based `FemtobotAgent` coexists with the legacy
  `AgentLoop`. The legacy loop is still the production path; the new
  adapter is opt-in for early adopters.
- Observability via Logfire is **opt-in**: set `FEMTOBOT_LOGFIRE=1` to
  enable (or `FEMTOBOT_LOGFIRE_SEND=no` + an OTel collector endpoint
  for self-hosted).

## What changed

### Phase 0 (commit `0a5fa79`)
- Added `pydantic-ai>=1.0,<2.0` and `logfire>=3.14.1,<4.0` to
  `pyproject.toml`.
- New `femtobot/observability/logfire_setup.py` with opt-in configure
  and instrument helpers.
- Fixed lazy-loading of `femtobot.*` submodules in `femtobot/__init__.py`.

### Phase 1 (commit `dbf727c`)
- New `femtobot/agent/deps.py` (`FemtobotDeps` dataclass for PydanticAI
  tool context).
- New `femtobot/agent/output.py` (`FemtobotOutput` typed response model
  with `final_message`, `iterations_used`, `completed_goal`).
- New `femtobot/agent/femtobot_agent.py` (`FemtobotAgent` factory +
  `_build_model` + `build_system_prompt`).
- New `femtobot/agent/toolsets/femtobot_timer.py` — pilot migration of
  the legacy `FemtobotTimerTool` to a PydanticAI `Tool`.

### Phase 2 (commit `8592cc1`)
- Removed isolated parity layer files with no external callers:
  `cli/suggestion.py`, `cli/mouse.py`, `cli/fullscreen.py`,
  `cli/transcript.py`, `cli/virtual_transcript.py`, `cli/voice.py`
  (plus their tests).
- **Kept** (would cascade): `cli/parity_stream.py`,
  `cli/parity_widgets.py`, `cli/textual_app.py`, `cli/keybindings.py`,
  `cli/renderer_factory.py`, `cli/whimsy.py`, `cli/status_line.py`,
  `cli/plugins/*`. These are still wired into the parity REPL flow.

### Phase 3 (commit `5af3dca`)
- New `femtobot/agent/toolsets/_combined.py` aggregator:
  `combined_toolset(config)` returns every migrated toolset.
- New `FemtobotAgent.from_config()` classmethod.
- New `FemtobotAgent(use_combined_toolset=True)` opt-in.

### Phase 4 (commit `7ffcb53`)
- New `femtobot/agent/runner_helpers.py` with
  `persist_tool_result`, `post_run_autocompact`, `post_run_session_save`.
- **Kept** `agent/loop.py` (2179 LOC) and `agent/runner.py` (1895 LOC)
  — full replacement deferred to a dedicated hard-refactor branch.

### Phase 5 (commit `504bd49`)
- `_build_model()` now dispatches to all four native PydanticAI
  provider classes: OpenAI, Anthropic, Bedrock, Gemini.
- Missing optional SDKs surface as actionable `RuntimeError`s.

### Phase 6 (commit `891dbc0`)
- New `logfire_setup.instrument_httpx()` (opt-in via
  `FEMTOBOT_LOGFIRE_HTTPX=1`).
- New `docs/observability.md`.
- New `tests/observability/test_logfire_setup.py`.

## Breaking changes

### CLI

**None in this branch.** The legacy `femtobot cli/commands.py` is
still the production CLI entry point. The parity / Claude-Style UI
remains available under `agents.defaults.cli.ui_parity.profile = "compat"`.

### Providers

**None.** The legacy `providers/*.py` modules are untouched. The new
`_build_model()` is only invoked by `FemtobotAgent` (opt-in).

### Observability

**None.** Logfire is opt-in; existing loguru logs continue to be
written to stderr.

### Tool API

**None.** Legacy `Tool` ABC and `ToolRegistry` are untouched. The new
PydanticAI toolsets under `femtobot/agent/toolsets/` are additive.

## Deprecations

Nothing deprecated yet. The plan reserves the following for future
phases:
- `cli/parity_stream.py`, `cli/textual_app.py` (Camada de paridade
  removida em release futura).
- `providers/openai_compat_provider.py` (replaced by OpenAIModel com
  custom base_url).
- `agent/loop.py` / `agent/runner.py` (replaced by FemtobotAgent).

## Auto-migration

`config.json` is loaded by `load_config()` unchanged. No deprecation
warnings emitted yet.

## Upgrading

```bash
uv sync
uv run femtobot --version     # should still print 0.1.0a0+ui0
uv run femtobot status        # confirms provider wiring still works
```

To try the new PydanticAI adapter:

```python
from femtobot.agent.femtobot_agent import FemtobotAgent
from femtobot.agent.deps import FemtobotDeps
from pathlib import Path

cfg = ...  # your loaded Config
deps = FemtobotDeps(config=cfg, workspace=Path("/path/to/workspace"))
agent = FemtobotAgent(cfg, Path("/path/to/workspace"))
result = await agent.run("Hello", deps=deps)
print(result.final_message)
```

To enable Logfire:

```bash
FEMTOBOT_LOGFIRE=1 uv run logfire auth
FEMTOBOT_LOGFIRE=1 uv run femtobot agent
```
