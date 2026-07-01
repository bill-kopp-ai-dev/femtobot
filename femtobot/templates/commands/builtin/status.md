---
name: /status
description: Show Femtobot runtime status
argument_hint: []
tags: [info, session]
bypass_llm: false
---

Show the current session status including context window usage, model, and MCP server state.

This command queries the active agent loop directly and does not use the LLM.
