# Multiple Instances

femtobot can run multiple instances on the same machine, each with its own isolated configuration, memory, and workspace. This is achieved using the `--suffix` or `--folder-path` CLI flags.

## Instances Structure

By default, femtobot stores its data in `.femtobot/` (usually located in your home directory or `FEMTOBOT_HOME`).
When you specify a suffix, it creates an isolated directory named `.femtobot_<suffix>/`.

- Default instance: `.femtobot/`
- Instance with suffix `dev`: `.femtobot_dev/`
- Instance with suffix `test`: `.femtobot_test/`

Alternatively, you can provide an exact absolute or relative path using `--folder-path`.

## Quick Start

**1. Initialize instances:**

```bash
# Initialize default instance
femtobot onboard

# Initialize a 'dev' instance
femtobot onboard --suffix dev

# Initialize an instance in a specific path
femtobot onboard --folder-path /path/to/my/custom/instance
```

**2. Configure each instance:**

Each instance directory contains its own `config.json` and `workspace/` directory. You can edit them independently.

**3. Run instances:**

```bash
# Chat with the 'dev' instance
femtobot agent -m "Hello dev instance!" --suffix dev

# Start the API server for the custom path instance
femtobot serve --folder-path /path/to/my/custom/instance
```

## Suffix Validation

Suffixes must be alphanumeric and may contain hyphens or underscores (e.g., `test-1`, `dev_env`).

## Common Use Cases

- Keep testing and production instances isolated
- Use different models or providers for different projects
- Run multiple autonomous agents with separate configurations
