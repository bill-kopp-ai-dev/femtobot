# Implementation Plan: `nano_timer` Tool (Femtobot port)

**Created:** 2026-07-10
**Project:** v0.1.6 — Nanobot parity feature add
**Reference document:** `IMPLEMENTATION_nano_timer_tool_20260622.md` (nanobot
implementation as written by nanobot on 2026-06-22) +
`/home/bill/Codes/agents/nanobot/nanobot/agent/tools/time.py` (current
upstream implementation, evolved since the original plan).
**Status:** Awaiting user approval to execute.

---

## 📋 Overview

This document is the Femtobot-optimized port of the `nano_timer` core
tool.  The goal is the same as nanobot's: give the agent runtime
access to accurate time, timezone, and calendar information without
relying on the LLM to estimate UTC offsets — critical for any
time-sensitive operation (scheduling, cron, debouncing, audit
records, "in 5 minutes" requests).

Femtobot is a simplified subset of nanobot — it has **no cron, no
heartbeat, no scheduled agents**.  Those features drive some of
nanobot's `nano_timer` design choices.  This port strips the parts
nanobot added for those subsystems and keeps only what Femtobot's
runtime actually consumes.

---

## 🎯 Differences from the nanobot implementation

### Femtobot already has the runtime plumbing

The Femtobot runtime already provides what `nano_timer` needs:

