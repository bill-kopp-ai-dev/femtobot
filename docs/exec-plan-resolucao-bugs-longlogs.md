# Plano de Execução — Resolução dos bugs observados em `longlogs.txt`

> **Origem:** sessão do `femtobot agent --ui compat` em
> `/home/bill/Codes/mcp-servers-percival/femtobot`, registrada em
> `longlogs.txt`. O Femto respondeu a 8 testes de resiliência sobre o MCP
> server `percival-osm` sem chamar nenhuma ferramenta, em três turnos,
> violando o `Agent Loop Discipline` do próprio `AGENTS.md`.
>
> **Escopo:** corrigir os **10 bugs** (B1–B10) identificados no
> diagnóstico e devolver à CLI o comportamento esperado em todos os
> perfis (`off`, `compat`, `full`).
>
> **Regra-mãe:** **zero regressão** em `ui_parity=off` e em qualquer
> workspace que já funcione hoje. Toda mudança nova fica atrás de uma
> feature flag com default compatível. Nenhum patch altera o
> comportamento de `Femtobot.from_config()`/`AgentLoop.from_config()`
> sem que a `LongTaskConfig` correspondente (ou flag equivalente) esteja
> desligada por default.

---

## 0. Como ler este documento

- **Milestone (M)** = agrupamento de PRs com objetivo comum e entregável
  verificável.
- **PR** = unidade mergeável, com escopo definido, testes próprios,
  revisável em isolamento.
- **Tarefa** = passo atômico dentro de um PR.
- Cada PR tem **pré-requisitos**, **entregáveis** (arquivos
  modificados/criados) e **critérios de aceite** (lista binária).
- A ordem é **obrigatória**; pular ordem aumenta retrabalho. Em caso de
  conflito com outros planos (`long-task-by-default`, `cli-ui-parity`),
  este plano é subordinado: ajustes de UI aqui não conflitam com D5/F5
  já planejados (apenas os **consomem**).

---

## 1. Visão geral dos milestones

| # | Milestone | PRs | Resultado observável |
|---|---|---|---|
| M0 | Diagnóstico e contratos | 5 | Flags novas no schema, fixtures de log capturadas, suite baseline |
| M1 | Configuração MCP e visibilidade | 3 | `percival-osm` aparece em runtime; warnings amigáveis; `/mcp` exibe lista honesta |
| M2 | `ThinkingSpinner` + parity elapsed | 4 | `SpinnerWithElapsed` finalmente wireado; sem vazamento de `[2K` no TTY |
| M3 | `/ui` como hot-swap real | 2 | Troca de perfil reconstrói o renderer sem reiniciar a CLI |
| M4 | Reasoning stream separado | 3 | `reasoning_content` nunca mais cai no `Live` visível |
| M5 | Comportamento "Agent Loop Discipline" | 3 | LLM para de devolver planos vazios quando há tool disponível |
| M6 | Robustez SDK / hot reload | 2 | `Femtobot.run` lazy-MCP, race window reduzido em reload |
| M7 | Polish e telemetria | 3 | `restart_notice` ordenado, smoke tests E2E, métricas |

Total: **25 PRs** em **8 milestones**.

---

## 2. Pré-trabalho — Reproduzir e triar o bug

Antes do PR 0.1, executar localmente:

```bash
# 1. Capturar a sessão reprodutível
cd /home/bill/Codes/mcp-servers-percival/femtobot
femtobot agent --ui compat 2>&1 | tee /tmp/longlogs-repro.txt

# 2. Confirmar config vazia
jq '.tools.mcp_servers' .femtobot/config.json   # deve ser {} ou null

# 3. Confirmar ausência de tools no runtime
femtobot agent --ui compat -m "/help" 2>&1 | grep -E 'osm_|mcp_percival'
# esperado: 0 linhas
```

Anexar `/tmp/longlogs-repro.txt` ao PR 0.1 como evidência.

---

## 3. Milestone M0 — Diagnóstico e contratos

> Objetivo: fixar schema, flags e fixtures **sem mudar comportamento**.

### PR 0.1 — Adicionar `McpConfig` ao schema com warnings estruturados

