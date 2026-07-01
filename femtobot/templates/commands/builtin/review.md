---
name: /review
description: Review a GitHub pull request
argument_hint: [pr-url]
tags: [code-review, github]
bypass_llm: false
allowed_tools:
  - read_file
  - web_search
---

Review the changes in pull request $ARGUMENTS.

Steps:
1. Use web search to find the PR diff if no local checkout is available.
2. Read the changed files using read_file to understand the context.
3. Provide a concise review focusing on: correctness, security, and maintainability.
