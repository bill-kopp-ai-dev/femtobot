# OpenAI-Compatible API

> **Status:** **ALPHA.** This surface is functional and stable enough for local
> integrations, but it is part of the Stage 2 (A2A) roadmap and may evolve.

`femtobot serve` exposes an OpenAI-compatible HTTP endpoint so any client that
can call OpenAI can call Femtobot. The same binary serves all sessions through
a single per-session lock.

---

## Quick Start

```bash
# Start the server (binds to api.host:api.port from config.json)
uv run femtobot serve

# Start against a specific instance, on a different port
uv run femtobot serve --suffix prod --port 9000
```

Default bind: `127.0.0.1:8900` (from `api` block in `config.json` — see
[configuration.md](./configuration.md#api)). Override per-invocation with
`--host`, `--port`, `--timeout`.

The server prints:

```
Femtobot Starting OpenAI-compatible API server
  Endpoint : http://127.0.0.1:8900/v1/chat/completions
  Model    : minimax/MiniMax-M2.7
  Session  : api:default
  Timeout  : 120s
```

If you bind to `0.0.0.0` or `::`, the startup banner warns you:

```
Warning: API is bound to all interfaces. Only do this behind a trusted
network boundary, firewall, or reverse proxy.
```

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check. Returns `{"status": "ok"}`. |
| `GET` | `/v1/models` | Lists the single configured model. |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completion. Supports `stream: true`. |

All endpoints live on the same port. The server is plain HTTP — terminate TLS
at a reverse proxy (nginx, Caddy, Traefik) if you need HTTPS.

---

## Authentication

**The server has no built-in authentication.** It binds to `127.0.0.1` by
default, which is the only real defense. If you bind to a public interface:

- Put it behind a reverse proxy that enforces auth (mTLS, basic auth,
  bearer token).
- Or firewall the port to known IPs.
- Or run it inside a Docker network and only expose via an authenticated
  gateway.

The `api_key` field in OpenAI client configs is **not validated** — anything
works. Don't rely on it for security.

---

## `GET /v1/models`

```bash
curl http://127.0.0.1:8900/v1/models
```

Returns:

```json
{
  "object": "list",
  "data": [
    {
      "id": "minimax/MiniMax-M2.7",
      "object": "model",
      "created": 0,
      "owned_by": "Femtobot"
    }
  ]
}
```

The `id` is whatever `agents.defaults.model` resolves to in your config
(plus the preset tag if applicable). There's exactly one model per Femtobot
process — pass any other `model` value in `/v1/chat/completions` and you'll
get `400 Only configured model '<id>' is available`.

---

## `POST /v1/chat/completions`

### Non-streaming

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

Response:

```json
{
  "id": "chatcmpl-7f3a2b1c",
  "object": "chat.completion",
  "created": 1719500000,
  "model": "minimax/MiniMax-M2.7",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Hi there!"},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

> Note: `usage` is currently reported as zeros. Token accounting is a roadmap
> item, not a regression.

### Streaming (SSE)

Set `"stream": true` to receive Server-Sent Events. The server emits
`chat.completion.chunk` deltas, then a final chunk with `finish_reason: "stop"`,
then `data: [DONE]`.

```bash
curl -N http://127.0.0.1:8900/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Count to 5"}],
    "stream": true
  }'
```

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"1"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":", 2"},"finish_reason":null}]}

…

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### Request fields

| Field | Type | Default | Description |
|---|---|---|---|
| `messages` | array | **required** | Standard OpenAI messages array. Roles: `system`, `user`, `assistant`. |
| `model` | str | from config | Must match the configured model exactly. Other values → `400`. |
| `stream` | bool | `false` | If `true`, response is SSE. |
| `session_id` | str | `"default"` | Per-session continuity. Different IDs keep independent histories. Sessions persist across requests via the workspace. |

> Femtobot does **not** support `temperature`, `top_p`, `tools`, `tool_choice`,
> `response_format`, or other sampling/structured-output fields. Generation
> parameters come from `agents.defaults` (or the active preset). For finer
> control, switch presets — see [configuration.md](./configuration.md#modelpresets).

### Errors

```json
{ "error": { "message": "Only configured model 'minimax/MiniMax-M2.7' is available", "type": "invalid_request_error", "code": 400 } }
```

| Status | When |
|---|---|
| `400` | Invalid JSON body, unknown `model`, malformed `messages`. |
| `500` | Internal agent-loop failure. Inspect server logs. |
| `504` | Request exceeded `api.timeout` seconds (default 120). |

---

## Session semantics

The server uses one agent-loop instance and per-session locks. Each unique
`session_id` (or the literal `"default"`) gets its own conversation history
backed by the workspace's `sessions/` directory. Two concurrent requests with
the same `session_id` serialize through the lock; different sessions run in
parallel.

This means:

- The server is safe to share across multiple clients, as long as each uses a
  distinct `session_id`.
- The model, provider, and all generation params are shared — sessions only
  differ in conversation history.

---

## Python clients

### `openai` (recommended)

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8900/v1", api_key="not-required")

resp = client.chat.completions.create(
    model="minimax/MiniMax-M2.7",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)
```

Streaming:

```python
stream = client.chat.completions.create(
    model="minimax/MiniMax-M2.7",
    messages=[{"role": "user", "content": "Count to 5"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### `requests` (minimal)

```python
import requests

resp = requests.post(
    "http://127.0.0.1:8900/v1/chat/completions",
    json={"messages": [{"role": "user", "content": "Hello!"}]},
    timeout=120,
)
resp.raise_for_status()
print(resp.json()["choices"][0]["message"]["content"])
```

---

## See also

- [cli-reference.md](./cli-reference.md#femtobot-serve) — every `femtobot serve` flag
- [configuration.md](./configuration.md#api) — `api.host`, `api.port`, `api.timeout`
- [python-sdk.md](./python-sdk.md) — the SDK alternative to driving the HTTP surface
- [websocket.md](./websocket.md) — the other ingress (WebSocket) for streaming clients that prefer that protocol