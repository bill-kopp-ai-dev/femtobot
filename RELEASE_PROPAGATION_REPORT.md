# Relatório: Propagação de Melhorias do nanobot (v0.2.0 → v0.2.2) para o femtobot

> **Data:** 2026-07-09
> **Escopo:** Avaliação dos releases v0.2.0, v0.2.1 e v0.2.2 do upstream
> [HKUDS/nanobot](https://github.com/HKUDS/nanobot/releases) frente ao estado
> atual do femtobot v0.0.2.
>
> **Premissa:** femtobot é uma derivativa focada em **CLI-first + A2A + Docker**
> para o ecossistema percival.OS, com superfície deliberadamente pequena
> (~14k LOC, 13 tools nativas, 33 provedores, 1 canal: websocket). Muitas
> features upstream que dependem de WebUI/Slack/Teams/email/etc. **não se
> aplicam** e são marcadas como `N/A`. O relatório foca apenas no que tem
> fit real com a filosofia do projeto.

---

## TL;DR — Top 10 itens recomendados

| # | Origem | PR nanobot | Item | Esforço | Impacto femtobot |
|---|---|---|---|---|---|
| 1 | v0.2.0 | #3714 | `fallbackModels` (já existe) + `log primary error before fallback` | XS | Alto |
| 2 | v0.2.0 | #3641 | `toolHintMaxLength` (já existe) | — | — |
| 3 | v0.2.0 | #3574 | Suporte a **AWS Bedrock Converse** nativo | M | Médio |
| 4 | v0.2.0 | #3788/#3855 | **Long-task / goal ativo** (já existe `goal_state`) + ampliar timeout wall | S | Alto |
| 5 | v0.2.0 | #3707 | Provider **NVIDIA NIM** | XS | Baixo-Médio |
| 6 | v0.2.0 | #3708/#3715 | Refatorar `AgentLoop` em `from_config()` + state machine | M | Alto (manutenibilidade) |
| 7 | v0.2.0 | #3729 | Plugin architecture para tools (já parcialmente existe via `_plugin_discoverable`) | S | Médio |
| 8 | v0.2.0 | #3711 | Mover **arquivo de summary arquivado para o system prompt** (estabilidade de KV cache) | S | Médio |
| 9 | v0.2.0 | #3606 | `jobs.json` com escrita atômica + detecção de corrupção | S | Alto |
| 10 | v0.2.0 | #3631/#3660 | `dream_cursor` só avança em batches completos + restore correto | XS | Alto |
| 11 | v0.2.0 | #3614 | Soft workspace boundary com retry-throttle (em vez de crash) | S | Médio |
| 12 | v0.2.1 | #3881 | Fix race entre AutoCompact e Consolidator | S | Alto |
| 13 | v0.2.1 | #3918 | **Cold-start do gateway** ~4.6s → ~480ms | S | Alto (UX) |
| 14 | v0.2.1 | #3999 | Impedir runner de sair enquanto goal sustentado está ativo | XS | Médio |
| 15 | v0.2.1 | #3963/#3991 | **CLI Apps / unificação com MCP** (preset setup, capability mentions) | M | Médio |
| 16 | v0.2.1 | #3935 | Canal **Signal** | S | Baixo |
| 17 | v0.2.1 | #3928 | Validar redirect targets antes de web_fetch | XS | Médio (segurança) |
| 18 | v0.2.1 | #4086 | Normalizar IPv6-mapped IPv4 em SSRF | XS | Médio (segurança) |
| 19 | v0.2.1 | #4104 | Per-session lock em `process_direct` (idempotência) | S | Alto (concorrência) |
| 20 | v0.2.2 | #4135/#4115 | **Refator WebUI runtime state no event bus** (N/A femtobot) | — | — |
| 21 | v0.2.2 | #4123 | **Reject unsafe MCP HTTP URLs antes do probe** (SSRF) | S | Alto |
| 22 | v0.2.2 | #4146 | Canal **Napcat (QQ)** | S | Baixo |
| 23 | v0.2.2 | #4162 | Suporte a **attachments no canal email** (N/A femtobot) | — | — |
| 24 | v0.2.2 | #4202 | Clarificar política de escrita do workspace | XS | Médio (docs + validação) |
| 25 | v0.2.2 | #4266 | `apply_patch` com adições line-separated | S | Médio |
| 26 | v0.2.2 | #4275 | **Fail-fast em config inválida** (hoje femtobot cai no default silencioso) | S | Alto (DX) |
| 27 | v0.2.2 | #4315 | Ignorar history entries malformados | XS | Médio |
| 28 | v0.2.2 | #4367 | Disable proxy para endpoints locais, manter para cloud | S | Médio |
| 29 | v0.2.2 | #4356 | Sanitizar tool_use/tool_result IDs no Anthropic | XS | Baixo |
| 30 | v0.2.2 | #4239 | `bwrap` com `HOME` sensato | XS | Baixo |

**Recomendações priorizadas para um PR "sync nanobot v0.2.x" do femtobot:**

1. **Lote A — Estabilidade e segurança** (essencial, XS-S): itens 9, 10, 11,
   12, 17, 18, 21, 26, 27.
2. **Lote B — Durabilidade e concorrência** (alto valor, S): itens 4, 14, 19.
3. **Lote C — Refator de arquitetura** (M, manutenção de longo prazo): itens
   6, 7, 8, 15.
4. **Lote D — Provedores e cold-start** (S/M): itens 3, 5, 13.

O restante é opcional ou N/A para o foco CLI/A2A do femtobot.

---

## 1. Estado atual do femtobot (resumo executivo)

A partir da leitura da documentação, `pyproject.toml`, `architecture.md` e
`registry.py`:

- **v0.0.2** (~14k LOC, 85 módulos, MIT).
- **Stack:** Python 3.11+, Typer+Rich, Pydantic v2, aiohttp, websockets, mcp,
  loguru, jinja2, dulwich (gitstore), tiktoken, pypdf, ddgs/olostep.
- **Tools nativas (13):** `read_file`, `write_file`, `edit_file`,
  `apply_patch`, `list_dir`, `find_files`, `grep`, `exec`, `write_stdin`,
  `list_exec_sessions`, `web_search`, `web_fetch`, `my` (self), `message`.
- **Provedores (33):** openai, anthropic, openrouter, deepseek, groq, zhipu,
  dashscope, vllm, ollama, lmStudio, atomicChat, ovms, gemini, moonshot,
  MiniMax, MiniMaxAnthropic, mistral, stepfun, xiaomiMimo, longcat, antLing,
  aihubmix, siliconflow, novita, volcengine, volcengineCodingPlan, byteplus,
  byteplusCodingPlan, qianfan, nvidia, huggingface, skywork, custom.
- **Sistema de memória:** Consolidator → `history.jsonl` → Dream (cron)
  → `MEMORY.md`/`USER.md`/`SOUL.md` em gitstore local; AutoCompact para
  sessões ociosas.
- **Canais:** `websocket` apenas (alpha, com 3 modos de auth).
- **Runtime:** `AgentLoop` baseado em **state machine explícita** (`TurnState`
  enum: RESTORE / COMPACT / COMMAND / BUILD / RUN / SAVE / RESPOND / DONE) —
  isso é equivalente ao refator `from_config` + state machine do nanobot
  v0.2.0 (#3708, #3715). O femtobot **já chegou lá**.
- **Provider layer:** `FallbackProvider` com circuit breaker, lista branca
  de erros "fallbackable", e o wrapper recursivo-safe.
- **Memory hardening:** `MemoryStore` com `_append_lock = threading.Lock`
  para serializar cursor + append (consistente com #4147 do nanobot v0.2.2).
- **Long-task / goal state:** `session/goal_state.py` já tem `GOAL_STATE_KEY`,
  `sustained_goal_active`, `goal_state_runtime_lines`,
  `runner_wall_llm_timeout_s` — paridade substancial com #3788/#3855 do
  nanobot v0.2.0.
- **OpenAI API:** streaming SSE, per-session locks, sem auth, `usage` zerado
  (roadmap item).
- **SDK Python:** `Femtobot.from_config()` + `RunResult(content, tools_used,
  messages)` — já expõe `tools_used` e `messages` (#3620 do nanobot v0.2.0
  já foi incorporado).

**Diferenças filosóficas em relação ao nanobot upstream:**

- Sem WebUI. Sem channels sociais (Slack/Telegram/Feishu/Email/Teams/QQ/Signal).
- Sem desktop shell.
- Foco em A2A + Docker (Stage 2) e em ser worker leve para `percival.OS`.
- Documentação é o produto principal (15 docs `.md`).
- Test suite está em reconstrução (vide `CHANGELOG.md`).

---

## 2. Análise por release

### 2.1 v0.2.0 — "The agent learned to hold a goal"

**Contexto upstream:** 105 PRs, 20 novos contribuidores. Foco em
durabilidade (long-task / goal ativo), WebUI shipped-in-wheel, 5 novos
provedores, refator profundo do loop, segurança SSRF, image generation.

#### 2.1.1 Itens com fit direto (recomendados)

**A) Long-task / goal ativo — [#3788](https://github.com/HKUDS/nanobot/pull/3788), [#3855](https://github.com/HKUDS/nanobot/pull/3855)**

*O que o nanobot ganhou:* tool `long_task` + `/goal` + `complete_goal`.
O goal ativo é espelhado no Runtime Context a cada turno, sobrevive à
compactação, e a janela de wall-clock timeout do LLM **aumenta
automaticamente** enquanto o goal está ativo. Streaming cai num timeout
idle em vez de wall hard para não cortar modelos lentos no meio do
pensamento.

*Estado femtobot:* **Quase tudo já existe** —
`session/goal_state.py` implementa `sustained_goal_active`,
`goal_state_runtime_lines`, `runner_wall_llm_timeout_s`, e a flag
`max_tool_iterations` parece já ser honrada (vide [docs/cli-reference.md](./docs/cli-reference.md) que documenta
`/goal`/`/status`). O time precisa apenas:

1. **Auditar** se `runner_wall_llm_timeout_s` é de fato consultado em todos
   os call-sites do provider (ver `agent/loop.py` e `agent/runner.py`).
2. **Adicionar** fallback de idle timeout para streaming — verificar
   se o femtobot já tem ou não; no nanobot, esse era o ponto da #3855.
3. **Adicionar `/goal complete`** se ainda não estiver (cli-reference lista
   `/goal` e `/goal <text>`, mas não menciona `complete_goal`).

*Esforço:* S. *Impacto:* Alto (permite fluxos longos, alinhado ao roadmap
A2A onde um worker pode rodar por horas).

**B) `fallbackModels` com log primário — [#3756](https://github.com/HKUDS/nanobot/pull/3756), [#4385](https://github.com/HKUDS/nanobot/pull/4385)**

*O que o nanobot ganhou:* lista de fallback por turn com circuit-breaker
e **#4385 adiciona log do erro primário antes de cair no fallback** (debug
crucial).

*Estado femtobot:* Já tem `FallbackProvider` com
`_FALLBACK_ERROR_KINDS`, `_PRIMARY_FAILURE_THRESHOLD=3`,
`_PRIMARY_COOLDOWN_S=60` em [femtobot/providers/fallback_provider.py](file:///home/bill/Codes/agents/femtobot/femtobot/providers/fallback_provider.py).

*Gap:* Verificar se `Femtobot/fallback_provider.py` loga o erro primário
antes de descartar. Se não loga, portar a #4385 é XS. Se loga, está
completo.

*Esforço:* XS. *Impacto:* Alto (debug + observabilidade).

**C) `toolHintMaxLength` — [#3641](https://github.com/HKUDS/nanobot/pull/3641)**

*Estado femtobot:* **Já existe** — `agents.defaults.toolHintMaxLength` no
schema (vide [docs/configuration.md](./docs/configuration.md) linha 61). No-op.

**D) Provider `NVIDIA NIM` — [#3707](https://github.com/HKUDS/nanobot/pull/3707)**

*Estado femtobot:* Já tem `nvidia` no PROVIDERS registry
([docs/configuration.md](./docs/configuration.md) linha 160). No-op.

**E) Provider `LongCat` (OpenAI-compat) — [#3114](https://github.com/HKUDS/nanobot/pull/3114)**

*Estado femtobot:* Já tem `longcat` registrado. No-op.

**F) Refator `AgentLoop.from_config()` + state machine — [#3708](https://github.com/HKUDS/nanobot/pull/3708), [#3715](https://github.com/HKUDS/nanobot/pull/3715)**

*O que o nanobot ganhou:* factory central + `_process_message` reescrito
como state machine funcional.

*Estado femtobot:* O femtobot **já implementa o state machine**:
`TurnState(Enum)` com RESTORE/COMPACT/COMMAND/BUILD/RUN/SAVE/RESPOND/DONE em
[femtobot/agent/loop.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/loop.py#L85-L93).
E o `Femtobot.from_config()` é a facade SDK (já documentada em
[docs/python-sdk.md](./docs/python-sdk.md)). **Paridade alcançada**.

*Gap residual:* Verificar se `AgentLoop` (não `Femtobot`) também tem
`from_config()` para uso em embedders. Hoje o femtobot oferece a facade
`Femtobot.from_config()` em vez de mexer no loop diretamente — abordagem
até mais limpa, mas convém documentar como embedder pode construir um
`AgentLoop` direto.

*Esforço:* XS (doc) / S (refator menor). *Impacto:* Médio (clareza API).

**G) Plugin architecture para tools — [#3729](https://github.com/HKUDS/nanobot/pull/3729)**

*O que o nanobot ganhou:* tools com auto-descrição via plugin.

*Estado femtobot:* Já existe o padrão `_plugin_discoverable = True` +
`ToolLoader` (vide [docs/tools.md](./docs/tools.md) § "Adding a new tool").
`registry.py` é o ponto único de registro. **Paridade substancial**.

*Gap residual:* Falta doc explícita de como escrever uma tool com
capabilities avançadas (streaming progress, side-effect hooks).

*Esforço:* S. *Impacto:* Médio (DX para contribuidores de tools).

**H) Mover arquivo de summary arquivado para o system prompt — [#3711](https://github.com/HKUDS/nanobot/pull/3711)**

*Por que importa:* Estabilidade do KV cache. Quando o summary fica
anexado ao `system` em vez de injetado no histórico, o prefixo do prompt
é estável → cache hits preservados.

*Estado femtobot:* A renderização do prompt vive em
[femtobot/agent/context.py](./femtobot/agent/context.py) — auditar onde
o summary arquivado do Consolidator entra. Se entra em `messages`
dinamicamente, há ganho de performance. Se já entra no system prompt
template, no-op.

*Esforço:* S. *Impacto:* Médio (latência + custo de tokens em providers
com cache, especialmente Anthropic).

**I) Atomic write para `jobs.json` + detecção de corrupção — [#3606](https://github.com/HKUDS/nanobot/pull/3606)**

*O que o nanobot ganhou:* `cron/jobs.json` com escrita atômica
(tempfile + rename) e detecção de arquivo corrupto (não sobrescreve
silenciosamente).

*Estado femtobot:* O femtobot tem cron de Dream mas não há menção
explícita a `jobs.json` ou a resiliência da escrita. Vale auditar
`agent/memory.py` (Dream trigger) e qualquer persistência de jobs.

*Esforço:* S. *Impacto:* Alto (evita perda de configuração de jobs em
crash abrupto).

**J) `dream_cursor` só avança em batches completos — [#3631](https://github.com/HKUDS/nanobot/pull/3631) + restore correto — [#3660](https://github.com/HKUDS/nanobot/pull/3660)**

*O que o nanobot ganhou:* o cursor do Dream só avança após a
consolidação gravar com sucesso; restore com memory state preserva a
posição.

*Estado femtobot:* O `MemoryStore` tem `_dream_cursor_file` e a
propriedade `git` (gitstore) já é restaurável via `/dream-restore <sha>`.
**Auditar se o cursor é persistido dentro do mesmo commit git
(atomicidade).** Se sim, paridade. Se não, portar a #3631 é XS.

*Esforço:* XS-S. *Impacto:* Alto (evita perda de consolidação em crash).

**K) Soft workspace boundary com retry-throttle — [#3614](https://github.com/HKUDS/nanobot/pull/3614)**

*O que o nanobot ganhou:* violação de workspace vira warning retentável
em vez de crash do loop.

*Estado femtobot:* `tools.restrictToWorkspace` é policy intent
([docs/security.md](./docs/security.md) linha 35) e os writes
validam. Não está claro se o comportamento atual é hard-fail ou soft.
Recomenda-se auditar `agent/tools/filesystem.py` e `apply_patch.py`.

*Esforço:* S. *Impacto:* Médio (resiliência a prompt injection que tenta
escapar do workspace).

**L) Model presets + runtime switching — [#3714](https://github.com/HKUDS/nanobot/pull/3714)**

*Estado femtobot:* **Já tem** `modelPresets` + `modelPreset` no schema
([docs/configuration.md](./docs/configuration.md) linhas 49 e 326-356) +
`agent/model_presets.py` + comando `/model` documentado. **Paridade
alcançada**. Recomendação residual: o upstream depois adicionou um
`/model` wizard no onboard (#3890). Vale considerar o mesmo para o
`femtobot onboard`.

*Esforço:* S. *Impacto:* Baixo-Médio.

**M) Garbage: dead code removal, try/except → `contextlib.suppress`, ruff F-rules — [#3755](https://github.com/HKUDS/nanobot/pull/3755), [#3566](https://github.com/HKUDS/nanobot/pull/3566), [#3672](https://github.com/HKUDS/nanobot/pull/3672)**

*Estado femtobot:* `pyproject.toml` já tem `select = ["E", "F", "I", "N",
"W"]` (linha 149) com alguns ignores. **Paridade parcial**. Vale rodar
`vulture` + `coverage` como o upstream faz para varrer dead code.

*Esforço:* S. *Impacto:* Médio (saúde do código).

**N) WebUI shipped-in-wheel, image generation, BYOK — N/A femtobot**

Femtobot **não embarca WebUI** (decisão arquitetural explícita no README:
"no embedded web UI, no bundled frontend assets"). Esses 25+ PRs
relacionados a WebUI, image-generation tool, BYOK web search, redesign de
settings, etc. são **fora do escopo**.

#### 2.1.2 Itens com fit parcial / discutíveis

- **Bot name/icon configurável — [#3730](https://github.com/HKUDS/nanobot/pull/3730):** Femtobot já tem `botName`/`botIcon` no
  schema (linhas 64-65 do `configuration.md`). No-op.
- **Whisper retry — [#3646](https://github.com/HKUDS/nanobot/pull/3646):** Femtobot tem `cli/voice.py` com
  `transcriptionProvider: "groq" | "openai"`. Auditar se há retry em
  transientes.
- **`origin_message_id` outbound dedup — [#3561](https://github.com/HKUDS/nanobot/pull/3561):** N/A no websocket
  atual, mas relevante quando o gateway HTTP/A2A do Stage 2 entrar.

---

### 2.2 v0.2.1 — "The agent got a real workbench"

**Contexto upstream:** 84 PRs, 17 novos contribuidores. Foco em
WebUI-as-daily-workbench, estabilidade de long-running, extensões
(CLI Apps unificados com MCP), mais providers, e hardening de segurança.

#### 2.2.1 Itens com fit direto (recomendados)

**A) Race entre AutoCompact e Consolidator — [#3881](https://github.com/HKUDS/nanobot/pull/3881)**

*O que o nanobot ganhou:* lock entre as duas operações para evitar
interleaving corrupto.

*Estado femtobot:* O `MemoryStore` já tem `_append_lock =
threading.Lock()` ([femtobot/agent/memory.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/memory.py#L64)). **Mas** o
`AutoCompact` vive em `agent/autocompact.py` e o `Consolidator` em
`agent/memory.py` — verificar se o lock é compartilhado ou se há
janela de race. Como ambos rodam no mesmo loop asyncio e usam o
mesmo store, o `with self._append_lock:` deveria cobrir, mas é o tipo
de bug que só aparece sob carga.

*Esforço:* S. *Impacto:* Alto (consistência de memória).

**B) Cold-start do gateway ~4.6s → ~480ms — [#3918](https://github.com/HKUDS/nanobot/pull/3918)**

*Estado femtobot:* O `femtobot gateway` é placeholder Stage-2
([docs/cli-reference.md](./docs/cli-reference.md) linha 144-160: "currently exposes GET /health and a stub
POST /v1/chat/completions (returns 501 Not Implemented)"). Quando o A2A
gateway for implementado, esta otimização é cópia direta — deferred.

*Esforço:* S. *Impacto:* Alto (UX), **mas só após o gateway ser
implementado**.

**C) Impedir runner de sair enquanto goal sustentado está ativo — [#3999](https://github.com/HKUDS/nanobot/pull/3999) + estender budget de iteração — [#4127](https://github.com/HKUDS/nanobot/pull/4127)**

*Estado femtobot:* `sustained_goal_active` e `runner_wall_llm_timeout_s`
existem em `session/goal_state.py`. Auditar `agent/loop.py` e
`agent/runner.py` para garantir que o loop **não desiste** quando
`status == "active"`.

*Esforço:* XS-S. *Impacto:* Alto (essencial para o cenário de
long-task ser útil).

**D) CLI Apps unificados com MCP — [#3963](https://github.com/HKUDS/nanobot/pull/3963), [#3991](https://github.com/HKUDS/nanobot/pull/3991), [#3979](https://github.com/HKUDS/nanobot/pull/3979), [#4046](https://github.com/HKUDS/nanobot/pull/4046)**

*O que o nanobot ganhou:* "CLI Apps" como caminho de extensão unificado
com MCP, com preset setup, capability mentions, recovery, e um extension
registry.

*Estado femtobot:* Femtobot é **fortemente orientado a MCP**
([docs/mcp.md](./docs/mcp.md) inteiro). O equivalente seria:
1. Adicionar um extension registry file local
   (`extensions.json` no instance dir) que aponta para `uvx`-style
   tools não-MCP.
2. Adicionar `capability_mentions` ao schema do tool registry
   (parcialmente já existe em `tool_hints.py` com tags
   `[long-running, safe-mode:confirm]`).
3. Adicionar `/extensions status|reload|tools` espelhando o `/mcp`.

*Esforço:* M. *Impacto:* Médio (DX + caminho de crescimento além do
MCP).

**E) Per-session lock em `process_direct` — [#4104](https://github.com/HKUDS/nanobot/pull/4104)**

*O que o nanobot ganhou:* lock por session_id para impedir que duas
chamadas concorrentes a `process_direct` na mesma sessão interleave
corrompendo histórico.

*Estado femtobot:* A documentação do OpenAI API server
([docs/openai-api.md](./docs/openai-api.md) linha 192-198) afirma: *"Two
concurrent requests with the same session_id serialize through the lock"*.
**Mas** falta audit no `Femtobot.from_config().run()` (SDK) e no
endpoint A2A do Stage 2.

*Esforço:* S. *Impacto:* Alto (concorrência segura).

**F) Validar redirect targets antes de web_fetch — [#3928](https://github.com/HKUDS/nanobot/pull/3928)**

*Estado femtobot:* `web_fetch` tem SSRF guard ([docs/security.md](./docs/security.md) linha 110-141) mas
não está claro se valida **cada hop** de redirect. Se `httpx`/`aiohttp`
segue redirect para IP privado, o guard atual é bypassável.

*Esforço:* XS. *Impacto:* Médio (segurança real).

**G) Normalizar IPv6-mapped IPv4 em SSRF — [#4086](https://github.com/HKUDS/nanobot/pull/4086)**

*Estado femtobot:* O guard lista `fc00::/7` e `fe80::/10` mas não
menciona `::ffff:0:0/96` (IPv6-mapped IPv4). `aiohttp` segue DNS
resolvido e pode acabar em `::ffff:127.0.0.1` que bypassa o check
literal de string.

*Esforço:* XS. *Impacto:* Médio (segurança real, exploit conhecido
em outras bases).

**H) Falhas de fast em providers — [#4048](https://github.com/HKUDS/nanobot/pull/4048) surface arrearage, [#3864](https://github.com/HKUDS/nanobot/pull/3864) rate-limit PT, [#4009](https://github.com/HKUDS/nanobot/pull/4009) Codex transport blank errors**

*Estado femtobot:* Auditar `FallbackProvider._FALLBACK_ERROR_TOKENS`
(vide [femtobot/providers/fallback_provider.py](file:///home/bill/Codes/agents/femtobot/femtobot/providers/fallback_provider.py#L37-L59))
— já tem `quota_hard_limit`, `insufficient_balance`, mas não
`arrearage`/`欠费`. Adicionar.

*Esforço:* XS. *Impacto:* Médio (UX em cenários de billing).

#### 2.2.2 Itens com fit N/A ou deferido

- **Signal channel — [#3935](https://github.com/HKUDS/nanobot/pull/3935):** Pode ser adicionado (S effort) mas o
  femtobot é deliberadamente CLI-first. Manter como **opção de
  roadmap pós-Stage-2** se houver demanda de comunidade.
- **Telegram webhook mode — [#3996](https://github.com/HKUDS/nanobot/pull/3996):** N/A (sem Telegram).
- **Discord model slash command — [#4031](https://github.com/HKUDS/nanobot/pull/4031):** N/A.
- **WebUI: WebUI features, project workspaces, BYOK, sidebar, etc.:** N/A
  (femtobot não tem WebUI).
- **Search providers (Firecrawl, Exa, Bocha, Keenable, Volcengine):**
  Femtobot tem `Volcengine` (vide [femtobot/agent/tools/web.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/web.py)
  linha 37 `_VOLCENGINE_SEARCH_API_URL`). **Auditar Firecrawl/Exa/Bocha
  como adições de baixo custo** se a comunidade pedir.
- **i18n da WebUI:** N/A.

---

### 2.3 v0.2.2 — "The agent got sturdier"

**Contexto upstream:** 140 PRs, 21 novos contribuidores. Foco em
durabilidade de sessões WebUI, SDK Python de primeira classe, gateway
polish, mais providers/search/ASR, reliability hardening no agent core,
canais sociais, segurança e workspace boundaries.

#### 2.3.1 Itens com fit direto (recomendados)

**A) Fail-fast em config inválida — [#4275](https://github.com/HKUDS/nanobot/pull/4275)**

*O que o nanobot ganhou:* se a config tem erro, o processo morre alto
com mensagem clara em vez de cair no default silencioso.

*Estado femtobot:* [docs/configuration.md](./docs/configuration.md) linha 376-381 admite abertamente:
*"Errors are logged and a default configuration is used as fallback (so a
typo never crashes the agent at startup, but it does mean you silently
lose your overrides — always run `femtobot status` after editing
config.json)."*

*Problema:* O "forgiving by design" do loader é UX-friendly, mas
esconde typos. A recomendação é **manter o fallback para campos
opcionais** mas **falhar-fast para erros estruturais** (JSON inválido,
schema-mismatch em campos obrigatórios, pydantic ValidationError
"fatal").

*Esforço:* S. *Impacto:* Alto (DX — hoje o `status` é a única forma de
detectar isso, e o usuário só descobre depois que o agent "esqueceu"
uma config).

**B) Reject unsafe MCP HTTP URLs antes do probe — [#4123](https://github.com/HKUDS/nanobot/pull/4123)**

*O que o nanobot ganhou:* SSRF guard aplicado **antes** de tentar
conectar num servidor MCP HTTP, impedindo que o próprio startup
vire vetor de SSRF.

*Estado femtobot:* O MCP tem `url: str = ""` no
`MCPServerConfig` ([docs/mcp.md](./docs/mcp.md) linha 30, [docs/configuration.md](./docs/configuration.md) linha 266) e
o guard SSRF é genérico (`security/network.py`). Mas não está claro se
é aplicado no startup do MCP, antes do probe.

*Esforço:* S. *Impacto:* Alto (segurança).

**C) `apply_patch` com adições line-separated — [#4266](https://github.com/HKUDS/nanobot/pull/4266)**

*O que o nanobot ganhou:* `apply_patch` mantém quebras de linha
consistentes em adições de arquivo.

*Estado femtobot:* Auditar [femtobot/agent/tools/apply_patch.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/apply_patch.py) e
comparar com a implementação upstream. Se houver perda de newline
em `action: "add"`, portar a #4266.

*Esforço:* S. *Impacto:* Médio (qualidade de patches gerados).

**D) Clarificar política de escrita do workspace — [#4202](https://github.com/HKUDS/nanobot/pull/4202)**

*Estado femtobot:* [docs/security.md](./docs/security.md) linha 33-49 já documenta
`tools.restrictToWorkspace` mas é ambíguo se aplica a `exec`. Auditar
e adicionar a chamada explícita em `apply_patch` e `write_file` para
que a intent seja verificável em runtime, não só na doc.

*Esforço:* XS-S. *Impacto:* Médio (clareza de contrato).

**E) Disable proxy para endpoints locais, manter para cloud — [#4367](https://github.com/HKUDS/nanobot/pull/4367)**

*Estado femtobot:* `tools.web.proxy` existe. Auditar se
`openai_compat_provider` herda proxy de env (`HTTPS_PROXY`,
`HTTP_PROXY`) e ignora para `localhost`/`127.0.0.1`/`::1`. Hoje
muitos usuários tropeçam em "Ollama atrás de corp proxy".

*Esforço:* S. *Impacto:* Médio (UX comum).

**F) `apply_patch` com adições line-separated — já em C**

**G) Sanitizar tool_use/tool_result IDs no Anthropic — [#4356](https://github.com/HKUDS/nanobot/pull/4356)**

*O que o nanobot ganhou:* regex para validar IDs do Anthropic
(causa comum de 400).

*Estado femtobot:* Auditar `providers/openai_compat_provider.py` ou
wrapper Anthropic para garantir que IDs são sanitizados antes do envio.

*Esforço:* XS. *Impacto:* Baixo-Médio.

**H) `bwrap` com `HOME` sensato — [#4239](https://github.com/HKUDS/nanobot/pull/4239)**

*Estado femtobot:* `tools.exec.sandbox = "bubblewrap"` está documentado
mas **não tem backend wired por default** ([docs/security.md](./docs/security.md) linha 56-78).
Quando alguém implementar o wrapper real, copiar essa lição.

*Esforço:* XS (deferido até a implementação do sandbox). *Impacto:* Baixo.

**I) Workspace write policy + git from subdirs — [#4380](https://github.com/HKUDS/nanobot/pull/4380)**

*O que o nanobot ganhou:* comandos `git` funcionam em subdiretórios
do workspace sem afrouxar path guards.

*Estado femtobot:* Auditar `command_guard.py` — se ele nega `git` em
qualquer path que não seja raiz do workspace, ajustar. Caso comum: o
agent faz `cd subdir && git status` e o guard bloqueia.

*Esforço:* XS. *Impacto:* Médio (UX em projetos multi-repo).

**J) `idle` auto-compact ligado por default — [#4370](https://github.com/HKUDS/nanobot/pull/4370)**

*O que o nanobot ganhou:* o AutoCompact roda por default no
`sessionTtlMinutes` em vez de exigir opt-in.

*Estado femtobot:* `sessionTtlMinutes: 0` é o default
([docs/configuration.md](./docs/configuration.md) linha 68). **Considerar mudar para
algum valor não-zero default** (e.g. 60 min) — alinhado com a tendência
de "default safe". Trade-off: Dream e AutoCompact se sobrepõem em
alguns casos; revisar antes de mudar.

*Esforço:* XS. *Impacto:* Baixo-Médio (default mais seguro).

**K) Garbage malformed history + cursor monotonic — [#4315](https://github.com/HKUDS/nanobot/pull/4315), [#4256](https://github.com/HKUDS/nanobot/pull/4256)**

*O que o nanobot ganhou:* ignora entries malformadas no
history.jsonl + mantém cursor monotônico.

*Estado femtobot:* `MemoryStore._LEGACY_*` regex tratam migração
legada. Auditar se o append atual ignora entries malformadas ou
crasha. Cursor já tem `_append_lock`.

*Esforço:* XS. *Impacto:* Médio (resiliência).

**L) `extra_query` config para OpenAI-compat — [#4217](https://github.com/HKUDS/nanobot/pull/4217)**

*O que o nanobot ganhou:* permite injetar query string na URL do
provider OpenAI-compat.

*Estado femtobot:* O schema `ProviderConfig` tem `extraHeaders` e
`extraBody` ([docs/configuration.md](./docs/configuration.md) linha 150-151) mas não `extraQuery`.
Adicionar se algum provider regional precisar (e.g. para fixar
`?api-version=`).

*Esforço:* XS. *Impacto:* Baixo.

**M) Forward real LLM usage em /v1/chat/completions — [#4310](https://github.com/HKUDS/nanobot/pull/4310)**

*O que o nanobot ganhou:* `usage` real (prompt/completion/total
tokens) em vez de zeros.

*Estado femtobot:* [docs/openai-api.md](./docs/openai-api.md) linha 130 admite
abertamente: *"Note: `usage` is currently reported as zeros. Token
accounting is a roadmap item, not a regression."*

*Esforço:* S. *Impacto:* Alto (compliance com OpenAI spec, observabilidade
de custo para A2A peers).

**N) WebSocket fixes — [#4267](https://github.com/HKUDS/nanobot/pull/4267) session content dropped, [#4364](https://github.com/HKUDS/nanobot/pull/4364) LAN IP shim**

*Estado femtobot:* O `channels/websocket.py` é alpha ([docs/websocket.md](./docs/websocket.md) §"ALPHA/MINIMAL"). Auditar se há bugs conhecidos análogos
quando usuários migram para Stage 2 A2A via websocket.

*Esforço:* S. *Impacto:* Médio (relevante para Stage 2).

**O) Canal Napcat (QQ) — [#4146](https://github.com/HKUDS/nanobot/pull/4146)**

*Estado femtobot:* N/A (sem QQ). **Manter como opcional.**

**P) Smart strip de imagem para placeholder — [#4401](https://github.com/HKUDS/nanobot/pull/4401)**

*O que o nanobot ganhou:* quando uma imagem é stripped por privacy,
não vaza o path local no placeholder.

*Estado femtobot:* `utils/helpers.py::image_placeholder_text` —
auditar se o placeholder inclui path local.

*Esforço:* XS. *Impacto:* Baixo-Médio (privacidade).

#### 2.3.2 Itens com fit N/A

- **WebUI segmented transcript — [#4278](https://github.com/HKUDS/nanobot/pull/4278):** N/A.
- **WebUI token usage heatmap, prompt rail, etc.:** N/A.
- **Email channel attachments / IMAP post-actions — [#4162](https://github.com/HKUDS/nanobot/pull/4162), [#4258](https://github.com/HKUDS/nanobot/pull/4258):** N/A.
- **Telegram/Feishu/WhatsApp/Slack/Email/QQ/DingTalk/Weixin/Matrix channel
  fixes:** N/A (femtobot é deliberadamente single-channel).
- **Desktop app removido do core — [#4294](https://github.com/HKUDS/nanobot/pull/4294):** N/A.
- **Apple Silicon installer — [#4368](https://github.com/HKUDS/nanobot/pull/4368):** Considerar para Stage 3 (Mac
  é target do roadmap — "Operating System :: MacOS" no classifier).
- **Search providers (Firecrawl, Exa, Bocha, Keenable):** Ver 2.2.2
  acima.

---

## 3. Recomendações priorizadas (resumo executivo)

### Lote A — Estabilidade e segurança (essencial, XS-S, **executar primeiro**)

1. **Fail-fast em config inválida estrutural** (v0.2.2 #4275) — S effort
2. **Reject unsafe MCP HTTP URLs antes do probe** (v0.2.2 #4123) — S
3. **Reject redirect targets em web_fetch** (v0.2.1 #3928) — XS
4. **Normalizar IPv6-mapped IPv4 no SSRF guard** (v0.2.1 #4086) — XS
5. **Log primary error before fallback** (v0.2.0 #4385) — XS
6. **dream_cursor só avança em batches completos + restore correto**
   (v0.2.0 #3631/#3660) — XS-S
7. **Atomic write em `jobs.json`/persistência de cron** (v0.2.0 #3606) — S
8. **Soft workspace boundary com retry-throttle** (v0.2.0 #3614) — S
9. **Race fix entre AutoCompact e Consolidator** (v0.2.1 #3881) — S
10. **Ignorar history entries malformados + cursor monotonic** (v0.2.2
    #4315, #4256) — XS
11. **`extraQuery` para OpenAI-compat** (v0.2.2 #4217) — XS
12. **Sanitizar tool IDs do Anthropic** (v0.2.2 #4356) — XS
13. **Placeholders de imagem sem path local** (v0.2.2 #4401) — XS
14. **Arrearage/`欠费` como fallback trigger** (v0.2.1 #4048) — XS

### Lote B — Durabilidade e concorrência (alto valor, S)

1. **Per-session lock em `process_direct`** (v0.2.1 #4104) — S
2. **Impedir runner de sair com goal ativo + estender budget** (v0.2.1
   #3999, #4127) — XS-S
3. **Forward real LLM usage em /v1/chat/completions** (v0.2.2 #4310) — S
4. **`apply_patch` line-separated** (v0.2.2 #4266) — S
5. **Mover archived summary para o system prompt (KV cache)** (v0.2.0
   #3711) — S
6. **`/goal complete` slash command se faltar** (v0.2.0 #3788) — XS

### Lote C — Refator de arquitetura (M, manutenção longo prazo)

1. **Doc/API do `AgentLoop.from_config()`** paralelo ao `Femtobot.from_config()`
   (v0.2.0 #3708) — XS-S
2. **Capabilities em tools (plugin architecture explícita)** (v0.2.0 #3729) — S
3. **Extension registry local (extensions.json)** (v0.2.1 #4046) — M
4. **CLI Apps unificados com MCP (preset setup, capability mentions)** (v0.2.1
   #3963, #3991, #3979) — M
5. **`/model` wizard no `femtobot onboard`** (v0.2.1 #3890) — S

### Lote D — Provedores e cold-start (S/M)

1. **AWS Bedrock Converse nativo** (v0.2.0 #3574) — M (mas o femtobot já
   cobre a maioria dos casos via openai-compat)
2. **Cold-start do gateway ~10x mais rápido** (v0.2.1 #3918) — S
   (deferido até implementação do gateway A2A)
3. **Disable proxy para endpoints locais** (v0.2.2 #4367) — S
4. **`fallbackModels` mais robusto + arrearage** (v0.2.1 #4048) — XS

### Itens fora do escopo (N/A ou diferidos)

- **Toda a WebUI** (~25 PRs de v0.2.0-v0.2.2): femtobot é CLI-first.
- **Channels sociais** (Telegram, Feishu, Slack, Email, Teams, Discord,
  WhatsApp, Weixin, QQ, DingTalk, Matrix, Napcat, Signal): femtobot é
  single-channel (websocket).
- **Image generation tool + WebUI image mode** (v0.2.0 #3695, v0.2.1
  #3954/#3961/#3971): fora do escopo a menos que a comunidade peça
  (possível adição como tool opcional).
- **i18n da WebUI, BYOK web search, model switching UI:** N/A.
- **Desktop app:** Stage 3 exploratory ([README.md](./README.md) linha 510-512).

---

## 4. Notas de processo

1. **Test coverage está em reconstrução** ([CHANGELOG.md](./CHANGELOG.md) linha 51-52:
   *"Add or update tests if you change behavior (the test suite is being
   rebuilt from scratch in this stage)"*). Antes de portar qualquer item,
   recomenda-se:
   - Cobrir o caminho atual com `pytest` em `tests/`.
   - Adicionar regression test específico do bug upstream.
   - Confirmar `uv run ruff check .` passa.

2. **Schema Pydantic** é a fonte da verdade
   ([docs/configuration.md](./docs/configuration.md) linha 376-381). Qualquer nova
   chave deve:
   - Ser adicionada em `femtobot/config/schema.py` com `extra="forbid"`
     consistente.
   - Aparecer no JSON example de `configuration.md`.
   - Ser documentada com default + range + descrição.

3. **Compatibilidade com `model_presets.py` e `FallbackProvider`** é
   explícita no schema. Ao adicionar provider novo (e.g. Bedrock), seguir
   o padrão de `ProviderSpec` em
   [femtobot/providers/registry.py](file:///home/bill/Codes/agents/femtobot/femtobot/providers/registry.py).

4. **Compat com `apply_patch`**: a tool tem dois modos (`action: "add" |
   "replace"`). Quaisquer correções devem ser feitas em
   [femtobot/agent/tools/apply_patch.py](file:///home/bill/Codes/agents/femtobot/femtobot/agent/tools/apply_patch.py)
   e validadas via `tests/` (criar se não existir).

5. **Comunicação upstream**: o nanobot v0.2.x já tem os autores
   acostumados a receber PRs de fork. Considerar upstream-first para
   itens genéricos (e.g. `IPv6-mapped IPv4 SSRF` é genérico o suficiente
   para um PR cross-fork).

---

## 5. Métrica de alinhamento femtobot ↔ nanobot v0.2.x

Estimativa qualitativa baseada nesta análise:

| Subsistema | Paridade femtobot ↔ nanobot v0.2.2 | Notas |
|---|---|---|
| AgentLoop / state machine | **95%** | Já tem TurnState enum + from_config facade |
| Memory (Consolidator + Dream + AutoCompact) | **85%** | Falta atomic jobs.json + cursor atomic |
| Long-task / goal | **80%** | Falta audit de wall timeout + idle fallback |
| Provider layer + fallback | **90%** | Falta log primário + arrearage |
| MCP | **80%** | Falta unsafe-HTTP guard pre-probe |
| Security (SSRF, command guard) | **75%** | Falta IPv6-mapped + redirect validation |
| Channels | **20%** (1/15+) | Websocket only; fora do escopo |
| WebUI | **0%** (intencional) | N/A |
| OpenAI HTTP API | **70%** | Falta usage real + per-session lock + auth |
| Python SDK | **85%** | Tem Femtobot.from_config + RunResult |
| i18n | **0%** (intencional) | CLI inglês only |

**Conclusão:** O femtobot está **estruturalmente alinhado** com a arquitetura
v0.2.x do nanobot nos subsistemas que elegeu abraçar. Os gaps são
principalmente em hardening (atomicidade, validação, security) e em features
que dependem de canais/WebUI fora do escopo. Um PR "sync nanobot v0.2.2"
consumindo o Lote A e B deste relatório colocaria o femtobot num nível de
robustez **comparável ou superior** ao upstream na sua fatia de cobertura.
