# OpenAI-Compatible API (ALPHA)

> **STAGE 2 PREPARATION:** This feature is in Alpha and is part of the Stage 2 (A2A) multi-agent communication roadmap.

femtobot can expose an OpenAI-compatible API endpoint for local integrations and agent-to-agent communication.

```bash
femtobot serve
```

By default, the API binds to `127.0.0.1:8900`. 

## Endpoints

The API provides the following endpoints:

- `GET /health` : Check the health of the API server.
- `GET /v1/models` : List the available models.
- `POST /v1/chat/completions` : Standard OpenAI-compatible chat completions endpoint.

## curl Example

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Python (`requests`) Example

```python
import requests

resp = requests.post(
    "http://127.0.0.1:8900/v1/chat/completions",
    json={
        "messages": [{"role": "user", "content": "Hello!"}]
    },
    timeout=120,
)
resp.raise_for_status()
print(resp.json()["choices"][0]["message"]["content"])
```

## Python (`openai`) Example

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8900/v1",
    api_key="dummy",
)

resp = client.chat.completions.create(
    model="femtobot",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)
```
