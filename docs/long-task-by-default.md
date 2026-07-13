# Long Task by Default — Guide

> **Audience:** femtobot operators integrating the worker as part of an
> Orchestrator-Worker architecture where `nanobot` (or another agent)
> supervises one or more femtobot instances.

This guide explains what changed in femtobot 0.1.9 to make sustained
goals the default execution mode, how to disable it, and how the
supervisor should talk to the worker.

---

## What is "long task" mode?

Every inbound message to femtobot is now treated as a *sustained goal* —
a durable objective that the worker continues until it explicitly
finishes or hits a guardrail.  This is the same model nanobot uses
internally, but tuned for the worker side of an Orchestrator-Worker
topology:

| Aspect | One-shot mode (legacy) | Long task by default (new) |
|---|---|---|
| `by_default` config | implicit `false` | `true` |
| Inbound handling | single agent turn | wraps inbound as goal, runs to closure |
| Runner timeout | `FEMTOBOT_LLM_TIMEOUT_S` | disabled (`0.0`) while goal active |
| Goal-aware tools | hidden | visible (`long_task`, `complete_goal`) |
| Continuation across budget boundary | only via bus queue | also via SDK/API ephemeral queue |
| `/goal` slash command | boots goal via prompt hint | writes the blob directly |

The legacy one-shot behavior is **100% preserved** — flip
`agents.defaults.longTask.byDefault` to `false` to disable long task
mode entirely.

---

## Quick start

```json
{
  "agents": {
    "defaults": {
      "longTask": {
        "byDefault": true,
        "maxGoalRounds": 12,
        "maxGoalRuntimeS": 14400,
        "maxGoalAskAttempts": 3,
        "sdkExecutionMode": "goal_aware",
        "apiMode": "auto"
      }
    }
  }
}
```

When the file at `~/.femtobot/config.json` carries this block,
femtobot treats every inbound as a goal.  To turn the feature off:

```json
{ "agents": { "defaults": { "longTask": { "byDefault": false } } } }
```

---

## Slash commands

The `/goal` family was extended with three new commands:

| Command | Effect |
|---|---|
| `/goal <objective>` | Bootstrap a sustained goal (status=active). |
| `/goal complete [recap]` | Mark the goal complete; one-shot behavior resumes. |
| `/goal cancel [reason]` | Mark the goal cancelled without finishing. |
| `/goal block [reason]` | Mark the goal blocked pending human/orchestrator input. |
| `/goal status` | Print active goal state, elapsed seconds, pending asks. |

All four state-changing commands publish a `GoalStateChanged` event on
the runtime bus so subscribed UI surfaces can update in real time.

---

## Tools available to the LLM

The agent has two new tools with capability tag `long-running`:

### `long_task(objective, ui_summary?)`
Bootstraps or replaces the active sustained goal.  Only visible when
the current turn is allowed to create/replace a goal (i.e. an explicit
`/goal` invocation, or `by_default=true` mode).

### `complete_goal(action, recap?, objective?, ui_summary?)`
Closes the active goal.  Always visible while a goal is active.
Actions:
- `complete` — work finished successfully.
- `cancel` — abandon without finishing.
- `block` — needs human/orchestrator decision.
- `replace` — swap the objective (requires mutation permission).

### `ask_orchestrator(question, options?, timeoutS?, blocking?, target?)`
Blocking call that pauses the goal and surfaces a question to the
supervisor.  See §"Asking the orchestrator" below.

---

## Asking the orchestrator

The `ask_orchestrator` tool is the worker's escape hatch when a
critical decision is required:

```json
{
  "question": "Module X can be migrated to Y or Z. Which one?",
  "options": "Y (faster, breaks compat),Z (slower, keeps compat)",
  "timeoutS": 1800,
  "blocking": true
}
```

Behind the scenes:
1. A `correlation_id` is minted (`ask_…`) and the ask is persisted in
   session metadata under `pending_asks`.
2. The goal is marked `waiting_on="ask_orchestrator"`.
3. An outbound message is published to the configured escalation channel
   (or the current channel when none is set).
4. If `blocking=true`, the agent turn ends; the next inbound on the
   same session that carries the matching `correlation_id` resumes
   the goal.

The orchestrator answers in two ways:

* **HTTP:** `POST /v1/goals/{goal_id}/answer` with
  `{"correlation_id": "ask_…", "response": "go with Y"}`.  The handler
  marks the ask answered in metadata and enqueues a synthetic inbound
  to the same session.
* **Bus / chat:** any inbound that contains
  `metadata.correlation_id` matching a pending ask.  The loop auto-
  resumes the goal with the answer inlined.

If `timeoutS` elapses without a reply, the ask is flipped to `timed_out`
and the goal receives an "ask timed out — use the best hypothesis or
`complete_goal(block)`" continuation message.

---

## API surface (`async_goal`)

