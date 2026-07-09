# Plano de Refatoração — "Sync nanobot v0.2.x"

> **Origem:** derivado do
> [RELEASE_PROPAGATION_REPORT.md](./RELEASE_PROPAGATION_REPORT.md).
> **Escopo:** implementar os 4 lotes priorizados (A: estabilidade/segurança,
> B: durabilidade, C: refator, D: providers), totalizando 30 itens upstream.
> **Convenções:** cada item referencia a PR upstream correspondente e tem
> esforço/impacto/dono/branch. `Lote A → S1`, `Lote B → S2`, etc.

---

## 0. Sumário executivo

| Lote | Tema | Itens | Esforço total | PRs sugeridos |
|---|---|---|---|---|
| **A** | Estabilidade e segurança | 14 | ~5–7 dias | A1–A14 (1 milestone) |
| **B** | Durabilidade e concorrência | 6 | ~3–4 dias | B1–B6 |
| **C** | Refator de arquitetura | 5 | ~6–8 dias | C1–C5 |
| **D** | Provedores e cold-start | 4 | ~3–4 dias | D1–D4 |
| **E** | Hardening pós-release | 11 | ~2–3 dias | E1–E11 (audit, ruff, race, security) |
| **Total** | — | **40** | **~19–26 dias úteis** | 5 milestones |

**Premissas:**

- A branch `main` está em v0.0.2; cada lote termina com uma versão interna
  bumped (`v0.0.3-rcN`) e o CHANGELOG atualizado.
- Cada item entra como commit próprio (ou squash de commits pequenos
  relacionados) para revisão atômica.
- Tudo que toca schema/config ganha validação em `tests/test_config_*.py`
  e exemplo em `docs/configuration.md`.
- Tudo que toca security ganha teste de regressão (bypass conhecido) em
  `tests/test_security_*.py`.
- Nenhum dos itens quebra `Femtobot.from_config()` ou o wire do OpenAI
  API (`/v1/chat/completions`) — backward-compat é lei.

**Como ler:** Seção 1 tem o roadmap agregado. Seções 2–5 detalham cada
lote. Seção 6 tem os testes obrigatórios. Seção 7 tem a estratégia de
release.

---

## 1. Roadmap agregado (4 milestones)

### Milestone `v0.0.3` — Lote A: Estabilidade e segurança

Objetivo: fechar a janela de bugs "silenciosos" (config inválida, SSRF
bypass, MCP sem pre-flight, race em memory). Tudo aqui é **XS-S effort
e alto valor**.

**Saída esperada:**

- `femtobot status` reporta config inválida estrutural de forma ruidosa.
- `web_fetch` valida cada hop de redirect.
- SSRF guard trata IPv6-mapped IPv4 e bloqueia `::ffff:0:0/96`.
- MCP HTTP probes são rejeitados pre-flight para IPs privados.
- History append tem lock de cursor + append (já existe, falta audit).
- `FallbackProvider` loga erro primário.
- Quatro testes de regressão de segurança.

**Riscos:** Mudar o loader de config para fail-fast pode quebrar
deployments existentes. Mitigação: gate por env var
`FEMTOBOT_STRICT_CONFIG_LOAD` (default `false` em v0.0.3, `true` em
v0.0.4). Documente em `docs/configuration.md`.

### Milestone `v0.0.4` — Lote B: Durabilidade e concorrência

Objetivo: tornar o femtobot confiável para execução de longa duração
(alinhado com o roadmap A2A/Stage 2 onde workers podem rodar horas).

**Saída esperada:**

- Per-session lock em `Femtobot.run()` (SDK) e `serve` (OpenAI API).
- Loop não aborta com goal sustentado ativo.
- `apply_patch` preserva quebras de linha em adições.
- `usage` real em `/v1/chat/completions`.
- Archived summary mora no system prompt (KV cache estável).

**Riscos:** Per-session lock pode deadlockar se mal-implementado.
Mitigação: testes de stress com `asyncio.gather` no mesmo session_id.

### Milestone `v0.0.5` — Lote C: Refator de arquitetura

Objetivo: DX para contribuidores + caminho de crescimento além de MCP
(extension registry).

**Saída esperada:**

- Doc de `AgentLoop.from_config()`.
- Capabilities em tools (plugin architecture explícita).
- `extensions.json` local registry.
- `/model` wizard no `femtobot onboard`.
- Unified CLI Apps / MCP concept (capability mentions, preset setup).

**Riscos:** Refator de tool loading é terreno minado. Mitigação: feature
flag `FEMTOBOT_USE_PLUGIN_ARCH=true` (default `false` em v0.0.5, vira
`true` em v0.0.6).

### Milestone `v0.0.6` — Lote D: Provedores e cold-start

Objetivo: ampliar cobertura de providers e melhorar cold-start do
gateway A2A (Stage 2).

**Saída esperada:**

- AWS Bedrock Converse nativo (ou via openai-compat layer).
- `extraQuery` no `ProviderConfig`.
- Disable proxy para endpoints locais (localhost, 127.0.0.1, ::1).
- Cold-start do gateway A2A ~10x mais rápido (deferido até o gateway
  existir; ver §5.4).

**Riscos:** Bedrock traz superfície de auth nova (SigV4). Mitigação:
suportar via `boto3` lazy import e `BEDROCK_*` env vars.

### Milestone `v0.0.7` — Lote E: Hardening pós-release

Objetivo: fechar os bugs que ficaram em v0.0.2 → v0.0.6 sem
new features.  Audit manual + ruff check + race conditions +
review de paths de exceção.

**Saída esperada:**

- `WebSocketChannel.gateway` finalmente atribuído (E1).
- `AgentLoop._session_locks` race-fixed (E2).
- `FEMTOBOT_NO_BASH_INLINE` kill-switch para `!`cmd`` em skill
  bodies (E3).
- `AgentLoop.from_config` instance assignment corrigido (E4).
- `atomic_write_text` com `suppress` no escopo correto (E5).
- Vários outros fixes pequenos (E6–E11).

**Riscos:** nenhum — todos os fixes são bug correções
sem breaking changes.  Compat 100% com v0.0.6.

---

## 2. Lote A — Estabilidade e segurança (Milestone v0.0.3)

> 14 itens · ~5–7 dias · PRs #A1–#A14 · Branch: `release/v0.0.3-stability`

### A1. Fail-fast em config inválida estrutural

