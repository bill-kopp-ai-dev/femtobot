# Migrating from Femtobot 0.1.x to 1.0

> **Status:** skeleton (Fase 0). Will be filled in as Phases 1-8 land.

## Breaking changes

- ...

## Auto-migration

Femtobot 1.0 auto-migrates `config.json` from 0.1.x format. No manual
editing required.

## Deprecations

- `providers.<X>.type` values are normalized to: `openai`, `anthropic`,
  `bedrock`, `gemini`, `openai_compat`. Custom values are mapped
  automatically.
