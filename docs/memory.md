# Memory in Femtobot

Femtobot's memory is built on a simple belief: memory should feel alive, but it
should not feel chaotic.

Good memory is not a pile of notes. It is a quiet system of attention. It
notices what is worth keeping, lets go of what no longer needs the spotlight,
and turns lived experience into something calm, durable, and useful.

## The Design

Femtobot does not treat memory as one giant file. It separates memory into
**three layers** with three different lifecycles:

| Layer | Where | Lifetime | Purpose |
|---|---|---|---|
| **Session messages** | `sessions/<session_id>.json` | Per session | Living short-term conversation. Bounded by `agents.defaults.maxMessages`. |
| **Compressor archive** | `memory/history.jsonl` | Append-only, GC'd | Compressed past turns summarized by the `Consolidator` and queued for Dream. |
| **Durable knowledge** | `SOUL.md`, `USER.md`, `memory/MEMORY.md` | Persistent (Git-backed) | Voice, user profile, project facts, decisions, durable context. |
| **Git history** | `memory/.git/` | Persistent | Every change to the durable files is a commit. Restorable via `/dream-restore`. |

The boundaries matter: each layer has a different write frequency, a different
storage cost, and a different "blast radius" if it gets corrupted. Session
messages are cheap and disposable; durable files are expensive and precious.

---

## The Flow

Memory moves through Femtobot in two stages, plus an idle-triggered third
stage.

### Stage 1 — Consolidator (per-turn)

Class: [`femtobot/agent/memory.py::Consolidator`](../femtobot/agent/memory.py).

When a conversation grows large enough to pressure the context window, the
`Consolidator` summarizes the oldest safe slice of the conversation and
appends that summary to `memory/history.jsonl`. The summary is plain text with
a stable header so the Dream stage can parse it back out later.

The trigger conditions are token-budget based, derived from
`agents.defaults.contextWindowTokens` minus the `maxTokens` reservation
minus a small safety buffer:

```
budget = contextWindowTokens - maxTokens - _SAFETY_BUFFER
```

When the estimated prompt tokens cross `budget`, the oldest turn range is
folded into a new summary line and pushed to `history.jsonl`.

### Stage 2 — AutoCompact (idle sessions)

Class: [`femtobot/agent/autocompact.py::AutoCompact`](../femtobot/agent/autocompact.py).

If `agents.defaults.sessionTtlMinutes > 0`, sessions that have been idle for
that many minutes get compacted by `AutoCompact.compact_idle_session()`,
which delegates to `Consolidator`. Sessions below the TTL are not touched.

To disable idle compaction, set `sessionTtlMinutes: 0` (the default).

### Stage 3 — Dream (periodic)

Classes: [`femtobot/agent/memory.py::Consolidator.archive`](../femtobot/agent/memory.py)
plus `templates/agent/dream.md`.

`Dream` is the slower, more thoughtful layer. It runs every
`agents.defaults.dream.intervalH` hours (default 2). Each cycle:

1. Reads new entries from `memory/history.jsonl` (consumed via
   `.dream_cursor`).
2. Reads the current `SOUL.md`, `USER.md`, and `memory/MEMORY.md`.
3. Invokes the LLM to make surgical edits to the long-term files — never
   rewriting from scratch, always additive or refining.
4. Commits the changes to `memory/.git/` so they're restorable.
5. Advances `.dream_cursor` so the next cycle sees only newer entries.

### The mental model

Think of the three stages as **short-term → archive → long-term**, mirroring
human memory:

| Human | Femtobot |
|---|---|
| Working memory | Session messages |
| Yesterday's recall | `history.jsonl` |
| Life story | `SOUL.md` / `USER.md` / `MEMORY.md` |
| Dreaming that consolidates memories | Dream cron |

---

## The Files

```
.femtobot/
├── config.json
├── workspace/
│   ├── SOUL.md              # The bot's long-term voice and communication style
│   ├── USER.md              # Stable knowledge about the user
│   ├── AGENTS.md            # Operating instructions for the agent
│   └── memory/
│       ├── MEMORY.md        # Project facts, decisions, durable context
│       ├── history.jsonl    # Append-only history summaries
│       ├── .cursor          # Consolidator write cursor
│       ├── .dream_cursor    # Dream consumption cursor
│       └── .git/            # Version history for long-term memory files
└── sessions/                # Per-session JSONL message logs
```

| File | Owner | Edited by |
|---|---|---|
| `SOUL.md` | User / Dream | Manual edits or Dream consolidation. |
| `USER.md` | User / Dream | Manual edits or Dream consolidation. |
| `MEMORY.md` | Dream (primary), Agent (during turns) | Dream cycles + agent's own appends. |
| `history.jsonl` | `Consolidator` | Append-only. |
| `sessions/*.jsonl` | `AgentLoop` | Per-session message log. |

---

## Commands

Users can inspect and guide memory from inside the REPL (see
[cli-reference.md](./cli-reference.md#in-repl-commands-slash-commands)):

| Command | What it does |
|---|---|
| `/dream` | Run Dream immediately (don't wait for the cron). |
| `/dream-log` | Show the latest Dream memory change (commit diff). |
| `/dream-log <sha>` | Show a specific Dream commit diff. |
| `/dream-restore` | List recent Dream memory versions. |
| `/dream-restore <sha>` | Restore memory to the state before a specific Dream commit. |

---

## Configuration

The relevant fields live in `agents.defaults` (see
[configuration.md](./configuration.md#agentsdefaults) for the full schema).

```json
{
  "agents": {
    "defaults": {
      "maxMessages": 120,
      "sessionTtlMinutes": 0,
      "consolidationRatio": 0.5,
      "dream": {
        "enabled": true,
        "intervalH": 2
      }
    }
  }
}
```

| Field | What it controls |
|---|---|
| `maxMessages` | How many of the most recent session messages are replayed into the prompt before the agent sees older turns as `Consolidator` summaries. |
| `sessionTtlMinutes` | Idle threshold for `AutoCompact`. `0` = disabled. Set to e.g. `60` to compact sessions idle for an hour. |
| `consolidationRatio` | Target fraction of context budget retained after compaction (e.g. `0.5` keeps ~50% — the rest is summarized). |
| `dream.enabled` | Register the Dream cron on startup. |
| `dream.intervalH` | Hours between Dream runs. |
| `dream.modelOverride` | (Placeholder) override the model for Dream sessions. |

If you want Dream to run as part of CI rather than on a schedule, leave
`dream.enabled: false` and invoke `/dream` from your workflow.

---

## Operational notes

- **Storage cost.** `history.jsonl` grows monotonically. Add a cron that
  compresses / rotates it if your session volume is high.
- **Git corruption.** `memory/.git/` is local and intentionally separate from
  any workspace-level Git repo. If it gets corrupted, you lose Dream
  checkpoints but the durable files themselves are still readable.
- **Concurrency.** Dream is single-threaded. If you run multiple instances
  against the same workspace, only one of them should have `dream.enabled:
  true`, or you'll get interleaved commits.
- **Inspection.** The `.cursor` and `.dream_cursor` files are integer
  offsets. To force Dream to re-process entries, lower `.dream_cursor`.

---

## See also

- [configuration.md](./configuration.md) — full schema for `agents.defaults.*`
- [cli-reference.md](./cli-reference.md#in-repl-commands-slash-commands) —
  every slash command
- [architecture.md](./architecture.md) — where the Consolidator / AutoCompact
  / Dream fit in the agent loop