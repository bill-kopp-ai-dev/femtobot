# Self Tool (My Tool)

The `self` tool (formerly "my tool") allows the agent to sense and adjust its own runtime state. It acts as an internal introspection mechanism.

## Overview

Normal tools let the agent operate on the outside world (read/write files, search code). The self tool lets the agent:

- **Know its configuration**: Check current settings, models, and limits.
- **Understand its context**: Read its workspace path and instance parameters.

The tool is implemented in `femtobot/agent/tools/self.py`.

## Usage

The tool is available by default and can be used to query internal state.

### check — Check current state

The agent can call the tool to inspect its current configuration and active properties. This helps the agent make decisions based on available context window, tools, or model constraints.

```text
self(action="check")
```

With a key parameter, the agent can drill into a specific configuration:

```text
self(action="check", key="model")
# → What model is currently running
```

## Practical Scenarios

### "Self-diagnosis"

```text
User: "Which model are you using?"
Agent: Let me check my configuration.
→ self(action="check", key="model")
```

### "Workspace Location"

```text
Agent: Let me check where my workspace is located before I write the file.
→ self(action="check", key="workspace")
```

## Security Mechanisms

The tool is primarily read-only to prevent the agent from causing persistent damage or escaping the intended sandbox constraints. Sensitive information (like API keys and tokens) is explicitly blocked from being read or modified.
