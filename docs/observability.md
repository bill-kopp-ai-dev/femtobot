# Observability with Logfire

Femtobot 1.0 uses [Pydantic Logfire](https://logfire.pydantic.dev) for
observability. Logfire is **opt-in**: by default nothing is sent
anywhere. Set the `FEMTOBOT_LOGFIRE=1` environment variable (or pass a
write token) to enable.

## Quick start

1. Sign up at <https://logfire.pydantic.dev> (free tier is fine).
2. Authenticate: `uv run logfire auth`.
3. Create a project: `uv run logfire projects new`.
4. Enable: `FEMTOBOT_LOGFIRE=1 uv run femtobot agent`.
5. View traces at <https://logfire.pydantic.dev>.

## Environment variables

| Variable | Values | Default | Effect |
|---|---|---|---|
| `FEMTOBOT_LOGFIRE` | `1` / `true` / `yes` | unset | Shortcut for `FEMTOBOT_LOGFIRE_SEND=yes` |
| `FEMTOBOT_LOGFIRE_SEND` | `yes` / `no` / `if-token-present` / `auto` | `if-token-present` | Explicit control over send-to-Logfire |
| `FEMTOBOT_LOGFIRE_HTTPX` | `1` / `true` / `yes` | unset | Also instrument httpx (high volume) |

Precedence: `FEMTOBOT_LOGFIRE_SEND` wins over `FEMTOBOT_LOGFIRE`, which
wins over the default (`if-token-present`).

## Self-hosted OpenTelemetry

Set `FEMTOBOT_LOGFIRE_SEND=no` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://...`
to send traces to any OTel collector:

```bash
FEMTOBOT_LOGFIRE_SEND=no \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
  uv run femtobot agent
```

## What gets instrumented

- `FemtobotAgent.run()` / `FemtobotAgent.run_stream()` → top-level span.
- Every PydanticAI model call → child span with token usage.
- Every tool call (Phase 3+) → child span with args and result.
- Every MCP interaction → child span (when MCP is enabled).
- `httpx` HTTP traffic → opt-in via `FEMTOBOT_LOGFIRE_HTTPX=1`.

## Disabling in CI

Tests force Logfire off via the `tests/observability/test_logfire_setup.py`
`autouse` fixture: `monkeypatch.setenv("FEMTOBOT_LOGFIRE_SEND", "no")`.
Nothing reaches Logfire during the standard `pytest tests/` run.

## API summary

```python
from femtobot.observability import logfire_setup

logfire_setup.configure()                # Reads FEMTOBOT_LOGFIRE / _SEND
logfire_setup.configure(send_to_logfire="no")  # Override
logfire_setup.instrument_pydantic_ai()   # Idempotent
logfire_setup.instrument_httpx()         # Opt-in via env
```
