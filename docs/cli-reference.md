# CLI Reference

| Command | Description |
|---------|-------------|
| `femtobot onboard` | Initialize config & workspace |
| `femtobot onboard --force` | Overwrite existing configuration |
| `femtobot onboard --suffix <name>` | Initialize a specific instance using a suffix |
| `femtobot onboard --folder-path <path>` | Initialize an instance at a specific path |
| `femtobot agent` | Interactive chat mode |
| `femtobot agent -m "..."` | Chat with the agent |
| `femtobot agent --suffix <name>` | Chat against a specific instance suffix |
| `femtobot agent --folder-path <path>` | Chat against a specific instance path |
| `femtobot serve` | Start the OpenAI-compatible API |
| `femtobot gateway` | Start the gateway in headless mode |
| `femtobot gateway --suffix <name>` | Start the gateway for a specific instance suffix |
| `femtobot gateway --folder-path <path>` | Start the gateway for a specific instance path |
| `femtobot status` | Show status |
| `femtobot status --suffix <name>` | Show status for a specific instance suffix |
| `femtobot status --folder-path <path>` | Show status for a specific instance path |

Interactive mode exits: `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.
