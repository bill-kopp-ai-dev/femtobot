# Plano de Execução — Long Task by Default no femtobot

> **Status:** derivado direto da [V2 do plano de refatoração](file:///home/bill/Codes/agents/femtobot/docs/refactor-long-task-by-default.md).
> **Objetivo:** quebrar o plano V2 em milestones e PRs pequenos, implementáveis
> em ordem, cada um com critério de aceite próprio.
> **Regra-mãe:** nada de regressão. `byDefault=false` deve preservar o
> comportamento atual byte-a-byte até o último PR.

---

## 0. Como ler este documento

- **Milestone** = agrupamento de PRs com um objetivo comum e entregável
  verificável.
- **PR** = uma unidade mergeável, com escopo bem definido, testes próprios
  e revisável em isolamento.
- **Tarefa** = passo atômico dentro de um PR.
- Cada PR tem **pré-requisitos** (PRs que precisam estar mergeados antes),
  **entregáveis** (arquivos modificados/criados) e **critérios de aceite**
  (lista verificável).
- A ordem abaixo **deve** ser seguida; pular ordem aumenta o risco de
  retrabalho.

---

## 1. Visão geral dos milestones

| # | Milestone | PRs | Resultado observável |
|---|---|---|---|
| M0 | Contrato operacional | 5 | Config nova carrega, schema validado, smoke tests passam |
| M1 | Domínio do goal | 4 | `/goal` cria goal real, `GoalStateChanged` é publicado, sem tools ainda |
| M2 | Tools e visibilidade por turno | 4 | `long_task` e `complete_goal` funcionam; `complete_goal` visível em todo goal ativo |
| M3 | Runtime context e template | 2 | Bloco "Goal (active)" injetado no system prompt |
| M4 | Continuação multi-canal | 4 | `process_direct(goal_aware)` e `SDK` rodam goals sem intervenção manual |
| M5 | API assíncrona | 5 | Supervisor chama worker via HTTP com `async_goal` |
| M6 | `ask_orchestrator` | 4 | Worker pausa em dúvida crítica e retoma por `correlation_id` |
| M7 | UX e polish | 5 | Slash commands novos, CLI com coluna goal, docs |

Total: **33 PRs**, agrupados em **8 milestones**.

---

## 2. Milestone M0 — Contrato operacional

> Objetivo: fixar schema, tipos e módulos de suporte **sem alterar comportamento**.

### PR 0.1 — Adicionar `LongTaskConfig` ao schema (somente schema)
**Pré-requisitos:** nenhum.
**Entregáveis:**
- `femtobot/config/schema.py`: nova classe `LongTaskConfig` com todos os campos da V2 §6.1
- `LongTaskApiMode` enum (`sync | async_goal | auto`)
- Campo `long_task: LongTaskConfig = Field(default_factory=LongTaskConfig)` em `AgentDefaults`

**Critérios de aceite:**
- [ ] `femtobot config validate` aceita um `config.json` sem bloco `longTask`
- [ ] `femtobot config validate` aceita um `config.json` com `longTask.byDefault=true`
- [ ] Suite atual de testes do config passa sem mudança
- [ ] Nenhum comportamento de runtime é alterado

### PR 0.2 — Carregar `LongTaskConfig` no `AgentLoop`
**Pré-requisitos:** PR 0.1.
**Entregáveis:**
- `femtobot/agent/loop.py`: `AgentLoop.__init__` aceita `long_task_config: LongTaskConfig | None`
- `AgentLoop.from_config` lê de `defaults.long_task`
- Logger registra `long_task_config` no startup

**Critérios de aceite:**
- [ ] Loop instancia normalmente sem `long_task_config`
- [ ] Loop loga `long_task_config.by_default` no startup
- [ ] Testes unitários cobrem default e override

### PR 0.3 — Esqueleto vazio de `pending_asks`
**Pré-requisitos:** nenhum.
**Entregáveis:**
- `femtobot/session/pending_asks.py`: dataclasses `PendingAsk`, `AskStatus`, helpers
  `register_pending_ask`, `resolve_pending_ask`, `expire_pending_asks`
- Sem integração runtime ainda — apenas estrutura e testes

**Critérios de aceite:**
- [ ] Dataclasses criam, expiram e resolvem corretamente
- [ ] `PendingAsk` é serializável em JSON
- [ ] Cobertura de testes ≥ 90%

### PR 0.4 — Esqueleto vazio de `goal_runtime`
**Pré-requisitos:** nenhum.
**Entregáveis:**
- `femtobot/api/goal_runtime.py`: dataclasses `GoalJob`, `GoalEvent`
- Funções puras: `create_goal_job`, `serialize_goal_event`, `terminal_status`
- Sem integração com `server.py` ainda

**Critérios de aceite:**
- [ ] `GoalJob` carrega JSON round-trip
- [ ] `terminal_status("complete" | "cancel" | "block")` retorna o status esperado
- [ ] Testes unitários independentes da API

### PR 0.5 — Smoke tests do contrato atual
**Pré-requisitos:** PRs 0.1–0.4.
**Entregáveis:**
- `tests/test_long_task_m0.py`: valida que
  - `config validate` aceita o novo bloco
  - `loop.from_config` carrega corretamente
  - `pending_asks` e `goal_runtime` módulos importam sem side-effects
  - Comportamento atual preservado (`byDefault=false` em todos os testes existentes)

**Critérios de aceite:**
- [ ] Toda a suite de testes existente passa
- [ ] M0 suite passa
- [ ] CI verde

---

## 3. Milestone M1 — Domínio do goal (sem tools ainda)

> Objetivo: o estado do goal é criado/atualizado por slash commands e o
> evento é publicado, mas o LLM ainda não tem tools.

### PR 1.1 — Helpers de `goal_state`
**Pré-requisitos:** M0 mergeado.
**Entregáveis:**
- `femtobot/session/goal_state.py`:
  - constante `MAX_GOAL_OBJECTIVE_CHARS = 4000`
  - constante `GOAL_ACTIONS = ("complete", "cancel", "block", "replace")`
  - `explicit_goal_requested(message_metadata)`
  - `implicit_goal_requested(message_metadata)`
  - `goal_bootstrap_requested(message_metadata)`
  - helpers `goal_started_at`, `goal_elapsed_s`, `goal_block_reason`
- Preservar `sustained_goal_active` e `sustained_goal_turn` (já existentes)

**Critérios de aceite:**
- [ ] Cada helper tem teste próprio
- [ ] Comportamento das funções legadas é bit-by-bit equivalente
- [ ] Suite existente passa

### PR 1.2 — `goal_permission.py` (ContextVar)
**Pré-requisitos:** PR 1.1.
**Entregáveis:**
- `femtobot/agent/goal_permission.py`:
  - ContextVar `_FEMTOBOT_GOAL_MUTATION_ALLOWED`
  - `set_goal_mutation_allowed(bool)`, `goal_mutation_allowed()`
  - `revoke_goal_mutation_permission()`
  - `MutationNotAllowedError`

**Critérios de aceite:**
- [ ] ContextVar é isolado por task asyncio
- [ ] Default é `False`
- [ ] Testes cobrem set/get/revoke

### PR 1.3 — Publicação de `GoalStateChanged`
**Pré-requisitos:** PR 1.1.
**Entregáveis:**
- `femtobot/bus/runtime_events.py`: confirmar que `GoalStateChanged` existe
- `femtobot/utils/runtime.py` (ou novo helper `femtobot/bus/goal_events.py`):
  `publish_goal_state_changed(rc, session_key, status, objective, ...)`

**Critérios de aceite:**
- [ ] Função `publish_goal_state_changed` testada com subscriber fake
- [ ] Nenhum subscriber real é adicionado ainda

### PR 1.4 — `/goal` cria goal explicitamente
**Pré-requisitos:** PRs 1.1–1.3.
**Entregáveis:**
- `femtobot/command/builtin.py`:
  - `cmd_goal` grava `goal_state` diretamente no `session.metadata` (não
    depende mais do LLM chamar tool)
  - Marca `goal_requested=True` na inbound
  - Publica `GoalStateChanged`
- `cmd_goal_complete`, `cmd_goal_cancel`, `cmd_goal_block`, `cmd_goal_status`
  escrevem o status correto no metadata e publicam evento

**Critérios de aceite:**
- [ ] `/goal Refatorar X` cria goal ativo
- [ ] `/goal complete` finaliza
- [ ] `/goal status` mostra o objetivo e status
- [ ] `GoalStateChanged` é publicado em cada transição
- [ ] Testes atuais de `/goal` (se houver) continuam passando

---

## 4. Milestone M2 — Tools e visibilidade por turno

> Objetivo: criar `long_task.py` e `complete_goal` e torná-los visíveis
> segundo as regras da V2 §8.

### PR 2.1 — `LongTaskTool`
**Pré-requisitos:** M1 mergeado.
**Entregáveis:**
- `femtobot/agent/tools/long_task.py`: classe `LongTaskTool`
- Schema: `objective` (string, 1..4000), `ui_summary` (string|null, max 120)
- Implementação chama helper de domínio para gravar `goal_state`
- Publica `GoalStateChanged`
- Verifica `goal_mutation_allowed()` antes de criar/substituir

**Critérios de aceite:**
- [ ] Tool aparece no registry
- [ ] Sem permissão, retorna erro estruturado (`MutationNotAllowedError`)
- [ ] Publica evento em sucesso
- [ ] Testes unitários cobrem cada path

### PR 2.2 — `CompleteGoalTool`
**Pré-requisitos:** PR 2.1.
**Entregáveis:**
- `femtobot/agent/tools/long_task.py`: classe `CompleteGoalTool`
- Schema com action (`complete | cancel | block | replace`), `recap`, `objective`, `ui_summary`
- `replace` exige permissão de mutação
- `complete | cancel | block` revogam permissão

**Critérios de aceite:**
- [ ] Cada action testada
- [ ] `replace` sem permissão falha
- [ ] Revogação de permissão é verificada

### PR 2.3 — Visibilidade por turno em `context.py`
**Pré-requisitos:** PR 2.2.
**Entregáveis:**
- `femtobot/agent/context.py`: nova função `filter_tool_schemas_for_turn(registry, session_metadata, message_metadata, long_task_config)`
- Regras:
  - `long_task`: visível quando `byDefault=true` ou `explicit/implicit_goal_requested`
  - `complete_goal`: visível sempre que `sustained_goal_active(session_metadata)`
  - `ask_orchestrator`: sempre visível

**Critérios de aceite:**
- [ ] Função é pura e testável
- [ ] Cobertura das combinações de estado
- [ ] Documentação inline do motivo de cada regra

### PR 2.4 — Hook em `loop._state_command`
**Pré-requisitos:** PR 2.3.
**Entregáveis:**
- `femtobot/agent/loop.py`: quando `byDefault=true` e inbound não é slash
  command, marcar `goal_requested=True`, `goal_requested_implicitly=True`,
  `goal_started_at`
- Não sobrescrever `original_command` (correção da V2)
- Atualizar `filter_tool_schemas_for_turn` no `_state_build`

**Critérios de aceite:**
- [ ] Mensagem trivial "oi" com `byDefault=true` vira goal implícito
- [ ] Mensagem trivial "oi" com `byDefault=false` mantém comportamento atual
- [ ] `complete_goal` continua visível em turnos seguintes do goal

---

## 5. Milestone M3 — Runtime context e template

### PR 3.1 — `runtime_context.py`
**Pré-requisitos:** M2 mergeado.
**Entregáveis:**
- `femtobot/runtime_context.py`: `RuntimeContextBlock`, `build_runtime_context_lines`
- Suporte a blocos: `goal_active`, `ask_pending`, `goal_blocked`

**Critérios de aceite:**
- [ ] Funções puras testáveis
- [ ] Nenhum acoplamento ao loop ainda

### PR 3.2 — Template e injeção no system prompt
**Pré-requisitos:** PR 3.1.
**Entregáveis:**
- `femtobot/templates/agent/goal_runtime.md`
- `femtobot/agent/context.py`: injeta `RuntimeContextBlock` no system prompt
  durante `_state_build`

**Critérios de aceite:**
- [ ] Em goal ativo, system prompt contém bloco `Goal (active)`
- [ ] Em ask pendente, contém bloco `Pending ask`
- [ ] Em goal bloqueado, contém bloco `Goal blocked`

---

## 6. Milestone M4 — Continuação multi-canal

### PR 4.1 — Generalizar `turn_continuation.py`
**Pré-requisitos:** M3 mergeado.
**Entregáveis:**
- `femtobot/session/turn_continuation.py`: enum `ContinuationKind`
  (`sustained_goal`, `ask_wait`, `goal_resume`)
- Promover `_MAX_GOAL_CONTINUATION_ROUNDS` para `long_task_config.max_goal_rounds`
- Helpers por `kind`

**Critérios de aceite:**
- [ ] Cada kind tem teste próprio
- [ ] Default 12 preservado quando config ausente

### PR 4.2 — `process_direct(goal_aware)` com fila efêmera
**Pré-requisitos:** PR 4.1.
**Entregáveis:**
- `femtobot/agent/loop.py`: `process_direct(execution_mode="goal_aware")` cria
  `pending_queue` local e propaga para `_process_message`
- Default controlado por `long_task_config.sdk_execution_mode`

**Critérios de aceite:**
- [ ] `execution_mode="sync"` mantém comportamento atual byte-a-byte
- [ ] `execution_mode="goal_aware"` permite continuação invisível
- [ ] Testes comparativos sync vs goal_aware

### PR 4.3 — `Femtobot.run()` aceita `execution_mode`
**Pré-requisitos:** PR 4.2.
**Entregáveis:**
- `femtobot/femtobot.py`: `Femtobot.run(message, *, session_key, execution_mode=None)`
- Default: `config.agents.defaults.long_task.sdk_execution_mode`

**Critérios de aceite:**
- [ ] SDK roda em modo goal_aware quando `byDefault=true`
- [ ] SDK roda em sync quando `byDefault=false`
- [ ] Override explícito pelo chamador funciona

### PR 4.4 — Testes E2E de continuação multi-canal
**Pré-requisitos:** PR 4.3.
**Entregáveis:**
- `tests/test_long_task_m4_e2e.py`:
  - Goal com 3 continuations via `process_direct(goal_aware)`
  - Goal com continuations via `Femtobot.run()`
  - Comparação byte-a-byte com `byDefault=false` em todos os caminhos

**Critérios de aceite:**
- [ ] Todos os cenários verdes
- [ ] Suite existente segue verde

---

## 7. Milestone M5 — API assíncrona

### PR 5.1 — Schemas de request/response para `async_goal`
**Pré-requisitos:** M4 mergeado.
**Entregáveis:**
- `femtobot/api/types.py` (ou similar): `AsyncGoalRequest`, `AsyncGoalResponse`
- Modelos Pydantic

**Critérios de aceite:**
- [ ] Validação de schema funciona
- [ ] Round-trip JSON estável

### PR 5.2 — Detecção de long task em `server.py`
**Pré-requisitos:** PR 5.1.
**Entregáveis:**
- `femtobot/api/server.py`: helper `should_async_goal(request, long_task_config)`
- Decide com base em `apiMode`, `byDefault`, headers do request

**Critérios de aceite:**
- [ ] Decisão é puramente funcional (testável)
- [ ] `apiMode=sync` ignora a heurística

### PR 5.3 — Endpoint principal `async_goal`
**Pré-requisitos:** PR 5.2.
**Entregáveis:**
- `POST /v1/...` com modo `async_goal`:
  - gera `goal_id`, `session_id`
  - enfileira job
  - responde `202 Accepted` com `poll_url`, `events_url`

**Critérios de aceite:**
- [ ] Request não bloqueia no goal inteiro
- [ ] Resposta sai em ≤ `api_async_accept_timeout_s`
- [ ] Job é processado assincronamente

### PR 5.4 — Endpoints auxiliares
**Pré-requisitos:** PR 5.3.
**Entregáveis:**
- `GET /v1/goals/{goal_id}`
- `GET /v1/goals/{goal_id}/events`
- `POST /v1/goals/{goal_id}/answer`

**Critérios de aceite:**
- [ ] Status retorna JSON com `status`, `objective`, `elapsed_s`
- [ ] Events retorna stream SSE ou NDJSON
- [ ] Answer aceita `correlation_id` opcional

### PR 5.5 — E2E supervisor chamando worker via HTTP
**Pré-requisitos:** PR 5.4.
**Entregáveis:**
- `tests/test_long_task_m5_e2e.py`:
  - supervisor envia goal
  - recebe `202`
  - poll até status terminal
  - verifica eventos publicados

**Critérios de aceite:**
- [ ] Tempo de resposta HTTP inicial < 1s
- [ ] Goal completo retorna status correto
- [ ] Modo `sync` segue funcionando

---

## 8. Milestone M6 — `ask_orchestrator`

### PR 6.1 — Tool `AskOrchestratorTool` (estrutura)
**Pré-requisitos:** M5 mergeado.
**Entregáveis:**
- `femtobot/agent/tools/ask_orchestrator.py`: classe com schema completo
- Implementação esqueleta (sem `pending_asks` ainda)

**Critérios de aceite:**
- [ ] Tool aparece no registry
- [ ] Sem persistência ainda — `pending_asks` retornaria erro claro

### PR 6.2 — Persistência de asks via `pending_asks`
**Pré-requisitos:** PR 6.1.
**Entregáveis:**
- `AskOrchestratorTool.execute`:
  1. gera `correlation_id`
  2. persiste ask antes de enviar
  3. envia `OutboundMessage` com `metadata["ask_correlation_id"]`
  4. marca goal como `waiting_on="ask_orchestrator"`

**Critérios de aceite:**
- [ ] Ask é persistido em metadata de sessão
- [ ] Restart preserva ask
- [ ] Mensagem outbound inclui correlation_id

### PR 6.3 — Retomada por `correlation_id`
**Pré-requisitos:** PR 6.2.
**Entregáveis:**
- `femtobot/agent/loop.py`:
  - helper `resolve_pending_ask(correlation_id, response)` 
  - enfileira `goal_resume` na fila da sessão
- Endpoint `POST /v1/goals/{goal_id}/answer` também resolve

**Critérios de aceite:**
- [ ] Resposta correta é casada com ask correto
- [ ] Goal retoma após resposta
- [ ] Resposta errada (correlation_id inválido) é rejeitada com erro claro

### PR 6.4 — Timeout e recovery
**Pré-requisitos:** PR 6.3.
**Entregáveis:**
- `pending_asks.expire_pending_asks()` chamado em `_state_build`
- Injeção de mensagem "ask timed out" no context
- Publicação de `AskStateChanged` em cada transição

**Critérios de aceite:**
- [ ] Após `deadline_at`, ask vira `timed_out`
- [ ] Goal recebe injeção orientando "use melhor hipótese ou block"
- [ ] Restart não perde asks

---

## 9. Milestone M7 — UX e polish

### PR 7.1 — `/goal cancel`
**Pré-requisitos:** M6 mergeado.
**Entregáveis:**
- `cmd_goal_cancel` em `builtin.py`

**Critérios de aceite:**
- [ ] Goal vira `cancelled`
- [ ] `GoalStateChanged` publicado
- [ ] Testes

### PR 7.2 — `/goal block`
**Pré-requisitos:** PR 7.1.
**Entregáveis:**
- `cmd_goal_block` em `builtin.py`
- Aceita `reason`

**Critérios de aceite:**
- [ ] Goal vira `blocked`
- [ ] Mensagem outbound para supervisor com reason
- [ ] Testes

### PR 7.3 — `/goal status` enriquecido
**Pré-requisitos:** PR 7.2.
**Entregáveis:**
- `cmd_goal_status` mostra:
  - status atual
  - objective
  - elapsed_s
  - pending_asks count
  - last event

**Critérios de aceite:**
- [ ] Output human-friendly
- [ ] Output JSON opcional para tooling

### PR 7.4 — `femtobot sessions list` com active goal
**Pré-requisitos:** PR 7.3.
**Entregáveis:**
- `femtobot/cli/commands.py`: nova coluna `active goal` na listagem
- Filtro opcional `--with-active-goal`

**Critérios de aceite:**
- [ ] Coluna visível quando há goal ativo
- [ ] Filtro funciona

### PR 7.5 — Documentação final
**Pré-requisitos:** PR 7.4.
**Entregáveis:**
- `docs/long-task-by-default.md`: guia de uso, exemplos, troubleshooting
- `README.md`: seção atualizada
- `docs/REFACTOR_PLAN.md`: nota de migração

**Critérios de aceite:**
- [ ] Documento cobre todos os caminhos (`bus`, `sdk`, `api`)
- [ ] README menciona `byDefault`

---

## 10. Sequência de execução recomendada

```
M0 (5 PRs)  ─► M1 (4 PRs) ─► M2 (4 PRs) ─► M3 (2 PRs)
                                          └► M4 (4 PRs) ─► M5 (5 PRs) ─► M6 (4 PRs) ─► M7 (5 PRs)
```

### Por que esta ordem

1. **M0 primeiro** porque é zero-impacto e fixa o vocabulário.
2. **M1 antes das tools** para garantir que o domínio do goal já tem
   estado, eventos e permissões antes de qualquer coisa ser exposta ao LLM.
3. **M2 antes de M3** porque tool visibility depende do goal domain.
4. **M3 antes de M4** porque runtime context é base para continuações
   semânticas.
5. **M4 antes de M5** porque `process_direct(goal_aware)` precisa existir
   antes da API assíncrona reusá-lo.
6. **M5 antes de M6** porque `ask_orchestrator` depende do protocolo de
   resposta da API.
7. **M7 por último** porque depende dos demais.

### Atalhos permitidos (apenas se a revisão liberar)

- M0 PRs 0.3 e 0.4 podem ser mergeados em paralelo (são módulos vazios
  independentes).
- M1 PRs 1.1 e 1.2 podem ser mergeados em paralelo.
- M2 PRs 2.1 e 2.2 podem ser mergeados em paralelo **se** o teste de
  registry for adicionado no PR 2.1 e o gating em 2.3.
- M5 PRs 5.1 e 5.2 podem ser mergeados em paralelo.

---

## 11. Critérios de aceite por milestone

### M0
- Suite existente verde; `byDefault=false` byte-equivalente; novos módulos
  sem side-effects.

### M1
- `/goal` cria goal real e publica evento; nenhum tool novo ainda.

### M2
- `long_task` e `complete_goal` funcionam; `complete_goal` visível em todo
  goal ativo (validado por teste explícito).

### M3
- System prompt contém bloco `Goal (active)` em goal ativo.

### M4
- `process_direct(goal_aware)` e `Femtobot.run()` rodam goals sem
  intervenção manual.

### M5
- Supervisor chama worker via HTTP com `async_goal`, recebe `202`, poll
  funciona.

### M6
- Worker pausa em dúvida crítica, retoma por `correlation_id`, restart
  preserva asks.

### M7
- Slash commands novos funcionam; CLI mostra coluna `active goal`;
  documentação completa.

---

## 12. Critérios de aceite globais (final do último PR)

- [ ] `byDefault=false` preserva comportamento atual byte-a-byte (regressão
      zero)
- [ ] `byDefault=true` funciona em `bus`, `process_direct`, `SDK` e `API`
- [ ] `complete_goal` permanece visível em todo turno com goal ativo
- [ ] `ask_orchestrator` funciona com `correlation_id` persistido
- [ ] Restart do processo não perde asks pendentes nem estado do goal
- [ ] API `sync` segue compatível
- [ ] API `async_goal` suporta polling/SSE
- [ ] Nenhum timeout externo HTTP mata long task no modo assíncrono
- [ ] Nenhum caminho permite loop infinito sem guardrail
- [ ] Cobertura de testes ≥ 85% nos novos módulos
- [ ] CI verde em todas as fases

---

## 13. Estimativa qualitativa (sem prazos)

| Milestone | Complexidade | Risco |
|---|---|---|
| M0 | baixa | baixo |
| M1 | média | baixo |
| M2 | média | médio (tool visibility é delicada) |
| M3 | baixa | baixo |
| M4 | alta | médio (`process_direct` afeta SDK e API) |
| M5 | alta | médio (contrato HTTP novo) |
| M6 | alta | alto (correlação + persistência + retomada) |
| M7 | baixa | baixo |

Os milestones de **maior risco** são **M5** e **M6**. M5 muda contrato
externo, M6 adiciona novo protocolo. Ambos exigem revisão dupla.

---

## 14. Próximos passos

1. Aprovar este plano de execução.
2. Criar branch `refactor/long-task-by-default` baseado em `main`.
3. Abrir PRs em ordem M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7.
4. Em cada PR: rodar suite completa + suite do milestone.
5. Gate de merge: ≥ 1 reviewer + CI verde + critérios de aceite do PR
   marcados.

> **Última nota:** o PR 0.1 e o PR 0.2 podem ser feitos juntos como um
> único PR inicial ("schema + loading") se o time preferir reduzir PRs.
> A separação aqui serve para isolar o impacto de cada commit.