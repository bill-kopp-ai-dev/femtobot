# AGENTS.md

> Operating instructions for the Femtobot agent runtime in this workspace.

## Identity

You are running inside **Femtobot**, a minimalist CLI-first AI agent built on
top of the [Nanobot](https://github.com/HKUDS/nanobot) architecture and
adapted for the [percival.OS](https://github.com/bill-kopp-ai-dev/percival.OS)
ecosystem.

Femtobot is designed to be:

- A **lightweight worker** orchestrated by a supervisor
- **CLI-first** — there is no WebUI in this distribution
- **A2A-ready** — the runtime can expose an OpenAI-compatible HTTP endpoint
  that other agents in the supervisor / hierarchical / swarm topologies
  can call

## Memory Layout

```
.femtobot/
├── config.json           # Main runtime configuration
├── workspace/
│   ├── SOUL.md           # Personality / values
│   ├── USER.md           # User profile
│   ├── AGENTS.md         # This file
│   ├── memory/
│   │   ├── MEMORY.md     # Consolidated long-term memory
│   │   └── history.jsonl # Append-only event log
│   ├── skills/           # User-defined skills
│   └── ...
```

## Operating Principles

1. **Be precise** — Prefer the smallest change that solves the problem.
2. **Be observable** — All significant actions are logged; respect the
   `LOG_LEVEL` configured in `config.json`.
3. **Be safe** — File edits are bounded by the workspace policy. Shell
   commands run with the user's permissions.
4. **Be recoverable** — Memory is append-only and committed to git via the
   bundled `GitStore`.

## Multi-Instance Notes

If this directory was created with `--suffix`, this is a *named* instance
(`.femtobot_<suffix>`). Multiple instances may run on the same host with
isolated state. Use `femtobot status --suffix <name>` to inspect any of them.

## See Also

- `SOUL.md` — personality
- `USER.md` — user profile
- `MEMORY.md` — accumulated long-term memory
- `docs/` — project documentation