| Required asset | Femtobot equivalent | Reference |
|----------------|----------------------|-----------|
| `ToolContext.timezone` | `ToolContext.timezone: str = "UTC"` | [agent/tools/context.py:42](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/context.py#L42) |
| `agent_defaults.timezone` | `AgentDefaults.timezone: str = "UTC"` (line 446 of [config/schema.py](file:///home/bill/Codes/agents/femtobot/femtobot/config/schema.py#L418)) | already exists, default `"UTC"` |
| `ToolLoader` auto-discovery | `ToolLoader.discover()` scans `femtobot.agent.tools.*` skipping `_SKIP_MODULES` — `time` is not in the skip list so a `time.py` is auto-discovered | [agent/tools/loader.py:21-31](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/loader.py#L21-L31) |
| `ToolsConfig` extends | One line: `timer: TimerToolConfig = Field(...)` next to `web`, `exec`, `my` | [config/schema.py:619-644](file:///home/bill/Codes/agents/femtobot/femtobot/config/schema.py#L619-L644) |

The port is therefore much shorter than nanobot's plan: **no config
loader surgery, no `AGENTS.md` config-section addition, no manual
plugin registration**.

### Femtobot does not have these nanobot-specific subscribers

`nano_timer` in nanobot carries two pieces that Femtobot does not
need:

1. **`channel` / `chat_id` request context recording** — `set_context`
   in nanobot's tool records who asked.  Femtobot's `RequestContext`
   *also* has these fields, and `ContextAware` protocol exists in
   both.  We keep the `set_context` hook (it is a one-liner) for
   parity, but we never use the values; if a future audit wants to
   log "the webhook channel that triggered the time question", the
   data is there.
2. **Renderer fallback warning with the raw bad tz string** — nanobot
   preserves the user's bad timezone input in a footer so the LLM
   sees why the fallback fired.  We keep this verbatim: it makes the
   tool *self-documenting* to the model.

### Strict scoping relative to the upstream document

The nanobot implementation document (`IMPLEMENTATION_nano_timer_tool_20260622.md`)
includes steps that **do not apply** to Femtobot:

| Step | Femtobot applicability |
|------|------------------------|
| Step 5 — update `config.json` with `user.timezone` | Not applicable — Femtobot's config schema already has `AgentDefaults.timezone` (line 446); `user.timezone` is a **nanobot-specific** namespace key that Femtobot has not adopted.  Users put `tools.timer.timezone` (or rely on the existing `agents.defaults.timezone`). |
| Step 4 — add an `AGENTS.md` config-block | Optional.  Femtobot's `AGENTS.md` is workspace-local and already documents runtime.  If the user wants an `nano_timer_config` knob (`auto`/`always`/`never`) like nanobot, it is a **separate**, larger feature that is out of scope here.  We add a one-line description next to the existing tool mentions (à la `## MCP Servers in this workspace`), not a full auto-call gate. |
| Step 6 — `loader.py` import | Not needed — `ToolLoader._SKIP_MODULES` does not list `time`, so `time.py` is auto-discovered. |
| Step 2 — "Alternative manual registration" | Not needed — same reason. |
| Step 4 `nano_timer_config` knob | **Out of scope.** Femtobot's tool system does not yet have an "auto-call before X" gate; the upstream `nano_timer_config` knob is a nanobot-specific feature that depends on a system Femtobot does not have.  We add the tool, not the gate.  Future enhancement: a `tool_hints.py` / `tool_force_call_pattern` field could port the gate later. |

---

## 🔧 Implementation Steps

### Step 1 — Create `femtobot/agent/tools/time.py`

Mirror nanobot's `time.py` (current upstream, evolved since the
2026-06-22 plan — smaller and cleaner than the plan's first draft)
**with the Femtobot-specific adaptations**:

- Use the Femtobot tool-class template (subclasses `Tool,
  ContextAware` like `WebSearchTool` does), not the nanobot
  `@tool_parameters` decorator style which is structurally similar
  but Femtobot has its own helpers.  Look at `agent/tools/web.py`
  for the closest analog.
- Skip `_plugin_discoverable = False`; we want auto-discovery.
- `config_key = "timer"` and a `TimerToolConfig(Base)` model.
- `create(ctx)` reads `ctx.timezone` (the already-injected
  `ToolContext.timezone`) and `ctx.config.timer.timezone_override`
  (optional).
- Drop the nanobot-flavoured messages — let Femtobot's `i18n`
  (Portuguese weekday names) come from the same lookup helper.
- Keep `_resolve_server_tz()` and `_format_offset()` as private
  helpers; the helper `tzinfo.key` path is more correct than the
  nanobot plan's plain `tzname()` call (the plan was written before
  nanobot learned about the `TZ=Asia/Tokyo` POSIX edge case).

The file is approximately **180 lines**.  Full sketch:

```python
"""Time awareness tool — current UTC, user local time, IANA timezone, calendar."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from femtobot.agent.tools.base import Tool, tool_parameters
from femtobot.agent.tools.context import ContextAware, RequestContext
from femtobot.agent.tools.schema import StringSchema, tool_parameters_schema
from femtobot.config.schema import Base

# Match the nanobot parameters schema (with the nullable=True variant
# Femtobot's StringSchema already supports).
_TIMER_PARAMETERS = tool_parameters_schema(
    info_type=StringSchema(
        "What information to return: 'time' | 'timezone' | 'location' | 'calendar' | 'all'.",
        enum=("time", "timezone", "location", "calendar", "all"),
        nullable=True,
    ),
    description=(
        "Selects the section of the time report. Defaults to 'all' when null or unknown."
    ),
)


class TimerToolConfig(Base):
    """Configuration for the nano_timer tool."""
    enable: bool = True
    # Optional per-workspace override of the agent timezone for the
    # tool.  When unset we fall back to ``ctx.timezone`` (which the
    # loop populates from ``agents.defaults.timezone``).
    timezone_override: str | None = None


def _resolve_server_tz() -> tuple[str, str]: ...   # verbatin port
def _format_offset(offset: Any) -> str: ...         # verbatin port


@tool_parameters(_TIMER_PARAMETERS)
class NanoTimerTool(Tool, ContextAware):
    """Provide accurate time, timezone, and calendar information..."""

    config_key = "timer"

    @classmethod
    def config_cls(cls):
        return TimerToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.timer.enable

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        tz_override = getattr(ctx.config.timer, "timezone_override", None)
        return cls(timezone=tz_override or ctx.timezone)

    def __init__(self, timezone: str = "UTC"):
        self._timezone = timezone
        self._tz_fallback_name: str | None = None
        self._channel: str = ""
        self._chat_id: str = ""

    def set_context(self, ctx: RequestContext) -> None:
        self._channel = ctx.channel
        self._chat_id = ctx.chat_id

    @property
    def name(self) -> str:
        return "nano_timer"

    @property
    def description(self) -> str:
        return (
            "Returns accurate time, timezone, and calendar information using IANA "
            "timezone with automatic DST handling. Call this before scheduling, "
            "cron jobs, reminders, or any time-sensitive operation where wrong "
            "time would cause harm. Also useful when the user asks about current "
            "time, date, or timezone, or when converting/comparing times across zones."
        )

    def _compute_payload(self) -> dict[str, Any]: ...   # verbatin port of nanobot
    def _format(self, info_type: str, payload: dict[str, Any]) -> str: ...
    async def execute(self, info_type: str | None = "all", **kwargs: Any) -> str: ...
```

> **Note on naming:** keep the public class name as `NanoTimerTool`
> and the tool name `nano_timer`.  Both names are already referenced
> in nanobot + future Femtobot users may have muscle memory.  The
> file lives under `femtobot/agent/tools/time.py` to match nanobot's
> layout (no `timer.py` divergence).

### Step 2 — Register in `ToolsConfig`

**File:** `femtobot/config/schema.py`

Two surgical edits:

1. Forward-import for lazy resolution (around line 838 — paired with
   `model_rebuild`):

```python
from femtobot.agent.tools.time import TimerToolConfig
```

2. Add the field to `ToolsConfig` (around line 627, beside `web` /
   `exec` / `my`):

```python
timer: TimerToolConfig = Field(
    default_factory=lambda: _lazy_default("femtobot.agent.tools.time", "TimerToolConfig")
)
```

That single-line addition is all the runtime config plumbing
nanobot's plan covers in **Steps 2, 5, and 6** combined.

### Step 3 — Re-export in `agent/tools/__init__.py` (optional)

Not strictly necessary — `ToolLoader.discover()` walks the package
and finds `NanoTimerTool` automatically.  But because
`MyTool` exists in the same `__init__.py` exposure pattern, we add a
parallel re-export for grep / IDE convenience:

```python
from femtobot.agent.tools.time import NanoTimerTool
```

### Step 4 — Add a one-paragraph `AGENTS.md` section

**File:** `femtobot/templates/AGENTS.md` (template)
**File:** the live workspace copy at `~/.femtobot/workspace/AGENTS.md`

Add under "MCP-Aware Operating Rules" → just below the timezone hint:

```markdown
## Time, Date, and Calendar

If you need to know the current time, timezone offset, or calendar
information, call the `nano_timer` tool.  Do not estimate UTC offsets
from training data: timezone rules change and DST shifts vary by
jurisdiction.  Use `nano_timer(info_type="time")` for a quick "what
time is it" and `nano_timer(info_type="all")` for the full report.
```

This is much shorter than nanobot's 25-line `nano_timer_config`
table.  Femtobot does not have an auto-call gate, so the section
describes the manual-call expectation only.

### Step 5 — Tests (parallel to nanobot's Test Plan)

Three test files / sections:

* `tests/test_timer_tool.py` (new, 12-15 tests):
  - `test_returns_utc_and_user_local_time`
  - `test_info_type_all_renders_full_payload`
  - `test_info_type_time_minimal_payload`
  - `test_info_type_calendar_includes_weekday_and_day_of_year`
  - `test_info_type_timezone_includes_offset_str`
  - `test_invalid_timezone_falls_back_to_utc_with_warning`
  - `test_empty_timezone_falls_back_to_utc_with_warning`
  - `test_offset_formats_partial_hours_india_nepal_chatham`
  - `test_offset_format_whole_hour_compact_utc_minus_three`
  - `test_server_local_label_when_no_iana_tzdata`
  - `test_set_context_records_channel_and_chat_id`
  - `test_execute_unknown_info_type_defaults_to_all`
  - `test_execute_robust_to_compute_payload_failure`

* Extend `tests/test_dream_parity.py` style smoke check:
  - `test_nano_timer_appears_in_tool_loader_scan()` — verifies
    the loader's auto-discovery picked up the new module and the
    openai-style `parameters` JSON schema is well-formed.

* Update `tests/test_agents_template_mcp.py` if the AGENTS.md
  change breaks a fixture (the "mentions of MCP-aware rules"
  tests).  Should be a one-line addition.

### Step 6 — Config surface check

To confirm the new tool runs end-to-end without surprising existing
config files, generate a fresh `~/.femtobot/config.json` template and
verify it parses:

* `femtobot config print-default | jq .tools.timer.enable` →
  expect `true`.
* `femtobot tools list | grep nano_timer` → expect the tool to
  appear.

---

## 🧪 Validation Plan

### Static checks
- `uv run ruff check .` → All checks passed.
- `uv run mypy femtobot/agent/tools/time.py` (if mypy is in dev
  deps; otherwise skip) — keep type annotations aligned with
  nanobot's source.

### Behavior tests
- New `tests/test_timer_tool.py` — 12-15 tests (Step 5).
- Full suite: `uv run pytest tests/` — must continue to pass.

### Smoke tests
- `femtobot agent --message "what time is it?"` — should call
  `nano_timer` and return the user-local time.
- `femtobot agent --message "schedule X for tomorrow at 10am"` —
  should use `nano_timer` to anchor the request to real time.

### Round-trip checks
- `pydantic-settings` round-trip for `TimerToolConfig(enable=False)`
  — verify the field is recognized and serialized.

---

## 📋 Checklist

| Step | Task | Owner | Status |
|------|------|-------|--------|
| 1 | Create `femtobot/agent/tools/time.py` with `NanoTimerTool` + 2 helpers | @claude | ⬜ pending approval |
| 2 | Add `TimerToolConfig` to `ToolsConfig` and the lazy-import hook | @claude | ⬜ pending approval |
| 3 | Re-export `NanoTimerTool` in `agent/tools/__init__.py` | @claude | ⬜ pending approval |
| 4 | Add AGENTS.md section (template + live workspace) | @claude | ⬜ pending approval |
| 5 | Write `tests/test_timer_tool.py` + 1 cross-file test | @claude | ⬜ pending approval |
| 6 | `ruff + pytest + smoke test` | @claude | ⬜ pending approval |
| 7 | Bump version (`v0.1.5 → v0.1.6`), CHANGELOG, README, push | @claude | ⬜ pending approval |

---

## 🚦 Migration risk and compat

* **API compat:** `v0.1.6` is the first version where `NanoTimerTool`
  exists.  Adding a tool is purely additive; existing tool sets and
  prompts are unaffected.
* **Config compat:** adding a `tools.timer` field to `ToolsConfig`
  means a fresh `config.json` write will include the new key.
  Existing saved configs that lack the key will default to
  `enable=True`, `timezone_override=None`.  Both safe defaults.
* **Prompt compat:** adding one short paragraph to the AGENTS.md
  template costs ~5 user-tokens per turn.  Acceptable.

---

## 🤔 Open questions for the user

1. **Tool name:** keep `nano_timer` (matches nanobot, has muscle
   memory for users coming from nanobot) or rename to `femtobot_timer`
   (consistent with the project name)?

2. **Config knob parity:** nanobot has `nano_timer_config: "auto" |
   "always" | "never"` in AGENTS.md that toggles whether the tool
   is auto-called before scheduled operations.  Femtobot's runtime
   does not have an auto-call gate yet.  Should we:

   * (a) port **only** the tool (small, this plan as written) — the
     knob can be added later if/when an auto-call gate lands;
   * (b) port the tool **and** add a `_auto_call_in` list field to
     `TimerToolConfig` (a small additive guardrail, no full gate);
   * (c) port the tool **and** go all the way and port the
     nanobot `nano_timer_config` knob (larger — needs a way to
     influence prompts from AGENTS.md).

   Default recommendation: **(a)** — keep this PR focused.

3. **i18n:** the original plan's `_WEEKDAY_NAMES_PT` is held over
   verbatim from the first implementation.  Femtobot's CLI does
   not have an i18n subsystem yet.  Should we keep `pt` weekday
   names as a hard-coded complement (matches nanobot's behaviour
   on en-US + pt-BR workspaces), or drop them to `en` only?

   Default recommendation: **keep pt** to match nanobot + Bill's
   `user.location` is `Lindóia-SP`.