- **Upstream:** nanobot v0.2.2 #4275
- **Estado atual:** [femtobot/config/loader.py:192-211](file:///home/bill/Codes/agents/femtobot/femtobot/config/loader.py#L192-L211) captura
  `(json.JSONDecodeError, ValueError, pydantic.ValidationError)` e cai no
  default silencioso. Documentado abertamente em
  [docs/configuration.md](./docs/configuration.md) linha 376-381.
- **Mudança:**
  1. Adicionar env var `FEMTOBOT_STRICT_CONFIG_LOAD` (default `false`).
  2. Em modo strict: `JSONDecodeError` e `pydantic.ValidationError` em
     campos **obrigatórios** (top-level) abortam com `SystemExit(2)` e
     mensagem clara apontando o path do campo.
  3. Em modo lenient (default): comportamento atual, **mas** sempre
     emite um warning estruturado com `logger.error` em vez de
     `logger.warning` para typos em chaves de primeiro nível.
  4. Adicionar CLI `femtobot config validate [--strict]` que carrega a
     config e roda as validações sem entrar no agent loop.
- **Arquivos:**
  - [femtobot/config/loader.py](file:///home/bill/Codes/agents/femtobot/femtobot/config/loader.py) — refator de `load_config`.
  - `femtobot/cli/commands.py` — novo subcommand `config validate`.
  - [docs/configuration.md](./docs/configuration.md) — seção "Validation
    behavior".
  - [docs/troubleshooting.md](./docs/troubleshooting.md) — entry
    "Femtobot refuses to start after config edit".
- **Esforço:** S. **Impacto:** Alto. **Dono:** @bill-kopp-ai-dev.
- **Critério de aceitação:** `uv run pytest tests/test_config_loader.py -k strict` passa;
  `femtobot config validate` retorna exit 0/2 corretamente.

### A2. Reject unsafe MCP HTTP URLs antes do probe

- **Upstream:** nanobot v0.2.2 #4123
- **Estado atual:** [femtobot/agent/tools/mcp.py:233-244](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/mcp.py#L233-L244)
  tem `_probe_http_url` que faz TCP probe mas **não** consulta o SSRF
  guard. Já existe `validate_url_target` em
  [femtobot/security/network.py:55-94](file:///home/bill/Codes/agents/femtobot/femtobot/security/network.py#L55-L94)
  que faz exatamente isso.
- **Mudança:**
  1. Em `connect_single_server` (linha 1195-1236 do mcp.py), **antes** do
     `_probe_http_url`, chamar `validate_url_target(cfg.url,
     allow_loopback=True)` (loopback permitido só para `127.0.0.1`/
     `localhost`).
  2. Se inválido: log warning estruturado e abortar a conexão daquele
     servidor (não do processo todo).
  3. Aplicar o mesmo guard em `reload_servers` ao ler `cfg.url` da
     config recarregada.
- **Arquivos:**
  - [femtobot/agent/tools/mcp.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/mcp.py) — pre-flight check antes de
     `_probe_http_url`.
  - `tests/test_mcp_startup_notify.py` — adicionar caso
     "rejeita URL privada antes do probe".
- **Esforço:** S. **Impacto:** Alto (segurança real).
- **Critério de aceitação:** MCP com `url: "http://169.254.169.254/..."`
  é rejeitado no startup sem tentar conectar; teste cobre.

### A3. Validar redirect targets em web_fetch

- **Upstream:** nanobot v0.2.1 #3928
- **Estado atual:** [femtobot/agent/tools/web.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/web.py) tem SSRF guard
  no `validate_url_target` mas não está claro se valida **cada hop** de
  redirect. `aiohttp` e `httpx` (via `follow_redirects=True`) podem
  seguir DNS resolvido para IP privado.
- **Mudança:**
  1. Localizar a chamada `web_fetch` em
     [femtobot/agent/tools/web.py](./femtobot/agent/tools/web.py).
  2. Substituir `follow_redirects=True` por `follow_redirects=False`.
  3. Adicionar hook `on_redirect` que chama
     `validate_url_target(new_url, allow_loopback=...)` em cada hop.
  4. Se inválido: abortar com mensagem clara.
- **Arquivos:**
  - [femtobot/agent/tools/web.py](./femtobot/agent/tools/web.py) — refator
     do request.
  - `tests/test_web_fetch.py` (criar) — caso "redirect para IP privado
     é bloqueado".
- **Esforço:** XS. **Impacto:** Médio.
- **Critério de aceitação:** URL pública que redireciona para
  `http://127.0.0.1:8500` é bloqueada com mensagem clara.

### A4. Normalizar IPv6-mapped IPv4 no SSRF guard

- **Upstream:** nanobot v0.2.1 #4086
- **Estado atual:** [femtobot/security/network.py:12-20](file:///home/bill/Codes/agents/femtobot/femtobot/security/network.py#L12-L20)
  tem lista de redes bloqueadas mas **já existe** o helper
  `_normalize_addr` (linha 36-42) que faz exatamente isso. **Auditar
  se está sendo usado em todos os call-sites.**
- **Mudança:**
  1. Confirmar que `_normalize_addr` é chamado em `validate_url_target`
     e `validate_resolved_url` (verificar pelo código).
  2. Adicionar `::ffff:0:0/96` (IPv6-mapped IPv4) à lista
     `_BLOCKED_NETWORKS` como belt-and-suspenders (mesmo com o
     normalize, ter o range explícito evita bypass futuro).
  3. Adicionar teste: `validate_url_target("http://[::ffff:127.0.0.1]/")`
     retorna `Blocked`.
- **Arquivos:**
  - [femtobot/security/network.py](file:///home/bill/Codes/agents/femtobot/femtobot/security/network.py) — adicionar `::ffff:0:0/96`.
  - `tests/test_security_network.py` (criar) — caso do IPv6-mapped.
- **Esforço:** XS. **Impacto:** Médio (segurança real).
- **Critério de aceitação:** `validate_url_target` bloqueia
  `http://[::ffff:169.254.169.254]/` e variantes.

### A5. Log primary error before fallback

- **Upstream:** nanobot v0.2.0 #4385
- **Estado atual:** [femtobot/providers/fallback_provider.py:62-77](file:///home/bill/Codes/agents/femtobot/femtobot/providers/fallback_provider.py#L62-L77)
  tem `FallbackProvider` com circuit breaker. **Auditar se loga o
  erro primário** antes de cair no fallback.
- **Mudança:**
  1. Se não loga: adicionar `logger.error("Primary provider failed
     before fallback: {kind}: {msg}", kind=..., msg=...)` no
     caminho de failover.
  2. Adicionar `on_primary_error_callback` opcional para testes
     (injetar contador).
- **Arquivos:**
  - [femtobot/providers/fallback_provider.py](file:///home/bill/Codes/agents/femtobot/femtobot/providers/fallback_provider.py).
  - `tests/test_fallback_provider.py` (criar).
- **Esforço:** XS. **Impacto:** Alto (debug + observabilidade).
- **Critério de aceitação:** Teste confirma que `on_primary_error_callback`
  é chamado antes do fallback ser tentado.

### A6. dream_cursor só avança em batches completos

- **Upstream:** nanobot v0.2.0 #3631
- **Estado atual:** `MemoryStore` em
  [femtobot/agent/memory.py:60-73](file:///home/bill/Codes/agents/femtobot/femtobot/agent/memory.py#L60-L73) tem
  `_dream_cursor_file` e `_append_lock`. Auditar se a escrita do
  cursor é atômica com o commit git.
- **Mudança:**
  1. Localizar o método de Dream que avança o cursor.
  2. Garantir que `git commit` acontece **antes** de escrever o
     `.dream_cursor` (ou ambos dentro do mesmo lock).
  3. Se a consolidação falha após commit: reverter commit e não avançar
     cursor.
- **Arquivos:**
  - [femtobot/agent/memory.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/memory.py) — refator do Dream.
  - `tests/test_memory_dream.py` (criar) — caso "cursor não avança
     em falha".
- **Esforço:** S. **Impacto:** Alto.
- **Critério de aceitação:** Simulação de crash mid-Dream → cursor
  não avança, próximo ciclo reprocessa.

### A7. Atomic write em `jobs.json` / persistência de cron

- **Upstream:** nanobot v0.2.0 #3606
- **Estado atual:** Não há arquivo `jobs.json` explícito no femtobot.
  O Dream tem `dream.intervalH` no config e `.dream_cursor` no disco.
- **Mudança:**
  1. Identificar toda persistência de jobs (cron, dream, etc.).
  2. Substituir `open(path, 'w').write(...)` por padrão
     `tempfile.NamedTemporaryFile(dir=parent) + os.replace()`.
  3. Detectar arquivo corrupto: try/except ao carregar, log + skip +
     renomear para `*.corrupt-<timestamp>` em vez de sobrescrever.
- **Arquivos:**
  - [femtobot/agent/memory.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/memory.py) — escrita de `.dream_cursor`.
  - Qualquer outro arquivo de jobs (auditar).
- **Esforço:** S. **Impacto:** Alto.
- **Critério de aceitação:** Crash mid-write não corrompe o arquivo;
  próximo startup detecta e renomeia para `*.corrupt-<ts>`.

### A8. Soft workspace boundary com retry-throttle

- **Upstream:** nanobot v0.2.0 #3614
- **Estado atual:** [docs/security.md](./docs/security.md) linha 33-49 documenta
  `tools.restrictToWorkspace` mas o comportamento atual é **hard-fail**
  (auditar `agent/tools/filesystem.py` e `apply_patch.py`).
- **Mudança:**
  1. Auditar `apply_patch.py` e `write_file` tool: hoje em dia negam
     com exception, ou retornam mensagem de erro?
  2. Se hard-fail: converter para soft warning + retry-throttle (3
     strikes por session_id, depois hard).
  3. Adicionar contagem `workspace_violation_count` ao session
     metadata.
- **Arquivos:**
  - [femtobot/agent/tools/filesystem.py](./femtobot/agent/tools/filesystem.py).
  - [femtobot/agent/tools/apply_patch.py](./femtobot/agent/tools/apply_patch.py).
  - `tests/test_workspace_policy.py` (criar).
- **Esforço:** S. **Impacto:** Médio (resiliência).
- **Critério de aceitação:** Escrita fora do workspace produz warning
  sem crashar o loop; após 3 strikes o session é marcado para review.

### A9. Race fix entre AutoCompact e Consolidator

- **Upstream:** nanobot v0.2.1 #3881
- **Estado atual:** `_append_lock` no `MemoryStore` cobre
  [femtobot/agent/memory.py:64](file:///home/bill/Codes/agents/femtobot/femtobot/agent/memory.py#L64).
  Verificar se `AutoCompact` em
  [femtobot/agent/autocompact.py](./femtobot/agent/autocompact.py) usa o
  mesmo lock.
- **Mudança:**
  1. Se não usa: fazer `AutoCompact.compact_idle_session()` adquirir
     o mesmo `_append_lock` antes de delegar ao `Consolidator`.
  2. Adicionar teste de stress com `asyncio.gather(consolidate(),
     auto_compact())` — saída deve ser consistente.
- **Arquivos:**
  - [femtobot/agent/autocompact.py](./femtobot/agent/autocompact.py).
  - `tests/test_autocompact_race.py` (criar).
- **Esforço:** S. **Impacto:** Alto.
- **Critério de aceitação:** 100 iterações de stress test não
  produzem entries órfãs em `history.jsonl`.

### A10. Ignorar history entries malformados + cursor monotonic

- **Upstream:** nanobot v0.2.2 #4315, #4256
- **Estado atual:** `MemoryStore._LEGACY_*` regex tratam migração legada.
- **Mudança:**
  1. Adicionar `try/except (json.JSONDecodeError, KeyError, ValueError)`
     em todos os pontos de leitura de `history.jsonl`.
  2. Log warning com `entry_index` e skip.
  3. Garantir que o cursor nunca regride (assert no write).
- **Arquivos:**
  - [femtobot/agent/memory.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/memory.py).
- **Esforço:** XS. **Impacto:** Médio.
- **Critério de aceitação:** `history.jsonl` com linha corrompida
  no meio não crasha o Consolidator; warning é emitido com índice.

### A11. `extraQuery` para OpenAI-compat

- **Upstream:** nanobot v0.2.2 #4217
- **Estado atual:** [docs/configuration.md](./docs/configuration.md) linha 150-151 documenta
  `extraHeaders` e `extraBody` mas não `extraQuery`.
- **Mudança:**
  1. Adicionar `extraQuery: dict[str, str] | None = None` ao
     `ProviderConfig` em `femtobot/config/schema.py`.
  2. Em `openai_compat_provider.py`, concatenar
     `?{urlencode(extra_query)}` na URL antes de enviar.
- **Arquivos:**
  - [femtobot/config/schema.py](./femtobot/config/schema.py).
  - [femtobot/providers/openai_compat_provider.py](./femtobot/providers/openai_compat_provider.py).
  - [docs/configuration.md](./docs/configuration.md).
- **Esforço:** XS. **Impacto:** Baixo-Médio.
- **Critério de aceitação:** Provider com `extraQuery: {"api-version":
  "2024-01-01"}` envia a query string correta.

### A12. Sanitizar tool IDs do Anthropic

- **Upstream:** nanobot v0.2.2 #4356
- **Estado atual:** Auditar `providers/openai_compat_provider.py` ou
  wrapper Anthropic.
- **Mudança:**
  1. Adicionar regex `^[a-zA-Z0-9_-]{1,64}$` para validar IDs antes
     de enviar.
  2. Se inválido: substituir por hash determinístico.
- **Arquivos:**
  - [femtobot/providers/openai_compat_provider.py](./femtobot/providers/openai_compat_provider.py).
  - `tests/test_anthropic_sanitize.py` (criar).
- **Esforço:** XS. **Impacto:** Baixo.
- **Critério de aceitação:** Tool ID com caracteres especiais é
  sanitizado antes de chegar no Anthropic API.

### A13. Placeholders de imagem sem path local

- **Upstream:** nanobot v0.2.2 #4401
- **Estado atual:** `femtobot/utils/helpers.py::image_placeholder_text`
  — auditar.
- **Mudança:**
  1. Se placeholder inclui path local: substituir por "[image
     stripped: <reason>]" sem path.
- **Arquivos:**
  - [femtobot/utils/helpers.py](./femtobot/utils/helpers.py).
- **Esforço:** XS. **Impacto:** Baixo-Médio (privacidade).
- **Critério de aceitação:** Teste confirma que o placeholder não
  vaza path absoluto.

### A14. Arrearage/`欠费` como fallback trigger

- **Upstream:** nanobot v0.2.1 #4048
- **Estado atual:** [femtobot/providers/fallback_provider.py:37-59](file:///home/bill/Codes/agents/femtobot/femtobot/providers/fallback_provider.py#L37-L59)
  tem `_FALLBACK_ERROR_TOKENS` mas não `arrearage`/`欠费`.
- **Mudança:**
  1. Adicionar `"arrearage"`, `"欠费"`, `"out of credits"`,
     `"billing_hard_limit"` (já tem) ao set.
  2. Garantir que mensagem de arrearage chega ao usuário clara
     (verificar `ARREARAGE_ERROR_MESSAGE` em
     [femtobot/agent/runner.py:30-34](file:///home/bill/Codes/agents/femtobot/femtobot/agent/runner.py#L30-L34) — já existe!).
- **Arquivos:**
  - [femtobot/providers/fallback_provider.py](file:///home/bill/Codes/agents/femtobot/femtobot/providers/fallback_provider.py).
  - `tests/test_fallback_provider.py` (criar).
- **Esforço:** XS. **Impacto:** Médio (UX em billing).
- **Critério de aceitação:** Erro com texto "arrearage" da API dispara
  fallback e mensagem amigável ao usuário.

---

## 3. Lote B — Durabilidade e concorrência (Milestone v0.0.4)

> 6 itens · ~3–4 dias · PRs #B1–#B6 · Branch: `release/v0.0.4-durability`

### B1. Per-session lock em `process_direct` (SDK + serve)

- **Upstream:** nanobot v0.2.1 #4104
- **Estado atual:** [docs/openai-api.md](./docs/openai-api.md) linha 192-198 afirma
  per-session locks no serve, mas o `Femtobot.run()` do SDK em
  [femtobot/femtobot.py](./femtobot/femtobot.py) **não tem lock explícito
  por `session_key`**. Chamadas concorrentes com mesmo `session_key`
  podem interleave.
- **Mudança:**
  1. Em `Femtobot.run()`, criar `WeakValueDictionary[session_key,
     asyncio.Lock]` e adquirir antes do loop.
  2. Em `api/server.py`, garantir que o mesmo lock é usado por
     session_id.
  3. Timeout de 5s para aquisição; se timeout: `409 Conflict` com
     mensagem clara.
- **Arquivos:**
  - [femtobot/femtobot.py](./femtobot/femtobot.py).
  - [femtobot/api/server.py](./femtobot/api/server.py).
  - `tests/test_session_lock.py` (criar) — stress test com
     `asyncio.gather` no mesmo session_id.
- **Esforço:** S. **Impacto:** Alto.
- **Critério de aceitação:** 100 chamadas concorrentes com mesmo
  `session_key` resultam em 99 com `409` e 1 com sucesso; nenhuma
  corrompe o history.

### B2. Impedir runner de sair com goal ativo + estender budget

- **Upstream:** nanobot v0.2.1 #3999, #4127
- **Estado atual:** `sustained_goal_active` em
  [femtobot/session/goal_state.py:40-44](file:///home/bill/Codes/agents/femtobot/femtobot/session/goal_state.py#L40-L44) e
  `runner_wall_llm_timeout_s` existem. Auditar `agent/loop.py` e
  `agent/runner.py` para garantir que o loop **não desiste** quando
  `status == "active"`.
- **Mudança:**
  1. Em `agent/runner.py`, no caminho de finalização por
     `max_iterations`: se `goal_active_predicate()` é True, **não**
     finalizar; emitir mensagem de "goal em progresso, continuando" e
     continuar.
  2. Adicionar `goal_iteration_extra_budget: int = 50` ao
     `AgentRunSpec`.
- **Arquivos:**
  - [femtobot/agent/runner.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/runner.py).
  - [femtobot/agent/loop.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/loop.py).
  - `tests/test_sustained_goal.py` (criar).
- **Esforço:** XS-S. **Impacto:** Alto.
- **Critério de aceitação:** Loop com goal ativo itera 250 vezes (200
  base + 50 extra) sem abortar.

### B3. Forward real LLM usage em `/v1/chat/completions`

- **Upstream:** nanobot v0.2.2 #4310
- **Estado atual:** [docs/openai-api.md](./docs/openai-api.md) linha 130 admite
  `usage: {prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}`.
- **Mudança:**
  1. Capturar `prompt_tokens`/`completion_tokens` do `LLMResponse` em
     [femtobot/providers/base.py](./femtobot/providers/base.py).
  2. Propagar via `Femtobot.run()` → `RunResult.usage` (novo campo).
  3. Em `api/server.py`, popular `usage` na resposta OpenAI-compat.
- **Arquivos:**
  - [femtobot/providers/base.py](./femtobot/providers/base.py).
  - [femtobot/femtobot.py](./femtobot/femtobot.py).
  - [femtobot/api/server.py](./femtobot/api/server.py).
  - [docs/openai-api.md](./docs/openai-api.md) — remover o disclaimer
     sobre zeros.
- **Esforço:** S. **Impacto:** Alto.
- **Critério de aceitação:** Resposta `/v1/chat/completions` tem
  `usage` com valores reais do provider.

### B4. `apply_patch` com adições line-separated

- **Upstream:** nanobot v0.2.2 #4266
- **Estado atual:** [femtobot/agent/tools/apply_patch.py](./femtobot/agent/tools/apply_patch.py) — auditar.
- **Mudança:**
  1. Garantir que `action: "add"` preserva o `\n` final do `new_text`
     exatamente como enviado.
  2. Não colapsar múltiplas linhas em uma.
- **Arquivos:**
  - [femtobot/agent/tools/apply_patch.py](./femtobot/agent/tools/apply_patch.py).
  - `tests/test_apply_patch.py` (criar) — caso "adição multilinha".
- **Esforço:** S. **Impacto:** Médio.
- **Critério de aceitação:** Adicionar `# header\n# body\n` em arquivo
  vazio resulta em 2 linhas distintas, não 1 colapsada.

### B5. Mover archived summary para o system prompt (KV cache)

- **Upstream:** nanobot v0.2.0 #3711
- **Estado atual:** [femtobot/agent/context.py](./femtobot/agent/context.py) —
  auditar onde o summary arquivado do Consolidator entra.
- **Mudança:**
  1. Se entra em `messages` dinamicamente: mover para um bloco
     `<consolidated_history>` no system prompt template.
  2. Se já entra no system: no-op.
- **Arquivos:**
  - [femtobot/agent/context.py](./femtobot/agent/context.py).
  - `femtobot/templates/agent/` — adicionar snippet se necessário.
- **Esforço:** S. **Impacto:** Médio (latência + custo em providers com
  cache).
- **Critério de aceitação:** Prompt token count cai ~5% em sessões
  longas; cache hit rate sobe (medir com OpenAI/Anthropic logs).

### B6. `/goal complete` slash command

- **Upstream:** nanobot v0.2.0 #3788
- **Estado atual:** [docs/cli-reference.md](./docs/cli-reference.md) linha 102-105
  lista `/goal` e `/goal <text>` mas não `complete_goal` ou `/goal
  complete`.
- **Mudança:**
  1. Adicionar handler `/goal complete` em
     [femtobot/command/builtin.py](./femtobot/command/builtin.py).
  2. Atualizar `docs/cli-reference.md` e `docs/memory.md`.
- **Arquivos:**
  - [femtobot/command/builtin.py](./femtobot/command/builtin.py).
  - [docs/cli-reference.md](./docs/cli-reference.md).
- **Esforço:** XS. **Impacto:** Médio (completa o feature de long-task).
- **Critério de aceitação:** `/goal complete` marca o goal como
  `status: "completed"` e runner wall timeout volta ao default.

---

## 4. Lote C — Refator de arquitetura (Milestone v0.0.5)

> 5 itens · ~6–8 dias · PRs #C1–#C5 · Branch: `release/v0.0.5-architecture`

### C1. Doc + helper `AgentLoop.from_config()`

- **Upstream:** nanobot v0.2.0 #3708
- **Estado atual:** [femtobot/femtobot.py](./femtobot/femtobot.py) tem
  `Femtobot.from_config()` (facade). O `AgentLoop` em
  [femtobot/agent/loop.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/loop.py) é construído
  internamente, sem factory exposta.
- **Mudança:**
  1. Adicionar `AgentLoop.from_config(config: Config, *,
     session_manager=None) -> AgentLoop`.
  2. Refator `Femtobot.from_config()` para chamar
     `AgentLoop.from_config()` e embrulhar.
  3. Documentar em [docs/python-sdk.md](./docs/python-sdk.md) com exemplo
     de uso direto do `AgentLoop` (sem facade).
- **Arquivos:**
  - [femtobot/agent/loop.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/loop.py).
  - [femtobot/femtobot.py](./femtobot/femtobot.py).
  - [docs/python-sdk.md](./docs/python-sdk.md).
- **Esforço:** S. **Impacto:** Médio (clareza API para embedders).
- **Critério de aceitação:** Exemplo em `docs/python-sdk.md` compila
  e roda; testes passam.

### C2. Capabilities em tools (plugin architecture explícita)

- **Upstream:** nanobot v0.2.0 #3729
- **Estado atual:** Já existe `_plugin_discoverable = True` +
  `ToolLoader`. Auditar o que falta.
- **Mudança:**
  1. Adicionar `capabilities: list[str] = []` à base class `Tool`.
  2. Refator registry para expor capabilities.
  3. Adicionar capability discovery no `Femtobot.status` (já tem
     "tools" no `/status`).
  4. Adicionar `femtobot tools list --capability <name>` CLI.
- **Arquivos:**
  - [femtobot/agent/tools/base.py](./femtobot/agent/tools/base.py).
  - [femtobot/agent/tools/registry.py](./femtobot/agent/tools/registry.py).
  - [femtobot/cli/commands.py](./femtobot/cli/commands.py).
  - [docs/tools.md](./docs/tools.md).
- **Esforço:** S. **Impacto:** Médio.
- **Critério de aceitação:** `femtobot tools list --capability
  long-running` lista só tools que se anunciam como tal.

### C3. Extension registry local (`extensions.json`)

- **Upstream:** nanobot v0.2.1 #4046
- **Estado atual:** Não existe. Femtobot é **fortemente MCP-centric**.
- **Mudança:**
  1. Adicionar `extensions.json` no instance dir como opt-in para
     extensões não-MCP (e.g. scripts locais).
  2. Schema:
     ```json
     {
       "extensions": {
         "name": {
           "kind": "cli",
           "command": "...",
           "args": ["..."],
           "capabilities": ["..."]
         }
       }
     }
     ```
  3. Carregar em `ToolLoader` como uma fonte adicional de tools.
  4. Adicionar `/extensions status|reload` slash command (espelhando
     `/mcp`).
- **Arquivos:**
  - `femtobot/agent/tools/extensions.py` (novo).
  - [femtobot/agent/tools/loader.py](./femtobot/agent/tools/loader.py).
  - [femtobot/command/builtin.py](./femtobot/command/builtin.py).
  - `docs/` — `extensions.md` (novo).
- **Esforço:** M. **Impacto:** Médio (caminho de crescimento).
- **Critério de aceitação:** Extension declarada em `extensions.json`
  aparece como tool e pode ser invocada; `/extensions status` lista.

### C4. CLI Apps unificados com MCP (preset setup, capability mentions)

- **Upstream:** nanobot v0.2.1 #3963, #3991, #3979
- **Estado atual:** Femtobot já tem `mcp-router` skill. Falta a
  *unificação explícita* entre "CLI Apps" (non-MCP) e MCP.
- **Mudança:**
  1. Adicionar `kind: "mcp" | "cli" | "http"` ao `MCPServerConfig` (ou
     unificar em `ExtensionConfig`).
  2. Adicionar `capability_mentions: list[str]` ao
     `MCPServerConfig` para que o system prompt exponha tags
     (`[long-running, safe-mode:confirm]`).
  3. Já tem `tool_hints.py` com tags — auditar e generalizar.
- **Arquivos:**
  - [femtobot/config/schema.py](./femtobot/config/schema.py).
  - [femtobot/agent/tools/mcp.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/mcp.py).
  - [femtobot/utils/tool_hints.py](./femtobot/utils/tool_hints.py).
  - `docs/mcp.md` — adicionar seção "Capability mentions".
- **Esforço:** M. **Impacto:** Médio.
- **Critério de aceitação:** Tool MCP com `capability_mentions:
  ["long-running"]` aparece com essa tag no system prompt.

### C5. `/model` wizard no `femtobot onboard`

- **Upstream:** nanobot v0.2.1 #3890
- **Estado atual:** `femtobot onboard` é não-wizard por default; config
  manual.
- **Mudança:**
  1. Adicionar prompt interativo para escolher model + provider no
     primeiro onboard.
  2. Validar API key connectivity (faz um `ping` ao provider).
  3. Salvar preset no `modelPresets` automaticamente.
- **Arquivos:**
  - [femtobot/cli/commands.py](./femtobot/cli/commands.py).
  - [docs/quick-start.md](./docs/quick-start.md).
- **Esforço:** S. **Impacto:** Baixo-Médio (DX no primeiro uso).
- **Critério de aceitação:** Wizard interativo de model + provider
  funciona, valida key, persiste preset.

---

## 5. Lote D — Provedores e cold-start (Milestone v0.0.6)

> 4 itens · ~3–4 dias · PRs #D1–#D4 · Branch: `release/v0.0.6-providers`

### D1. AWS Bedrock Converse nativo

- **Upstream:** nanobot v0.2.0 #3574
- **Estado atual:** Femtobot tem 33 providers em
  [femtobot/providers/registry.py](./femtobot/providers/registry.py) mas não tem
  Bedrock.
- **Mudança:**
  1. Adicionar `ProviderSpec(name="bedrock", backend="bedrock",
     keywords=("bedrock", "anthropic.claude", "amazon.nova"))` no
     registry.
  2. Implementar `BedrockProvider` em
     `femtobot/providers/bedrock.py` usando `boto3` (lazy import,
     não quebrar quem não tem boto3).
  3. Suportar SigV4 via `AWS_*` env vars.
  4. Suportar `BEDROCK_REGION`, `BEDROCK_API_KEY` (session token) como
     alternative path.
- **Arquivos:**
  - `femtobot/providers/bedrock.py` (novo).
  - [femtobot/providers/registry.py](./femtobot/providers/registry.py).
  - [femtobot/providers/factory.py](./femtobot/providers/factory.py).
  - [femtobot/config/schema.py](./femtobot/config/schema.py).
  - `pyproject.toml` — adicionar `boto3` como extra opcional
     `bedrock = ["boto3>=1.34.0"]`.
  - [docs/configuration.md](./docs/configuration.md).
- **Esforço:** M. **Impacto:** Médio.
- **Critério de aceitação:** Provider Bedrock configurado com AWS
  env vars consegue chamar `claude-3.5-sonnet` via Converse API.

### D2. `extraQuery` (já em A11)

> Já coberto por A11. **Não duplicar.** Veja §2.A11.

### D3. Disable proxy para endpoints locais

- **Upstream:** nanobot v0.2.2 #4367
- **Estado atual:** [femtobot/agent/tools/web.py](./femtobot/agent/tools/web.py) tem
  `proxy` no config mas [femtobot/providers/openai_compat_provider.py](./femtobot/providers/openai_compat_provider.py)
  herda `HTTPS_PROXY`/`HTTP_PROXY` do ambiente. Usuários tropeçam em
  "Ollama atrás de corp proxy".
- **Mudança:**
  1. Em `openai_compat_provider.py`, ao construir o `httpx.AsyncClient`:
     - Se `apiBase` é `localhost`, `127.0.0.1`, ou `::1`:
       `trust_env=False`.
     - Caso contrário: `trust_env=True` (default).
  2. Log debug quando a decisão é tomada.
- **Arquivos:**
  - [femtobot/providers/openai_compat_provider.py](./femtobot/providers/openai_compat_provider.py).
  - `tests/test_provider_proxy.py` (criar).
- **Esforço:** S. **Impacto:** Médio (UX comum).
- **Critério de aceitação:** Com `HTTPS_PROXY=http://corp-proxy:8080`
  setado, Ollama em `http://127.0.0.1:11434` é chamado sem proxy.

### D4. Cold-start do gateway A2A (deferido)

- **Upstream:** nanobot v0.2.1 #3918
- **Estado atual:** [docs/cli-reference.md](./docs/cli-reference.md) linha 144-160
  afirma que `femtobot gateway` é placeholder Stage 2.
- **Mudança:** **DEFERIDO** até o gateway ser implementado. Quando
  o Stage 2 entrar:
  1. Lazy import de providers (não `import boto3` no topo de
     `providers/__init__.py`).
  2. Lazy import de MCP SDK.
  3. Pool de MCP clients reusáveis (não reconectar por request).
  4. Cache de tool registry por session.
- **Esforço:** S. **Impacto:** Alto (mas só pós-Stage 2).
- **Critério de aceitação (quando aplicável):** Cold-start
  `femtobot gateway` <500ms (medido com `time femtobot gateway &
  /health`).

---

## 6. Lote E — Hardening pós-release (Milestone v0.0.7)

> 11 itens · ~2–3 dias · PRs #E1–#E11 · Branch: `release/v0.0.7-hardening`

> **Foco:** apenas bugfixes. Zero novas features, zero breaking
> changes.  Compatível com v0.0.6 — todos os releases até aqui
> introduziram features; Lote E é puramente de qualidade. Inclui
> sweep de `ruff check` (131 erros auto-fixados), corrida do test
> suite, e revisão manual profunda (AttributeError em runtime,
> race conditions, security, smoke tests de CLI).

### E1. CRITICAL: `WebSocketChannel.gateway` não atribuído

- **Arquivo:** [femtobot/channels/websocket.py](./femtobot/channels/websocket.py)
- **Estado atual:** `gateway: GatewayServices = None` é aceito no
  `__init__` mas nunca guardado em `self.gateway`.
  `_maybe_push_active_goal_state` lia `self.gateway.session_manager`
  direto.
- **Mudança:** `self.gateway = gateway` no `__init__` + guarda
  `if self.gateway is None or self.gateway.session_manager is None`.
- **Esforço:** XS. **Impacto:** CRÍTICO (AttributeError garantido).
- **Critério de aceitação:** `WebSocketChannel().gateway is None`
  e `WebSocketChannel(gateway=G).gateway is G`. Test em
  `tests/test_websocket_channel_critical.py`.

### E2. HIGH: Race em `AgentLoop._session_locks.setdefault`

- **Arquivo:** [femtobot/agent/loop.py](./femtobot/agent/loop.py)
- **Estado atual:** `dict.setdefault(...)` cria `asyncio.Lock` na
  primeira chamada. Duas coroutines concorrentes podiam criar
  locks diferentes para o mesmo `session_key` (TOCTOU).
- **Mudança:** novo método `AgentLoop._acquire_session_lock()`
  com double-check + `self._session_locks_lock`. Mesma técnica
  do `Femtobot._acquire_session_lock` (B1).
- **Esforço:** XS. **Impacto:** HIGH (race em serialização).
- **Critério de aceitação:** 50 acquires concorrentes na mesma
  key retornam **o mesmo** `asyncio.Lock`. Test em
  `tests/test_session_lock_race_fix.py`.

### E3. HIGH: Kill-switch para `shell=True` em skill bodies

- **Arquivo:** [femtobot/cli/md_commands.py](./femtobot/cli/md_commands.py)
- **Estado atual:** `_run_bash_inlines` expande `!`cmd`` com
  `shell=True` direto.
- **Mudança:** env var `FEMTOBOT_NO_BASH_INLINE=1` como global
  kill-switch (substitui por placeholder sem chegar ao shell);
  audit log em toda expansão.
- **Esforço:** XS. **Impacto:** HIGH (segurança contra skill
  body adulterada).
- **Critério de aceitação:** com `FEMTOBOT_NO_BASH_INLINE=1`,
  `subprocess.run` não é invocado. Test em
  `tests/test_md_commands_kill_switch.py`.

### E4. CRITICAL: `AgentLoop.from_config` retornava sem assignar `instance`

- **Arquivo:** [femtobot/agent/loop.py](./femtobot/agent/loop.py)
- **Estado atual:** o `from_config` original tinha `return
  cls(...)` (expressão solta) seguido de `instance._config = config`
  — `instance` nunca era definido (F821).  `/style` crashava
  em runtime.
- **Mudança:** `instance = cls(...)` antes do assign.
- **Esforço:** XS. **Impacto:** CRÍTICO.
- **Critério de aceitação:** lint passa, e `loop._config` é
  acessível depois de `from_config`.

### E5. HIGH: `atomic_write_text` com `from contextlib import suppress` no meio do try

- **Arquivo:** [femtobot/utils/gitstore.py](./femtobot/utils/gitstore.py)
- **Estado atual:** `suppress` era importado dentro do try mas
  usado no except logo abaixo. `UnboundLocalError` em qualquer
  write que falhasse.
- **Mudança:** `suppress` movido para o import do topo.
- **Esforço:** XS. **Impacto:** HIGH (todos os writes de
  `dream_cursor` / `history.jsonl` passam por aqui).
- **Critério de aceitação:** exception durante write não deixa
  `.tmp` órfão. Test em `tests/test_gitstore_atomic_write.py`.

### E6. MEDIUM: `RenderableType` undefined em `stream.py`

- **Arquivo:** [femtobot/cli/stream.py](./femtobot/cli/stream.py)
- **Estado atual:** type annotation sem import (F821).
- **Mudança:** adicionado ao `from rich.console import Console, RenderableType`.
- **Esforço:** XS. **Impacto:** MEDIUM (runtime non-issue mas
  anotação quebrada).
- **Critério de aceitação:** lint passa.

### E7. MEDIUM: `Femtobot.run` `_extra_hooks` vazava em timeout

- **Arquivo:** [femtobot/femtobot.py](./femtobot/femtobot.py)
- **Estado atual:** restore de `_extra_hooks` ficava fora do
  `try/finally` do lock; em timeout, o `SDKCaptureHook` vazava
  para a próxima `run()`.
- **Mudança:** `try/finally` aninhado garantindo restore em
  todos os paths (happy, timeout, exception).
- **Esforço:** XS. **Impacto:** MEDIUM.
- **Critério de aceitação:** lock timeout *não* altera
  `_extra_hooks` para próxima run. Já coberto por testes B1.

### E8. MEDIUM: `AgentLoop._config` inexistente sem `from_config`

- **Arquivo:** [femtobot/agent/loop.py](./femtobot/agent/loop.py)
- **Mudança:** `self._config: Any = None` no `__init__`.
- **Esforço:** XS. **Impacto:** MEDIUM.

### E9. MEDIUM: `trust_env=False` quebrava HTTPS local com cert custom

- **Arquivo:** [femtobot/providers/openai_compat_provider.py](./femtobot/providers/openai_compat_provider.py)
- **Mudança:** aplicar `trust_env=False` apenas quando scheme é
  `http://`; HTTPS local mantém `trust_env=True` (honra
  `SSL_CERT_FILE`).
- **Esforço:** XS. **Impacto:** MEDIUM.
- **Critério de aceitação:** `https://127.0.0.1:8443/v1` tem
  `trust_env=True`. Test em `tests/test_proxy_bypass_d3.py`.

### E10. LOW: `femtobot tools list` crashava em AttributeError

- **Arquivo:** [femtobot/cli/commands.py](./femtobot/cli/commands.py)
- **Mudança:** `except Exception` → `except (TypeError, ValueError, RuntimeError, AttributeError)`.
- **Esforço:** XS. **Impacto:** LOW.

### E11. LOW: `keybindings._Handler` usava `handler_self` em vez de `self`

- **Arquivo:** [femtobot/cli/keybindings.py](./femtobot/cli/keybindings.py)
- **Mudança:** renormalizado.
- **Esforço:** XS. **Impacto:** LOW.

### Validation

- **`uv run ruff check .`**: All checks passed! (zero erros).
- **`uv run pytest tests/`**: 536 passed, 0 failures.
- **CLI smoke**: `femtobot --help`, `femtobot tools list
  --show-capabilities`, `from femtobot.femtobot import Femtobot`.

### Critério de aceitação geral

- 11 bugs E1-E11 corrigidos.
- 30 novos testes de regressão (não classificados sob os
  markers A/B/C/D — são puramente hardening).
- Ruff 100% limpo.
- 100% compat com v0.0.6.

---

## 7. Estratégia de testes

### 6.1 Cobertura obrigatória por lote

Cada PR adiciona:

- **Lote A (segurança):**
  - `tests/test_config_loader.py` — fail-fast (A1), strict mode toggle.
  - `tests/test_mcp_startup_notify.py` — unsafe URL pre-flight (A2).
  - `tests/test_web_fetch.py` — redirect para IP privado (A3).
  - `tests/test_security_network.py` — IPv6-mapped (A4).
  - `tests/test_fallback_provider.py` — primary error log (A5, A14).
  - `tests/test_memory_dream.py` — cursor atomic (A6).
  - `tests/test_workspace_policy.py` — soft boundary (A8).
  - `tests/test_autocompact_race.py` — race fix (A9).
  - `tests/test_history_malformed.py` — ignore malformados (A10).
  - `tests/test_provider_extra_query.py` (A11).
  - `tests/test_anthropic_sanitize.py` (A12).
  - `tests/test_image_placeholder.py` (A13).

- **Lote B (durabilidade):**
  - `tests/test_session_lock.py` — concurrent calls (B1).
  - `tests/test_sustained_goal.py` — goal não aborta (B2).
  - `tests/test_api_usage.py` — usage real (B3).
  - `tests/test_apply_patch.py` — adições line-separated (B4).
  - `tests/test_context_kv_cache.py` — system prompt stability (B5).
  - `tests/test_goal_complete.py` — `/goal complete` (B6).

- **Lote C (refator):**
  - `tests/test_agent_loop_factory.py` (C1).
  - `tests/test_tool_capabilities.py` (C2).
  - `tests/test_extensions.py` (C3).
  - `tests/test_mcp_capability_mentions.py` (C4).
  - `tests/test_onboard_wizard.py` (C5).

- **Lote D (providers):**
  - `tests/test_bedrock_provider.py` (D1).
  - `tests/test_provider_proxy.py` (D3).

- **Lote E (hardening):**
  - `tests/test_websocket_channel_critical.py` (E1) — `gateway` não atribuído.
  - `tests/test_session_lock_race_fix.py` (E2) — race em `setdefault`.
  - `tests/test_md_commands_kill_switch.py` (E3) — `FEMTOBOT_NO_BASH_INLINE`.
  - `tests/test_gitstore_atomic_write.py` (E5) — `suppress` no `atomic_write_text`.
  - `tests/test_femtobot_facade.py` (E7, E8, E11) — hooks restore + `_config` default.
  - Marcador novo: nenhum (Lote E é puramente hardening sem marker dedicado).

### 6.2 Testes de regressão de segurança (obrigatórios)

Cada um destes **deve** existir antes de merge do Lote A:

1. `test_ssrf_ipv6_mapped.py` — `::ffff:127.0.0.1` é bloqueado.
2. `test_mcp_unsafe_url.py` — `http://169.254.169.254/` rejeitado
   pre-flight.
3. `test_web_fetch_redirect.py` — redirect para IP privado é
   bloqueado.
4. `test_workspace_soft_boundary.py` — escrita fora do workspace é
   warning retentável, não crash.

### 6.3 Convention

- Marcadores: `@pytest.mark.security` para os de regressão.
- Fixture `tmp_instance` que cria `.femtobot_test_<uuid>/` em
  `tmp_path` e limpa.
- Sem mock de `socket.getaddrinfo` para testes de SSRF — usar
  `127.0.0.1` literal (não resolve).

---

## 7. Estratégia de release

### 7.1 Versioning

| Versão | Lote | Data alvo | Notas |
|---|---|---|---|
| `v0.0.3` | A | T+1 semana | Bugfix release. Compat com v0.0.2. |
| `v0.0.4` | B | T+2 semanas | Minor (new feature: usage). |
| `v0.0.5` | C | T+4 semanas | Minor (refator + extensions). |
| `v0.0.6` | D | T+5 semanas | Minor (Bedrock, proxy). |
| `v0.0.7` | E | T+6 semanas | Bugfix release. Compat com v0.0.6. |

### 7.2 Branches

```
main                  (v0.0.2 → v0.0.6)
├── release/v0.0.3-stability     (A)
├── release/v0.0.4-durability   (B)
├── release/v0.0.5-architecture (C)
└── release/v0.0.6-providers    (D)
```

Cada `release/vX.Y.Z-*` é branch de integração. PRs individuais
(`feat/A1-...`, `fix/A2-...`) merge em `main` direto, mas só saem
em release após a barra de testes passar.

### 7.3 CHANGELOG entries (template)

Para cada release:

```markdown
## [0.0.3] — YYYY-MM-DD

### Security
- (A2) Reject unsafe MCP HTTP URLs before TCP probe (ref: nanobot #4123).
- (A3) Validate redirect targets in web_fetch (ref: nanobot #3928).
- (A4) Block IPv6-mapped IPv4 addresses in SSRF guard (ref: nanobot #4086).

### Fixed
- (A1) Optional fail-fast on invalid config (gated by FEMTOBOT_STRICT_CONFIG_LOAD).
- (A6) dream_cursor advances only after commit succeeds (ref: nanobot #3631).
- (A7) Atomic write for .dream_cursor + corruption detection.
- (A8) Soft workspace boundary with retry-throttle (ref: nanobot #3614).
- (A9) AutoCompact/Consolidator race fix (ref: nanobot #3881).
- (A10) Ignore malformed history entries + monotonic cursor.

### Added
- (A5) Log primary error before fallback (ref: nanobot #4385).
- (A11) extraQuery config for OpenAI-compat providers.
- (A14) Recognize arrearage/欠费 as fallbackable errors.
```

### 7.4 Migrações / back-compat

- **A1:** gated por env var; default lenient.
- **A8:** novo behavior opt-in via flag de schema; default é o
  comportamento atual.
- **B1:** novo campo `RunResult.usage` (default `None`); back-compat
  preservada.
- **B3:** breakage mínimo: clients que assumiam `usage = 0` vão
  começar a ver valores reais.
- **C3:** schema novo (`extensions.json`); ausência = no-op.
- **D1:** extra opcional `boto3`; ausência = no-op.

### 7.5 Comunicação

- Anunciar cada release em `femtobot` Gitea/CHANGELOG.
- Cross-post link no `percival.OS` se aplicável.
- Issue tracker: criar label `from-nanobot-sync` para tracking.

---

## 8. Riscos globais e mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Backward-compat quebrada | Média | Alto | Gating por env var + testes de compat em CI |
| Race conditions introduzidas em B1 | Baixa | Alto | Stress tests com `asyncio.gather` + timeout curto |
| Bedrock auth quebra em D1 | Média | Médio | Extra opcional + smoke test contra sandbox AWS |
| Refator C2 quebra tool loading | Baixa | Alto | Feature flag `FEMTOBOT_USE_PLUGIN_ARCH` |
| Mudança em A1 quebra deployments | Média | Alto | Default lenient + opt-in strict via env var |
| Cold-start D4 não atinge meta | Baixa | Médio | Medir baseline antes; aceitar meta relaxada |
| Docs desatualizados | Alta | Baixo | Atualizar CHANGELOG + cross-links no mesmo PR |

---

## 9. Definition of Done (por lote)

- [ ] Todos os itens do lote merged em `main`.
- [ ] Cobertura de testes do lote ≥85% para arquivos tocados.
- [ ] `uv run ruff check .` passa.
- [ ] `uv run pytest tests/ -x` passa.
- [ ] CHANGELOG atualizado com a entrada de release.
- [ ] `docs/configuration.md`/`docs/cli-reference.md`/`docs/security.md`
      refletem as mudanças.
- [ ] Cross-links do [RELEASE_PROPAGATION_REPORT.md](./RELEASE_PROPAGATION_REPORT.md)
      atualizados com os PRs merged.
- [ ] Smoke test manual: `femtobot onboard && femtobot agent -m "Hello"`
      funciona contra uma das instâncias de teste.

---

## 10. Apêndice — mapa de arquivos

| Arquivo | Lote | Itens |
|---|---|---|
| `femtobot/config/loader.py` | A | A1 |
| `femtobot/config/schema.py` | A, C, D | A1, A11, C4, D1 |
| `femtobot/agent/tools/mcp.py` | A, C | A2, C4 |
| `femtobot/agent/tools/web.py` | A | A3, D3 |
| `femtobot/security/network.py` | A | A4 |
| `femtobot/providers/fallback_provider.py` | A | A5, A14 |
| `femtobot/agent/memory.py` | A, B | A6, A7, A10, B5 |
| `femtobot/agent/autocompact.py` | A | A9 |
| `femtobot/agent/tools/filesystem.py` | A | A8 |
| `femtobot/agent/tools/apply_patch.py` | A, B | A8, B4 |
| `femtobot/providers/openai_compat_provider.py` | A, D | A11, A12, D3 |
| `femtobot/utils/helpers.py` | A | A13 |
| `femtobot/femtobot.py` | B, C | B1, B3, C1 |
| `femtobot/agent/loop.py` | B, C | B1, B5, C1 |
| `femtobot/agent/runner.py` | B | B2, B3 |
| `femtobot/api/server.py` | B | B1, B3 |
| `femtobot/providers/base.py` | B | B3 |
| `femtobot/command/builtin.py` | B, C | B6, C3 |
| `femtobot/agent/tools/base.py` | C | C2 |
| `femtobot/agent/tools/registry.py` | C | C2 |
| `femtobot/agent/tools/extensions.py` (novo) | C | C3 |
| `femtobot/agent/tools/loader.py` | C | C3 |
| `femtobot/utils/tool_hints.py` | C | C4 |
| `femtobot/providers/bedrock.py` (novo) | D | D1 |
| `femtobot/providers/factory.py` | D | D1 |
| `femtobot/providers/registry.py` | D | D1 |
| `femtobot/cli/commands.py` | C, E | C5, E10 |
| `femtobot/channels/websocket.py` | E | E1 |
| `femtobot/cli/md_commands.py` | E | E3 |
| `femtobot/cli/stream.py` | E | E6 |
| `femtobot/cli/keybindings.py` | E | E11 |
| `femtobot/utils/gitstore.py` | E | E5 |
| `pyproject.toml` | D, E | D1, E (ruff ignore E402) |
| `docs/configuration.md` | A, C, D | A1, A11, C4, D1 |
| `docs/cli-reference.md` | A, B, C | A1, B6, C5 |
| `docs/security.md` | A | A4, A8 |
| `docs/extensions.md` (novo) | C | C3 |
| `docs/mcp.md` | C | C4 |
| `docs/python-sdk.md` | C | C1 |
| `docs/openai-api.md` | B | B3 |
| `docs/memory.md` | B | B6 |
| `CHANGELOG.md` | A, B, C, D | (todos) |
| `tests/test_*.py` | todos | (todos) |
