# WebSocket Server Channel (ALPHA/MINIMAL)

> **ALPHA / MINIMAL STATUS:** femtobot is fundamentally a CLI-first application. The WebSocket channel is minimal and provided primarily for custom integrations and experimental use cases. It is not intended as the main communication channel.

Femtobot can act as a WebSocket server, allowing external clients or scripts to interact with the agent in real time via persistent connections.

## Quick Start

### 1. Configure

Add to `.femtobot/config.json` under `channels.websocket`:

```json
{
  "channels": {
    "websocket": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 8765
    }
  }
}
```

### 2. Start femtobot Gateway

```bash
femtobot gateway
```

You should see an indication that the WebSocket server is listening on the configured host and port.

### 3. Connect a client

You can use a simple tool like `websocat` or a Python script to connect and exchange JSON payloads.

```python
import asyncio
import json
import websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8765/") as ws:
        # Wait for the server ready signal
        ready = json.loads(await ws.recv())
        print("Connected:", ready)
        
        # Send a message
        await ws.send(json.dumps({"content": "Hello femtobot!"}))
        
        # Receive the reply
        reply = json.loads(await ws.recv())
        print("Reply:", reply.get("text", reply))

asyncio.run(main())
```

## Security

Because this channel is minimal and alpha, use it strictly on trusted local networks (`127.0.0.1`). Exposing the WebSocket channel publicly without a robust proxy and authentication layer is not recommended for production environments.
