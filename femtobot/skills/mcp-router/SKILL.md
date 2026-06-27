---
name: mcp-router
description: >
  Decide when to delegate a coding task to agy_run_task / claude_run_task
  (long autonomous workflows) versus using local tools (read_file,
  apply_patch, exec). Use this skill whenever the user mentions a
  multi-file refactor, autonomous planning, model comparison, or
  "let the agent handle it end-to-end".
metadata:
  femtobot:
    always: false
---

# MCP Router Skill

## When to delegate

Delegate to `agy_run_task` / `claude_run_task` if ANY of:

- The user says "refactor", "redesign", "migrate", "implement this
  feature end-to-end".
- The change spans >= 3 files.
- The user explicitly says "use Gemini" / "use Claude" / "let the agent
  handle this".
- The change requires planning + sequencing that local tool calls
  cannot express (e.g., "add a feature following the existing pattern
  in this repo").

## When NOT to delegate

Use local tools (`read_file`, `grep`, `apply_patch`, `edit_file`, `exec`):

- Single-file edits.
- Quick Q&A about the code ("what does this function do?").
- Running tests, builds, linters.
- Searching across the workspace.

## Server selection

| If the user wants... | Use |
|---|---|
| Long-horizon planning, multi-step refactor | `agy_run_task` |
| Quick, focused coding task | `claude_run_task` |
| Compare answers from both | call both, present diff |

## Required parameters

Both tools require:

- `workspace_path` (absolute path, must be in the server's
  `ALLOWED_ROOTS`).
- `task` (one-sentence objective).
- `confirm` (default `false`; set `true` only after explicit user
  approval of the plan).

## Confirm gate (safe-mode)

Both servers run in `mode=safe` by default. Writes require `confirm=true`.
NEVER set `confirm=true` speculatively. Pattern:

1. Call the tool with `confirm=false` to get the proposed plan.
2. Show the user what the tool wants to change.
3. Wait for the user to say "yes" / "go ahead" / "proceed".
4. Re-call with `confirm=true`.
