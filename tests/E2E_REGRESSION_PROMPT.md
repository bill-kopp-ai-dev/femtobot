# E2E Regression Prompt — femtobot v0.1.x context-loss bug

**Cole o bloco abaixo no CLI do femtobot e compartilhe o resultado comigo.**

---

## Prompt (cole exatamente assim)

```
Open 6 different files in this repo (any .py files), summarise what each
one does, and then call the agy MCP server's list tools to confirm MCP
is reachable. Use exec to run `ls -la femtobot/agent` afterwards so I
can see you really touched the filesystem. If anything fails, do NOT
give up — try a different approach and explain what changed.
```

---

## O que esse prompt testa

O bug original era: o `runner.py` chamava `_microcompact` **incondicionalmente** em todo turno, destruindo resultados de `read_file` / `exec` / `grep` assim que a conversa tinha mais de 10 outputs de tools. O agente perdia o contexto e entrava em loop na auto-correção "described an action but did not include any tool call".

Este prompt força os 4 cenários que comprovam o fix:

| # | Cenário | Sintoma que indicaria regressão |
|---|---|---|
| 1 | Ler **6 arquivos** diferentes e produzir sumários coerentes | Sumários vazios, sumários referenciando "[previous content omitted]", ou o agente dizendo que não consegue ler |
| 2 | Chamar o servidor MCP `agy` (listagem de tools) | Erro "MCP not connected", "tool not found", ou o agente descrevendo a chamada em prosa |
| 3 | Rodar `ls -la femtobot/agent` via `exec` | Erro de permissão, output ausente, ou o agente inventando o output |
| 4 | **Não entrar em loop** | Repetição da mensagem "your previous reply described an action ('...') but did not include any tool call" mais de 1 vez |

---

## O que me enviar de volta

Por favor compartilhe:

1. **A transcrição completa** da sessão (texto + tool calls + tool results)
2. **O resultado final** dos 4 critérios acima:
   - ( ) ✅ ou ❌ — Agente leu os 6 arquivos e produziu sumários coerentes
   - ( ) ✅ ou ❌ — Agente chamou o MCP `agy` e reportou as tools
   - ( ) ✅ ou ❌ — Agente executou `ls -la femtobot/agent` e citou o output real
   - ( ) ✅ ou ❌ — Sessão **NÃO** entrou em loop de auto-correção

3. Se houver **qualquer** mensagem de erro ou comportamento estranho, copie o trecho exato.

---

## Validação adicional (opcional, se quiser ser rigoroso)

Se quiser rodar o smoke-test automático **antes** de fazer o teste manual, execute:

```bash
cd /home/bill/Codes/CLI-router-project/femtobot
source .venv/bin/activate
python tests/e2e_regression_prompt.py
```

Esse script valida 5 invariantes do pipeline sem precisar de LLM/MCP e deve imprimir `ALL CHECKS PASSED`.

---