**Pré-requisitos:** nenhum.
**Entregáveis:**
- `femtobot/config/schema.py`: nova classe `McpConfig` com:
  - `warn_on_missing_references: bool = True` — emite warning ao iniciar
    quando um `mcp_servers` referenciado em `AGENTS.md`/`USER.md`/`SOUL.md`
    não está em `tools.mcp_servers`.
  - `auto_resolve_path_warnings: bool = True` — reusa
    `agents.defaults.notify_mcp_startup_failures` se presente
    (back-compat).
- Wire em `ToolsConfig.mcp: McpConfig = Field(default_factory=McpConfig)`.
- Refatorar `mcp_mentions` parsing em `agent/context.py:_collect_mcp_persistence_snippets`
  para retornar lista de nomes **não-resolvidos** além do snippet
  Markdown; persistir essa lista em `session.metadata["mcp_missing"]`.

**Critérios de aceite:**
- [ ] `femtobot config validate` aceita o bloco novo e o omite silenciosamente
- [ ] Suite atual de config (`tests/test_config_loader_a1.py`,
      `tests/test_agents_config_init.py`) passa
- [ ] Nenhum comportamento runtime alterado (todas as novas flags em
      default compatível)

### PR 0.2 — Fixture `tests/fixtures/longlogs_sample.txt`

**Pré-requisitos:** PR 0.1.
**Entregáveis:**
- `tests/fixtures/longlogs_sample.txt` — trecho curado (≤ 200 linhas)
  cobrindo cada um dos sintomas B1–B10.
- `tests/fixtures/longlogs_expected_bugs.json` — índice declarativo
  `{ "B1": {"line_start": 94, "line_end": 99, "kind": "tool_missing"}, … }`.
- `tests/test_longlogs_regression.py` — carrega o fixture, valida que
  cada bug tem uma linha-âncora presente, falhando se alguém limpar a
  fixture sem remover o teste.

**Critérios de aceite:**
- [ ] `pytest tests/test_longlogs_regression.py` passa
- [ ] Fixture tem sumário no topo listando os 10 bugs

### PR 0.3 — Refatorar `_resolve_allowed_path_restrict` em mensagens de erro

**Pré-requisitos:** PR 0.1.
**Entregáveis:**
- `femtobot/security/workspace_policy.py`: `WorkspaceBoundaryError`
  recebe `code` enum (`PATH_TRAVERSAL`, `OUTSIDE_ROOT`, `READONLY_ROOT`).
- Helper `explain_boundary_error(err, *, workspace, attempted)` que
  retorna Markdown curto pronto para o LLM com:
  - nome do workspace
  - tentativas anteriores que **também** falhariam (heurística:
    listar `..`, `../..`, `/tmp`, `/home` quando aplicável)
  - **ação recomendada** (criar subdir, ampliar `ALLOWED_ROOTS`, pedir
    aprovação humana)

**Critérios de aceite:**
- [ ] Mensagens atuais (`command_guard.py:104-138`) preservadas como
      `code="PATH_TRAVERSAL"` etc.
- [ ] Testes novos em
      `tests/security/test_workspace_boundary_messages.py`
- [ ] Suite de testes existente continua passando

### PR 0.4 — Snapshot helper para testes de regressão TUI

**Pré-requisitos:** PR 0.2.
**Entregáveis:**
- `tests/cli/_capture.py::capture_streaming` — usa `console.record=True`
  do Rich + `Live(console=recorder, transient=True)` para capturar
  output programaticamente, **incluindo** escapes ANSI.
- Função `normalize_ansi(s: str) -> str` que colapsa `[2K`, `[?25l`,
  `[?25h`, `[1A`, `[1B`, etc. em tags `<ESC:CLR>`, `<ESC:HIDE>`,
  etc., para tornar os snapshots diff-friendly.
- Baseline snapshot em
  `tests/cli/snapshots/compat_first_turn.txt` (gerado a partir do
  fixture de PR 0.2).

**Critérios de aceite:**
- [ ] `tests/test_stream_snapshot.py` passa com snapshot
- [ ] `normalize_ansi` é pura (sem I/O), testada com 20+ sequências

### PR 0.5 — Smoke tests do estado atual

**Pré-requisitos:** PRs 0.1–0.4.
**Entregáveis:**
- `tests/test_long_task_m_bugs_m0.py` — testa:
  - `McpConfig` defaults
  - `WorkspaceBoundaryError.code` em cada path
  - `mcp_missing` populado quando config não casa com AGENTS.md
