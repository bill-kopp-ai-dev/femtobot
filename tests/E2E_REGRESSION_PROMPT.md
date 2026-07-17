# E2E Regression Prompt — longlogs remediation

This file is the human-readable narrative for the automated E2E smoke
(`tests/e2e_regression_prompt.py`) that runs in CI nightly.

## Scenario

Reproduce the conditions that triggered the original `longlogs.txt`
captures:

1. Workspace has no `mcp_servers` configured (`tools.mcp_servers = {}`).
2. `AGENTS.md` references `mcp_percival-osm_*` tools but the binary
   (`percival-osm-mcp`) is not installed.
3. User asks the agent to run 8 resilience tests (E1–E8) against
   `percival-osm`.
4. `agents.defaults.tool_use_guard.enabled = True`.

## Expected behaviour (after the remediation plan)

- **First response** lists the tools the agent actually has (local +
  empty MCP set). Source: PR 5.2 (`## Tools available right now`).
- The agent explicitly states "MCP server `percival-osm` is not
  configured; add it to `.femtobot/config.json` under
  `tools.mcp_servers`". Source: PR 1.1, 1.2.
- If the agent answers with a plan ("Opção 1...", "Vou fazer..."),
  the `ToolUseGuardHook` (PR 5.3) injects a one-shot nudge asking
  for an explicit tool call or concrete blocker reason.
- **Runtime metric** `tool_use_guard_triggered` is published on the
  `RuntimeEventBus`. Source: PR 7.1.

## Failure conditions (the test fails if…)

- The agent does not list "Tools available right now" in its first
  response → regression of PR 5.2.
- The agent answers with a plan AND does not emit the
  `tool_use_guard_triggered` metric within 2 turns → regression of
  PR 5.3 + PR 7.1.
- The `/mcp status` slash command does not show the
  "referenced but not configured" line → regression of PR 1.1.

## How to run

```bash
# Headless smoke (no API key required)
pytest -m e2e tests/e2e_regression_prompt.py

# Nightly job (full provider call)
FEMTOBOT_E2E_PROVIDER=openai pytest -m e2e tests/e2e_regression_prompt.py
```

The headless smoke mocks the provider and only exercises the
AgentLoop scaffolding; the nightly job hits the real LLM.
