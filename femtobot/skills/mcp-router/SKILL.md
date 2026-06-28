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

## `workspace_path` — non-negotiable rule

**Never invent a `workspace_path`. Always pass exactly what the runtime
injects for you.** Specifically:

1. **Default: omit `workspace_path`.** The runtime auto-fills it from the
   active request context (see `AgentLoop._set_tool_context`). Pass
   nothing and let the wrapper fill it in. This is the safe path.
2. **Never pass `/tmp`, `/var`, `/home`, or any other system path**
   as a "convenient scratch dir". Servers reject with
   `NOT_ALLOWED: workspace_path is outside allowed roots`. Your retry
   will hit the same error.
3. **If you genuinely need an isolated scratch area** (smoke test,
   scratch computation, etc.) **inside the active workspace**, create a
   subdirectory like `<active_workspace>/.scratch_<task_id>/` via
   `exec mkdir -p` or `apply_patch` and pass that absolute path.
   Confirm the subdirectory is under the auto-filled workspace first.
4. **If you must operate outside the configured `ALLOWED_ROOTS`**
   (cross-repo work, system inspection, anything outside
   `/home/bill/Codes/CLI-router-project`), **stop and ask the user**:
   they may need to widen `AGY_MCP_ALLOWED_ROOTS` /
   `CLAUDE_MCP_ALLOWED_ROOTS` in `.femtobot/config.json` and restart
   the MCP servers. Do NOT silently bypass the policy.

**Symptom of getting this wrong:**

```
ValueError: NOT_ALLOWED: workspace_path is outside allowed roots
```

The fix is **never** to retry with a different invented path. The fix
is to use the auto-filled workspace, or to escalate to the user.

**Why this matters:** each MCP server enforces an `ALLOWED_ROOTS` policy
as a sandbox boundary. Auto-fill exists precisely so you don't have to
reason about paths. If you override it, you are operating outside the
trusted boundary without the user knowing — and the server will reject
the call anyway.

## Confirm gate (safe-mode)

Both servers run in `mode=safe` by default. Writes require `confirm=true`.
NEVER set `confirm=true` speculatively. Pattern:

1. Call the tool with `confirm=false` to get the proposed plan.
2. Show the user what the tool wants to change.
3. Wait for the user to say "yes" / "go ahead" / "proceed".
4. Re-call with `confirm=true`.