- CI: rodar o snapshot test antes do suite legacy.

**Critérios de aceite:**
- [ ] Toda a suite existente passa
- [ ] M0 suite passa
- [ ] CI verde

---

## 4. Milestone M1 — Configuração MCP e visibilidade (B1, B8)

> Objetivo: o agente sabe **honestamente** quais MCP servers estão
> conectados e quais estão faltando; o usuário recebe mensagem acionável.

### PR 1.1 — `mcp status` honra `_CONNECTED_TOOLS_CACHE` e `_mcp_servers`

**Pré-requisitos:** PR 0.1.
**Entregáveis:**
- `command/builtin.py:cmd_mcp` (linhas atuais 1396–1720) reescrito:
  - subcomando `status` lista:
    - **configured** (de `state._mcp_servers`)
    - **connected** (de `state._mcp_stacks.keys()`)
    - **missing** (configured − connected)
    - **referenced-but-unconfigured** (do
      `session.metadata["mcp_missing"]` introduzido em 0.1)
  - subcomando `path <server>` imprime `command`/`url`/`transport`
    efetivo
- Adicionar tip em `/help` referenciando `femtobot status --mcp` como
  visão CLI de alto nível (para casos em que o slash command não
  estiver disponível).

**Critérios de aceite:**
- [ ] `/mcp status` no workspace do `longlogs.txt` retorna a linha
      `configured: []` com link para editar `config.json`
- [ ] `femtobot status --mcp` retorna o mesmo conteúdo em formato JSON
- [ ] Teste novo em `tests/test_cmd_mcp_status.py`

### PR 1.2 — Warning inicial quando `referenced-but-unconfigured`

**Pré-requisitos:** PR 1.1.
**Entregáveis:**
- `agent/loop.py:_connect_mcp` (linhas 597–648): depois de
  `connect_missing_servers`, ler
  `session.metadata["mcp_missing"]` e:
  - sempre logar warning estruturado
  - se `agents_config.defaults.notify_mcp_startup_failures` (mantido
    de B1) **ou** `mcp.warn_on_missing_references`, emitir
    `OutboundMessage` em `bus.publish_outbound(channel="cli",
    chat_id="startup", …)` com:
    - nome(s) faltando
    - trecho do `config.json` que precisa editar
    - comando sugerido: `/mcp reload` após editar

**Critérios de aceite:**
- [ ] No repro do `longlogs.txt`, **a primeira resposta** do agente
      inclui a lista honesta de tools ausentes, não uma enumeração de
      opções (mata B10 indiretamente)
- [ ] Suite atual passa; flag default não emite warning quando
      `mcp_missing` é vazio

### PR 1.3 — `mcp-router` skill ampliada para servidores genéricos

**Pré-requisitos:** PR 1.1.
**Entregáveis:**
- `femtobot/skills/mcp-router/SKILL.md`: nova seção "Generic MCP
  servers" listando o que fazer quando o servidor referenciado não é
  `agy`/`claude`:
  1. verificar `tools.mcp_servers[name]` em `config.json`
  2. se ausente, listar via `/mcp status` e orientar o usuário
  3. se presente mas disconnected, oferecer `/mcp reload`
  4. **nunca** emular via `curl`/`exec` sem confirmação humana
- Frontmatter `metadata.femtobot.triggers`: adicionar
  `"MCP server", "percival-osm", "osm_*"` para que o skill seja
  ativado quando essas strings aparecerem no `inbound_message`.

**Critérios de aceite:**
- [ ] `tests/test_skills_mcp_router.py` cobre as 4 ramificações
- [ ] Skill ativada em turno que mencione "percival-osm" (teste
      programático em `tests/test_skill_triggers.py`)

---

## 5. Milestone M2 — `ThinkingSpinner` + parity elapsed (B3, B4)

> Objetivo: spinner com elapsed time de verdade, sem race com `Live`.

### PR 2.1 — `Live` pausa determinística antes de `_clear_current_line`

