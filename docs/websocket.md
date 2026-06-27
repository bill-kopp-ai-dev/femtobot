# WebSocket Server Channel

> **Status:** **ALPHA / MINIMAL.** Femtobot is fundamentally a CLI-first application.
> The WebSocket channel is provided for custom integrations, programmatic clients,
> and the A2A roadmap. It is not intended as the main communication channel for
> end users — the terminal is.

Femtobot can act as a WebSocket server, allowing external clients or scripts to
interact with the agent in real time via persistent connections.

---

## Quick Start

### 1. Configure

Add a `websocket` block under `channels` in `.femtobot/config.json`:

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 8765,
      "websocketRequiresToken": false
    }
  }
}
```

> **Important — `websocketRequiresToken` defaults to `true`.** If you leave it
> at the default with an empty `token` and no `token_issue_path`, the handshake
> will reject every client with `401 Unauthorized`. For local development on
> `127.0.0.1` you almost always want `websocketRequiresToken: false` (or set a
> static `token` — see [Authentication](#authentication) below).

### 2. Start the server

`femtobot gateway` starts the simplified HTTP gateway on the configured
`api.host` / `api.port`. To run the dedicated WebSocket channel, run the agent
loop with the websocket channel enabled:

```bash
femtobot agent --suffix dev
```

The agent log will show:

```
[websocket] WebSocket server listening on ws://127.0.0.1:8765/
```

### 3. Connect a client

You can use a simple tool like `websocat` or a Python script to connect and
exchange JSON payloads:

```python
import asyncio, json
import websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8765/") as ws:
        ready = json.loads(await ws.recv())
        print("Connected:", ready)

        await ws.send(json.dumps({"content": "Hello femtobot!"}))
        reply = json.loads(await ws.recv())
        print("Reply:", reply.get("text", reply))

asyncio.run(main())
```

---

## Configuration reference

All fields live under `channels.websocket` in `config.json`. The schema is
defined in `femtobot/channels/websocket.py:170`.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch. |
| `host` | str | `"127.0.0.1"` | Bind address. **Must not be `0.0.0.0` or `::` unless `token` or `token_issue_secret` is set** (see validator below). |
| `port` | int | `8765` | TCP port. |
| `unix_socket_path` | str | `""` | If non-empty, listen on this absolute Unix socket instead of TCP. |
| `path` | str | `"/"` | HTTP path that accepts the WebSocket upgrade. Must start with `/`. |
| `token` | str | `""` | Static bearer token. If set, clients must pass `?token=<this>` on the WebSocket URL. Compared with `hmac.compare_digest`. |
| `token_issue_path` | str | `""` | HTTP endpoint (`GET`) that returns short-lived `{"token": "...", "expires_in": <sec>}`. Must start with `/`, must differ from `path`. |
| `token_issue_secret` | str | `""` | If non-empty, token-issue requests must send `Authorization: Bearer <secret>` or `X-Femtobot-Auth: <secret>`. |
| `token_ttl_s` | int (30–86400) | `300` | Lifetime of issued tokens in seconds. |
| `websocketRequiresToken` | bool | `true` | If `true`, every handshake must present a valid token (static or issued). |
| `allowFrom` | list[str] | `["*"]` | Client-ID allow-list. Wildcard `*` permits all. Empty list denies all. |
| `streaming` | bool | `true` | Forward model deltas to the client in real time. |
| `maxMessageBytes` | int (1024–41943040) | `37748736` | Per-message size cap (~36 MB). Hard ceiling 40 MB. |
| `pingIntervalS` | float (5–300) | `20.0` | WebSocket keepalive interval. |
| `pingTimeoutS` | float (5–300) | `20.0` | WebSocket keepalive timeout. |
| `sslCertfile` | str | `""` | PEM cert path. If both cert and key are set, the listener upgrades to `wss://`. |
| `sslKeyfile` | str | `""` | PEM key path. |

### Validators (enforced at config load time)

1. **`path`** must start with `/`.
2. **`token_issue_path`** must start with `/` and must differ from `path`
   (otherwise the WebSocket upgrade route would be shadowed).
3. **Wildcard host requires auth**: if `host` is `0.0.0.0` or `::` and neither
   `token` nor `token_issue_secret` is set, config loading raises
   `ValueError("host is 0.0.0.0 (all interfaces) but neither token nor token_issue_secret is set — set one to prevent unauthenticated access")`.
   This blocks accidentally exposing an unauthenticated channel to the LAN.

---

## Authentication

Femtobot supports three modes:

### Anonymous (local-only)

```json
{
  "websocket": {
    "enabled": true,
    "host": "127.0.0.1",
    "websocketRequiresToken": false
  }
}
```

Suitable for development on the loopback interface. **Do not** combine with
`host: 0.0.0.0`.

### Static token

```json
{
  "websocket": {
    "enabled": true,
    "host": "0.0.0.0",
    "token": "percival-secret-token",
    "websocketRequiresToken": true
  }
}
```

Clients connect with `ws://host:8765/?token=percival-secret-token`. The server
compares with `hmac.compare_digest`. Recommended for single-tenant deployments
and Docker networks.

### Short-lived issued tokens

```json
{
  "websocket": {
    "enabled": true,
    "host": "0.0.0.0",
    "token_issue_path": "/webui/token",
    "token_issue_secret": "percival-issuer-secret",
    "token_ttl_s": 300,
    "websocketRequiresToken": true
  }
}
```

Workflow:

1. Client `GET http://host:8765/webui/token` with header
   `Authorization: Bearer percival-issuer-secret` → server returns
   `{"token": "<jwt-like>", "expires_in": 300}`.
2. Client opens `ws://host:8765/?token=<issued>`.
3. Server validates, accepts the connection, marks the token as used.

This is the recommended setup for A2A peers in a Docker network — the issuer
secret never leaves the trusted network and each issued token is single-use.

---

## Connecting from the same process

If your client code lives inside the same Python process as Femtobot and shares
the asyncio loop, do **not** call blocking `urllib` or synchronous `httpx` from
inside a coroutine to fetch the issued token. Use `httpx.AsyncClient` or run the
HTTP fetch in a thread.

---

## Security

Because this channel is currently minimal and alpha:

- Use it strictly on **trusted local networks** (`127.0.0.1` or authenticated
  LAN deployments).
- Exposing the WebSocket channel publicly without a robust reverse proxy
  (TLS termination, rate limiting, IP allow-list) is not recommended.
- All file paths and tool results in outbound messages are local filesystem
  paths. Remote clients need a shared filesystem or an HTTP file server to
  access media.

---

## See also

- [configuration.md](./configuration.md#channels) — full `channels` schema and
  the top-level UX flags (`sendProgress`, `sendToolHints`, etc.).
- [multiple-instances.md](./multiple-instances.md) — run multiple instances on
  the same host with isolated `port` and `allowFrom`.
- [openai-api.md](./openai-api.md) — the OpenAI-compatible HTTP surface, the
  other way for agents to talk to Femtobot.