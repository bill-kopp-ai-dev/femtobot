#!/bin/bash
set -euo pipefail

# ==============================================================================
# 1. Nome do script: core_agent_lines.sh
# 2. Propósito: Script utilitário para contar e reportar linhas de código Python 
#    no projeto femtobot.
# 3. Uso: Executar diretamente no terminal:
#    ./core_agent_lines.sh
#
# 4. Descrição de cada função:
#    - count_top_level_py_lines(): Conta linhas em arquivos .py no diretório raiz (maxdepth 1).
#    - count_recursive_py_lines(): Conta linhas recursivamente em arquivos .py.
#    - count_skill_lines()       : Conta linhas em .md, .py e .sh (para skills).
#    - print_row()               : Formata e imprime uma linha do relatório.
#
# 5. Saída esperada:
#    femtobot line count
#    ==================
#    
#    Core runtime
#    ------------
#      agent/                 150 lines
#      bus/                    80 lines
#    ...
#
# 6. Notas sobre o que é contado e o que não é:
#    - agent/ só conta arquivos .py no nível superior
#    - tools/ é contado separadamente
#    - skills/ conta .md, .py e .sh
#    - Não inclui: command/, providers/, security/, templates/, femtobot.py, arquivos raiz
# ==============================================================================

# Garante que o script será executado a partir do diretório onde ele se encontra
cd "$(dirname "$0")" || exit 1

# Conta linhas em arquivos .py no diretório raiz (maxdepth 1)
count_top_level_py_lines() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    echo 0
    return
  fi
  find "$dir" -maxdepth 1 -type f -name "*.py" -print0 | xargs -0 cat 2>/dev/null | wc -l | tr -d ' '
}

# Conta linhas recursivamente em arquivos .py
count_recursive_py_lines() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    echo 0
    return
  fi
  find "$dir" -type f -name "*.py" -print0 | xargs -0 cat 2>/dev/null | wc -l | tr -d ' '
}

# Conta linhas em .md, .py e .sh (para skills)
count_skill_lines() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    echo 0
    return
  fi
  find "$dir" -type f \( -name "*.md" -o -name "*.py" -o -name "*.sh" \) -print0 | xargs -0 cat 2>/dev/null | wc -l | tr -d ' '
}

# Formata e imprime uma linha do relatório com a contagem
print_row() {
  local label="$1"
  local count="$2"
  printf "  %-16s %6s lines\n" "$label" "$count"
}

echo "femtobot line count"
echo "=================="
echo ""

echo "Core runtime"
echo "------------"
core_agent=$(count_top_level_py_lines "femtobot/agent")
core_bus=$(count_top_level_py_lines "femtobot/bus")
core_config=$(count_top_level_py_lines "femtobot/config")
core_cron=$(count_top_level_py_lines "femtobot/cron")
core_session=$(count_top_level_py_lines "femtobot/session")

print_row "agent/" "$core_agent"
print_row "bus/" "$core_bus"
print_row "config/" "$core_config"
print_row "cron/" "$core_cron"
print_row "session/" "$core_session"

core_total=$((core_agent + core_bus + core_config + core_cron + core_session))

echo ""
echo "Separate buckets"
echo "----------------"
extra_tools=$(count_recursive_py_lines "femtobot/agent/tools")
extra_skills=$(count_skill_lines "femtobot/skills")
extra_api=$(count_recursive_py_lines "femtobot/api")
extra_cli=$(count_recursive_py_lines "femtobot/cli")
extra_channels=$(count_recursive_py_lines "femtobot/channels")
extra_utils=$(count_recursive_py_lines "femtobot/utils")

print_row "tools/" "$extra_tools"
print_row "skills/" "$extra_skills"
print_row "api/" "$extra_api"
print_row "cli/" "$extra_cli"
print_row "channels/" "$extra_channels"
print_row "utils/" "$extra_utils"

extra_total=$((extra_tools + extra_skills + extra_api + extra_cli + extra_channels + extra_utils))

echo ""
echo "Totals"
echo "------"
print_row "core total" "$core_total"
print_row "extra total" "$extra_total"

echo ""
echo "Notes"
echo "-----"
echo "  - agent/ only counts top-level Python files under femtobot/agent"
echo "  - tools/ is counted separately from femtobot/agent/tools"
echo "  - skills/ counts .md, .py, and .sh files"
echo "  - not included here: command/, providers/, security/, templates/, femtobot.py, root files"