**Pré-requisitos:** PR 0.4.
**Entregáveis:**
- `cli/stream.py` (linhas 25–32): `_clear_current_line` torna-se
  `_clear_live_block(console)` que:
  - lê `console.size` (linhas do bloco)
  - escreve `\x1b[2J\x1b[H` quando stdout é TTY (apaga tudo,
    reposiciona o cursor)
  - quando não é TTY, escreve `"\n" * (console.height // 2)` (limpa
    blocos anteriores, sem perder o histórico do usuário)
- Adicionar `live.stop()` antes do clear nos callers
  (`StreamRenderer.on_end`, `_start_spinner`, `_start_live`).

**Critérios de aceite:**
- [ ] Snapshot de PR 0.4 continua passando após as mudanças
- [ ] `tests/test_stream_snapshot.py::test_live_clear_race` — grava
      dois turnos seguidos em stdout capturado, valida que cada bloco
      está isolado por ≥ 1 linha em branco

### PR 2.2 — Wire `SpinnerWithElapsed` no `ThinkingSpinner`

**Pré-requisitos:** PR 2.1.
**Entregáveis:**
- `cli/stream.py` linhas 49–101: `ThinkingSpinner.__enter__` aceita
  `elapsed_renderable: SpinnerWithElapsed | None = None`. Quando setado,
  usa-o em vez de `console.status(text, spinner=…)`.
- `cli/parity_stream.py` `__init__` (linhas 55–90): constrói um
  `SpinnerWithElapsed` (já há campos `_spinner_renderable`,
  `_spinner_start_ts`) e o passa para o `base_renderer` (precisa
  expor um setter em `StreamRenderer`).
- `_make_progress` em `cli/commands.py` (linhas 1257–1340):
  - `tool_hint` agora inicializa `_spinner_renderable` com o renderable
    novo
  - `tool_end` finaliza `_spinner_start_ts`
- Remover o comentário "KNOWN GAP" em `cli/parity_stream.py:178-195`.

**Critérios de aceite:**
- [ ] Log capturado mostra `✻ Cogitating… (3s)` em vez de
      `Femtobot is cogitating...`
- [ ] Tokens (`↓ 412 tokens`) aparecem quando `last_usage` está
      disponível
- [ ] `tests/test_thinking_spinner.py::test_elapsed_renderable` — usa
      `monkeypatch` em `time.monotonic` para validar avanço

### PR 2.3 — Stop do spinner antes de `_clear_current_line`

**Pré-requisitos:** PR 2.1, PR 2.2.
**Entregáveis:**
- `_clear_live_block` (PR 2.1) aceita `live: Live | None` e o pausa
  antes de operar
- Todos os call sites passam o `live` quando há

**Critérios de aceite:**
- [ ] Mesmo snapshot de 2.1 passa; diferença é que agora o spinner
      para limpo, sem flicker
- [ ] `tests/test_textual_app.py` (já existente) continua passando

### PR 2.4 — Smoke test visual do spinner com elapsed

**Pré-requisitos:** PR 2.2, PR 2.3.
**Entregáveis:**
- `tests/cli/test_spinner_elapsed_integration.py` — monta um
  `FemtobotTextualApp` ou `StreamRenderer` real, dispara um turno
  curto, captura saída, valida presença da string
  `Femtobot is \w+ \(\d+s\)`.

**Critérios de aceite:**
- [ ] Teste é determinístico (sem `sleep` real; usa
      `monkeypatch.setattr("time.monotonic", …)`)
- [ ] Falha atual seria capturada (rodar contra código pré-2.2)

---

## 6. Milestone M3 — `/ui` como hot-swap real (B2)

> Objetivo: trocar de perfil **reconstrói** o renderer.

### PR 3.1 — `cmd_ui` invalida `_ACTIVE_RENDERER`

**Pré-requisitos:** nenhum (standalone).
**Entregáveis:**
- `command/builtin.py:cmd_ui` (linhas 1724–1795):
  - retorna `OutboundMessage` com `metadata["_rebuild_renderer"] =
    True`
- `cli/commands.py:_consume_outbound` (linhas 1425–1497):
  - intercepta `metadata["_rebuild_renderer"]` e chama novo helper
    `_swap_renderer(profile)` que:
    1. fecha o `_ACTIVE_RENDERER` atual (`await renderer.close()`)
    2. resolve `get_renderer_factory(profile)` (já existe em
       `renderer_factory.py`)
    3. atribui ao singleton
    4. imprime o cabeçalho do novo perfil

