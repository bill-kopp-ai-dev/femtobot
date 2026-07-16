# Multiple Instances

femtobot can run multiple instances on the same machine, each with its own
isolated configuration, memory, and workspace. This is achieved by pointing
the CLI at a different directory, either via `--folder-path` or via the
`FEMTOBOT_HOME` environment variable.

This is the same model upstream nanobot uses: one instance per directory.
Femtobot previously exposed a `--suffix` flag that named instances
`.femtobot_<x>/`, but that flag was **removed in v0.2.0** (refactor for
parity with nanobot, see
[`docs/refactor-parity-with-nanobot.md`](refactor-parity-with-nanobot.md)).
The flag was the only mechanism that produced derived directory names,
and it carried a self-replication risk (an agent with shell access could
materialize `.femtobot_ok/` etc. on disk).

## Directory layout

By default, femtobot stores its data in `.femtobot/` (located in your
project root or `FEMTOBOT_HOME`).

- Default: `<project>/.femtobot/`
- Override: `--folder-path /path/to/my/custom/instance` →
  `/path/to/my/custom/instance/.femtobot/`
- Override: `FEMTOBOT_HOME=/path/to/my/custom/instance` → same.

## Quick Start

**1. Initialize instances:**

```bash
# Initialize default instance in the current project
femtobot onboard

# Initialize an instance in a specific path
femtobot onboard --folder-path /path/to/my/custom/instance

# Same, via env var
FEMTOBOT_HOME=/path/to/my/custom/instance femtobot onboard
```

**2. Configure each instance:**

Each instance directory contains its own `config.json` and `workspace/`
directory. You can edit them independently.

**3. Run instances:**

```bash
# Chat with the default instance
femtobot agent -m "Hello"

# Chat with a custom-path instance
femtobot agent -m "Hello custom instance!" --folder-path /path/to/my/custom/instance

# Or via env var
FEMTOBOT_HOME=/path/to/my/custom/instance femtobot agent -m "Hello"
```

## Common Use Cases

- Keep testing and production instances isolated
- Use different models or providers for different projects
- Run multiple autonomous agents with separate configurations

## Migrating from `--suffix`

If you previously used `femtobot onboard --suffix dev`, your data lives at
`<project>/.femtobot_dev/`. Move it to a path under your control:

```bash
mv .femtobot_dev /path/to/my/custom/instance/.femtobot
# Then use:
femtobot agent -m "Hello" --folder-path /path/to/my/custom/instance
```

The contents (config.json, workspace/, history/) are unchanged.