The OpenAI-compat API gains four long-task endpoints:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/goals` | Admit a long-task job; returns `202` with `goal_id`, `poll_url`, `events_url`, `answer_url`. |
| `GET`  | `/v1/goals/{goal_id}` | Status snapshot. |
| `GET`  | `/v1/goals/{goal_id}/events` | NDJSON stream of events (`goal_created`, `status_changed`, `ask_pending`, `ask_answered`, `ask_timed_out`, `log`, `final`). |
| `POST` | `/v1/goals/{goal_id}/answer` | Submit an answer for a pending `ask_orchestrator` call. |

`apiMode` governs when the synchronous `POST /v1/chat/completions`
becomes `async_goal`:

- `sync` — never admit; always returns a complete response.  Default.
- `async_goal` — always admit; the response is `202`.
- `auto` — admit when the inbound has `session_id`, an explicit
  `objective`, or there is already an active goal on the session.

In `auto` mode the supervisor can drive the worker entirely through
HTTP without the worker ever blocking on a request thread.

---

## SDK usage

```python
from femtobot import Femtobot

bot = Femtobot.from_config(config)

# Long task by default → goal_aware execution
out = await bot.run("Refactor module X")
# Process completes only after the worker calls complete_goal.

# Explicit one-shot:
out = await bot.run(
    "What's the weather?",
    execution_mode="sync",
)
```

The SDK honors `agents.defaults.longTask.sdkExecutionMode`
(`"goal_aware"` or `"sync"`).  When `by_default=true` the default is
`goal_aware`; otherwise the default is `sync`.

---

## Guardrails

| Risk | Knob | Default | Effect |
|---|---|---|---|
| Infinite iterations | `max_goal_rounds` | 12 | Cap on internal continuation slices. |
| Goal runs forever | `max_goal_runtime_s` | 14400 (4h) | Wall-clock cap per goal. |
| Idle hang | `max_goal_wall_idle_s` | 1800 (30min) | Forced block when the agent stalls. |
| Spam of asks | `max_goal_ask_attempts` | 3 | Per-goal budget for `ask_orchestrator`. |
| Workspace bypass | `workspace_violation_threshold` | 3 | Forces `block` after N violations. |
| Open-ended goal | `require_objective_self_containment` | true | Rejects `/goal`/tool with `?`-shaped objectives. |
| HTTP timeout | `apiMode` | auto | Admit async instead of synchronous. |

When any of these triggers, the worker either blocks (waiting on a
human/orchestrator answer) or completes with a recap.  In both cases a
`GoalStateChanged` event is published with the relevant status
(`blocked`, `cancelled`, `complete`, etc.).

---

## Failure modes and recovery

* **Restart during a goal:** the goal blob lives in
  `session.metadata["goal_state"]`; pending asks live in
  `session.metadata["pending_asks"]`.  Both survive a process restart.
  When the worker restarts, the next inbound on that session resumes
  the goal automatically (or, in `async_goal` mode, the supervisor
  polls `/v1/goals/{goal_id}` to detect "no progress").
* **Ask times out:** the ask is marked `timed_out` and the goal
  receives a continuation nudge.  The agent should either commit a
  hypothesis (calling `complete_goal(complete, recap="…")`) or escalate
  via `complete_goal(block, recap="timed out on ask X")`.
* **Continuous `block` loops:** the supervisor should inspect the
  `/goal status` output to read the `block_reason` and answer via
  `POST /v1/goals/{goal_id}/answer`.  Two unanswered `block`s in a row
  is a strong signal that the objective itself is wrong — consider
  `complete_goal(replace, objective=…)` or `cancel`.

---

## Observability

Every transition publishes a `GoalStateChanged` event on the runtime
bus with the full session metadata snapshot.  Subscribe from any
process-local handler:

```python
from femtobot.bus.runtime_events import GoalStateChanged, RuntimeEventBus

bus = RuntimeEventBus()

async def on_goal(event: GoalStateChanged) -> None:
    goal = event.session_metadata.get("goal_state", {})
    print(goal.get("status"), goal.get("objective"))

bus.subscribe(on_goal, GoalStateChanged)
```

The HTTP `/events` endpoint mirrors the same stream as NDJSON,
suitable for piping into a log aggregator or a UI dashboard.

---

## Migration checklist

1. Add the `longTask` block to `~/.femtobot/config.json` (snippet
   above).
2. Restart femtobot.  Run `/help` and verify `/goal status`,
   `/goal cancel`, `/goal block`, `/goal complete` are listed.
3. Send a trivial message ("hi").  Expect a goal to be bootstrapped
   implicitly and the agent to call `complete_goal(action="complete",
   recap="…")` quickly.  Use `/goal status` to confirm.
4. From your supervisor, send `POST /v1/goals` with
   `session_id=worker-1` and an `objective`.  Confirm you get `202`
   with a `goal_id`.  Poll `/v1/goals/{goal_id}` until status is
   terminal.
5. (Optional) Flip `by_default` to `false` and verify the legacy
   one-shot behavior is restored (existing tests should continue to
   pass byte-a-byte).

When all five steps succeed, the worker is ready for production
deployment behind `nanobot` or any other orchestrator.