**Critérios de aceite:**
- [ ] `/ui off` no repro do `longlogs.txt` faz a próxima resposta
      voltar ao `StreamRenderer` legacy
- [ ] `/ui compat` reativa o parity layer sem reiniciar CLI
- [ ] `tests/test_md_commands_ui_swap.py` cobre todas as 3 transições
      (off→compat, compat→off, off→full)

### PR 3.2 — `/ui full` degrada graciosamente

**Pré-requisitos:** PR 3.1.
**Entregáveis:**
- `cli/textual_app.py` linhas 84–87: `TextualNotAvailable` é levantado
  com mensagem clara quando Textual não está instalado
- `cmd_ui` detecta `full` sem Textual e mostra:
  - banner `full profile requested but textual is not installed`
  - sugestão `pip install textual` ou `--ui compat`
  - fallback automático para `off`

**Critérios de aceite:**
- [ ] `pip uninstall textual -y && femtobot agent --ui full`
      retorna `Off profile loaded as fallback` e continua
- [ ] `tests/test_ui_parity_config.py` (já existente) continua
      passando

---

## 7. Milestone M4 — Reasoning stream separado (B5)

> Objetivo: `reasoning_content` nunca mais vaza no `Live` visível.

### PR 4.1 — Roteamento de `reasoning_content` no provider layer

**Pré-requisitos:** nenhum.
**Entregáveis:**
- `providers/openai_compat_provider.py` (e `openai_responses/`):
  - delta com campo `reasoning_content` (ou `reasoning` no caso
    Responses API) **não** é concatenado a `content`
  - é publicado em canal separado `reasoning_delta`
- `agent/progress_hook.py:AgentProgressHook` (chamado por
  `_run_agent_loop` em `loop.py:846-858`): callback `on_reasoning`
  novo, separado de `on_progress`

**Critérios de aceite:**
- [ ] Suite `test_providers_a11_a12.py` continua passando
- [ ] `test_reasoning_routing.py` — provider mock emite reasoning e
      valida que não aparece em `on_progress`

### PR 4.2 — `cli/commands.py` separa reasoning buffer

**Pré-requisitos:** PR 4.1.
**Entregáveis:**
- `_ReasoningBuffer` (já existe em algum lugar; localizar via grep)
  - passa a ser alimentado por `on_reasoning` callback novo
  - `channels.show_reasoning` controla se vai para stdout ou é
    descartado
- `_make_progress` (linhas 1257–1340) **só** repassa `reasoning=True`
  para o callback de reasoning; nunca para `on_delta`/`on_progress`

**Critérios de aceite:**
- [ ] Repro do `longlogs.txt` mostra o texto de reasoning em área
      separada (toggle `Ctrl+O`) ou invisível quando `show_reasoning=false`
- [ ] `tests/test_role_renderer.py` cobre o toggle

### PR 4.3 — Telemetria: tokens de reasoning

**Pré-requisitos:** PR 4.1, PR 4.2.
**Entregáveis:**
- `bus/runtime_events.py`: novo evento `reasoning_completed(duration_s,
  token_estimate)`
- `cli/parity_widgets.SpinnerWithElapsed.thoughts_s` recebe o evento

**Critérios de aceite:**
- [ ] Spinner mostra `thought for Xs` quando `thoughts_s >= 0.5`
      (já implementado em `parity_widgets.py:346-348`, só faltava
      wirear)
- [ ] `tests/test_thinking_spinner.py` (PR 2.4) cobre o novo campo

---

## 8. Milestone M5 — Comportamento "Agent Loop Discipline" (B10)

> Objetivo: o LLM para de devolver planos vazios quando há tool
> disponível.

### PR 5.1 — Auditoria estática do `AGENTS.md` runtime

**Pré-requisitos:** nenhum.
**Entregáveis:**
- Script `scripts/audit_agents_md.py` que:
  - resolve `workspace/AGENTS.md` + `templates/AGENTS.md` +
    `templates/agent/identity.md` na ordem de merge atual
  - detecta contradições:
    - **REGRA X contradiz REGRA Y**: ambos exigem ações mutuamente
      exclusivas (ex.: "ask the user" vs "be autonomous")
  - imprime ranking de precedência esperado (identity > AGENTS > SOUL)
- CI: roda em `pytest` como teste opcional (`-m audit`)

