# Python SDK

There are **three** ways to drive Femtobot from Python, ordered from highest to
lowest abstraction:

1. **`Femtobot` programmatic facade** — direct in-process API. Best for SDKs,
   long-lived integrations, and tests.
2. **`femtobot serve` + OpenAI client** — start the HTTP server, talk to it
   with the standard `openai` package. Best for cross-language and A2A setups.
3. **Subprocess + CLI** — spawn `femtobot agent -m …` from Python. Best for
   one-shot scripting where each call is independent.

---

## 1. `Femtobot` programmatic facade (recommended)

The `Femtobot` class lives in [`femtobot/femtobot.py`](../femtobot/femtobot.py).
It loads `config.json`, builds an `AgentLoop`, and exposes a coroutine that
runs a single turn end-to-end.

```python
import asyncio
from femtobot import Femtobot

async def main():
    bot = Femtobot.from_config("/home/me/.femtobot/config.json")

    result = await bot.run(
        "Summarize the last 5 commits in this repo",
        session_key="sdk:default",
    )
    print(result.content)
    print("Tools used:", result.tools_used)

asyncio.run(main())
```

`result` is a `RunResult` dataclass with three fields:

| Field | Type | Description |
|---|---|---|
| `content` | `str` | Final assistant text. |
| `tools_used` | `list[str]` | Names of tools the agent invoked (e.g. `["read_file", "exec", "apply_patch"]`). |
| `messages` | `list[dict]` | Full conversation snapshot (for inspection, logging, or replay). |

### Lifecycle hooks

Pass `hooks=[…]` to observe or modify the run:

```python
from femtobot.agent.hook import AgentHook, AgentHookContext

class TimingHook(AgentHook):
    async def pre_iteration(self, ctx: AgentHookContext) -> None:
        print(f"→ iteration {ctx.iteration}")

    async def post_iteration(self, ctx: AgentHookContext) -> None:
        print(f"← iteration {ctx.iteration} ({ctx.elapsed_ms}ms)")

result = await bot.run("…", hooks=[TimingHook()])
```

### Overriding the workspace

Sometimes you want to point Femtobot at a transient workspace (e.g. for a
CI job):

```python
bot = Femtobot.from_config(
    "/home/me/.femtobot/config.json",
    workspace="/tmp/femtobot-ci-123",
)
```

### Caveats

- Each `Femtobot` instance owns one `AgentLoop`. Calling `bot.run(…)`
  concurrently from multiple coroutines on the same instance is not safe —
  create one `Femtobot` per concurrent caller.
- The in-process facade does **not** wire the WebSocket channel. If you need
  streaming to a custom client, use option (2).

---

## 2. OpenAI-compatible HTTP server

Start `femtobot serve` in the background, then drive it with any OpenAI
client (Python, Node, curl, etc.). See [openai-api.md](./openai-api.md) for
the full API reference.

```python
import subprocess, time
from openai import OpenAI

server = subprocess.Popen(
    ["uv", "run", "femtobot", "serve", "--suffix", "dev"],
    cwd="/path/to/femtobot",
)
time.sleep(2)  # let the server bind

try:
    client = OpenAI(base_url="http://127.0.0.1:8900/v1", api_key="not-required")
    resp = client.chat.completions.create(
        model="femtobot",
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(resp.choices[0].message.content)
finally:
    server.terminate()
    server.wait()
```

The OpenAI surface is the recommended integration boundary for cross-language
and A2A peers.

---

## 3. Subprocess + CLI

For one-shot scripts, the simplest path is to call the CLI directly:

```python
import subprocess

def run_agent(message: str, suffix: str | None = None) -> str:
    cmd = ["femtobot", "agent", "-m", message]
    if suffix:
        cmd.extend(["--suffix", suffix])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()

print(run_agent("What is the capital of France?"))
```

This is robust because the CLI is the only public surface we promise to keep
stable across releases. It's also the slowest, since each call pays the full
CLI startup cost (~1–2 s).

---

## Choosing between the three

| Use case | Pick |
|---|---|
| In-process Python library | `Femtobot.from_config()` |
| Tests / mocks / assertions | `Femtobot.from_config()` + hooks |
| Cross-language / A2A / web UI | `femtobot serve` + OpenAI client |
| Cron job, one-shot script | subprocess + CLI |

---

## See also

- [openai-api.md](./openai-api.md) — endpoints, request/response shapes, streaming
- [configuration.md](./configuration.md) — `config.json` schema
- [architecture.md](./architecture.md) — where `Femtobot` and `AgentLoop` fit in the runtime graph