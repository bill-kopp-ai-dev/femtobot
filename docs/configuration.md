# Configuration

Config file: `.femtobot/config.json` (relative to the instance directory).
The default instance directory is located at `~/.femtobot/` unless overridden via `FEMTOBOT_HOME` or the `--suffix`/`--folder-path` CLI arguments.

## Environment Variables

You can set the `FEMTOBOT_HOME` environment variable to change the base path where femtobot looks for instance directories. For example, setting `FEMTOBOT_HOME=/opt/femtobot` will cause the default instance config to be located at `/opt/femtobot/.femtobot/config.json`.

## Schema

The configuration file is structured into several key sections:

### agents.defaults

Configures the core agent behavior, including the LLM provider, model, and reasoning parameters.

```json
{
  "agents": {
    "defaults": {
      "provider": "openrouter",
      "model": "anthropic/claude-3.5-sonnet",
      "reasoningEffort": null
    }
  }
}
```

### providers

Configures access to specific LLM providers.

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "YOUR_API_KEY",
      "apiBase": "https://openrouter.ai/api/v1"
    },
    "custom": {
      "apiKey": "YOUR_API_KEY",
      "apiBase": "http://localhost:11434/v1"
    }
  }
}
```

### channels

Configures external access to the agent. Currently, the primary supported channel for custom integrations is the `websocket` channel.

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

### tools

Configures available tools for the agent.

```json
{
  "tools": {
    "my": {
      "enable": true,
      "allow_set": false
    }
  }
}
```