**Critérios de aceite:**
- [ ] Rodar contra o workspace do `longlogs.txt` lista pelo menos a
      contradição "Agent Loop Discipline (mandatory tool use)" vs
      "Default Posture: autonomous" (atualmente ambas existem, mas a
      primeira perde na prática)
- [ ] Script é puro (sem I/O de rede)

### PR 5.2 — System prompt com bloco "Tools available right now"

**Pré-requisitos:** PR 1.1.
**Entregáveis:**
- `agent/context.py:build_system_prompt` (linhas 151–206):
  - nova seção `## Tools available right now` injetada **sempre** (não
    só quando há MCP), listando:
    - ferramentas locais (read, write, exec, apply_patch, grep, glob,
      bash_mode)
    - ferramentas MCP conectadas
    - ferramentas MCP configuradas mas disconnected (com
      `⚠ not connected`)
- Posição: entre `## Identity` e `## Default Posture` (precedência alta)

**Critérios de aceite:**
- [ ] `tests/test_agents_template_mcp.py` (já existe) continua
      passando
- [ ] `tests/test_system_prompt_tools_block.py` — verifica presença
      e ordem

### PR 5.3 — Hook pós-turn: tool-call-or-else

**Pré-requisitos:** PR 5.2.
**Entregáveis:**
- `agent/hook.py`: novo hook opcional `ToolUseGuardHook`:
  - se o turno termina com `stop_reason="completed"` mas a mensagem do
    usuário continha palavras-chave (`test`, `execute`, `run`, `rode`,
    `call`) e **nenhuma** tool foi usada, injeta continuation:
    `"Internal nudge: the user asked you to execute something but no
    tool was called. Either run a tool now, or state concretely why
    you cannot (missing tool, missing credentials, blocking policy)."`
- Opt-in via `agents.defaults.tool_use_guard.enabled=true` (default
  `false` para não quebrar setups legítimos)

**Critérios de aceite:**
- [ ] No repro do `longlogs.txt` com a flag ligada, o Femto **ou**
      chama `exec curl` para Nominatim **ou** responde "Não tenho a
      ferramenta MCP `osm_geocode` registrada neste workspace;
      registre-a em `tools.mcp_servers` (veja `/mcp status`)."
- [ ] `tests/test_tool_use_guard_hook.py` cobre os dois caminhos
      (tool usada / não usada)

---

## 9. Milestone M6 — Robustez SDK / hot reload (B6, B7, B9)

> Objetivo: SDK init seguro, race window zero em reload, `restart_notice`
> ordenado.

### PR 6.1 — `Femtobot.from_config` valida MCP antes de aceitar a config

**Pré-requisitos:** PR 1.1.
**Entregáveis:**
- `femtobot.py:from_config` (linhas 64–97):
  - após `load_config`, chama
    `validate_mcp_references(config)` (helper novo em
    `agent/tools/mcp.py`)
  - se algum `mcp_servers[name]` aponta para binário inexistente no
    PATH, emite warning via `typer.echo(..., err=True)` **mas não
    bloqueia** (o agente pode ser usado em modo local-only)
  - exporta métrica `mcp_startup_failures_total`

**Critérios de aceite:**
- [ ] `Femtobot.from_config()` no repro do `longlogs.txt` loga:
      `MCP server 'percival-osm' configured but binary 'percival-osm-mcp' not found in PATH`
- [ ] SDK continua usável (não levanta exceção)

### PR 6.2 — `restart_notice` ordenado

**Pré-requisitos:** nenhum.
**Entregáveis:**
- `cli/commands.py` linhas 1244–1249: o `_print_agent_response` do
  `restart_notice` só roda **depois** de
  `_init_prompt_session()` (mover para depois do bloco que cria o
  `_ACTIVE_RENDERER`)
- Se renderer não estiver pronto, fallback para `console.print(...)`
  sem header

**Critérios de aceite:**
- [ ] `tests/test_cli_signal_handler.py` continua passando
- [ ] Smoke test manual: `FEMTOBOT_RESTART_NOTICE=… femtobot agent`
      mostra o notice **após** o banner, não antes

---

## 10. Milestone M7 — Polish e telemetria

> Objetivo: observabilidade do que foi consertado.

### PR 7.1 — Métricas de bugs resolvidos

**Pré-requisitos:** PR 5.3.
**Entregáveis:**
- `bus/runtime_events.py`: eventos
  `tool_use_guard_triggered(session_key, reason)`,
  `mcp_missing_warning_emitted(server_name)`,
  `live_race_detected(turn_id)`
- `tests/test_runtime_events.py` cobre publicação

### PR 7.2 — `femtobot doctor` para triagem

**Pré-requisitos:** PR 6.1, PR 5.2.
**Entregáveis:**
- `cli/commands.py` (ou novo módulo `cli/doctor.py`): subcomando
  `femtobot doctor` que roda:
  1. `femtobot config validate`
  2. `femtobot status --mcp` (de PR 1.1)
  3. snapshot do `Live`/`Spinner` (caminho feliz)
  4. verifica `FEMTOBOT_RESTART_NOTICE` não consumido
  5. imprime scorecard `OK / WARN / FAIL`

**Critérios de aceite:**
- [ ] `femtobot doctor` no workspace do `longlogs.txt` retorna:
  - `config: OK`
  - `mcp_servers: WARN (percival-osm referenced but not configured)`
  - `spinner: OK` (após M2)
  - `live_race: OK` (após M2)

### PR 7.3 — Smoke E2E `femtobot_agent_repro_longlogs`

**Pré-requisitos:** todos os anteriores.
**Entregáveis:**
- `tests/E2E_REGRESSION_PROMPT.md`: roteiro de 8 passos reproduzindo o
  cenário do `longlogs.txt`
- `tests/e2e_regression_prompt.py`: executa o roteiro em modo
  headless (`femtobot agent --message …`) e valida:
  - tools ausentes listadas na primeira resposta
  - nenhum plano vazio (regex match `\bvou (fazer|emitir|começar)\b`
    deve ser seguido de tool call em até 2 turns)
- Roda em CI nightly (não bloqueia PR)

**Critérios de aceite:**
- [ ] `pytest -m e2e tests/e2e_regression_prompt.py` passa
- [ ] Falha anterior ao M5 (captura B10)

---

## 11. Compatibilidade e rollback

| Mudança | Default | Rollback |
|---|---|---|
| `McpConfig.warn_on_missing_references` | `True` | Setar `false` no config |
| `McpConfig.auto_resolve_path_warnings` | `True` | Setar `false` |
| `/ui` rebuild | sempre que invocado | N/A — sem rebuild, comportamento legacy |
| `SpinnerWithElapsed` wireado | sempre que `compat` | N/A — profile `off` usa legacy |
| `ToolUseGuardHook` | `False` | Setar `agents.defaults.tool_use_guard.enabled=false` |
| `femtobot doctor` | sempre disponível | Não usa nenhum recurso novo |

Em qualquer ponto, **`femtobot agent` sem flag nova se comporta
identicamente à v0.1.0-ui.0-preview**.

---

## 12. Critérios globais de aceite (release)

Para marcar todos os 10 bugs como resolvidos:

- [ ] **B1**: `/mcp status` lista `configured=[]` e warning inicial
      orienta a editar `config.json`
- [ ] **B2**: `/ui off|compat|full` reconstrói renderer imediatamente
- [ ] **B3**: spinner mostra elapsed time + tokens
- [ ] **B4**: snapshot TUI não tem `[2K` no TTY nem linhas vazadas
- [ ] **B5**: reasoning content fica em buffer separado
- [ ] **B6**: log capturado de TTY real é legível (sem escape codes
      espúrios)
- [ ] **B7**: `Femtobot.run` lazy-connect não causa race com reload
- [ ] **B8**: warning inicial sempre que `referenced-but-unconfigured`
- [ ] **B9**: `restart_notice` aparece depois do banner, não antes
- [ ] **B10**: agent executa tool ou explica blocker concreto em
      ≤ 1 turno

Validação final: rodar o repro do `longlogs.txt` e capturar nova
saída; nenhum dos 10 sintomas pode reaparecer.

---

## 13. Estimativa de esforço

> Evito números absolutos, mas a sequência cabe em ~3 ciclos curtos:
> M0–M1 (fundação), M2–M4 (UI/UX), M5–M7 (comportamento + telemetria).
> Cada milestone termina com um PR mergeável e testável
> independentemente.
