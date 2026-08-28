#!/usr/bin/env bash
# DoD empírico — lifecycle LLM on-demand (Regra 9: exit codes explícitos).
set -euo pipefail

WRAPPER="${WRAPPER:-/usr/local/bin/nanobot-local}"
if [[ ! -x "$WRAPPER" ]]; then
  WRAPPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/nanobot-local"
fi

run() {
  echo "cleiton@host:\$(pwd)\$ $*"
  "$@"
  echo "exit=$?"
  echo
}

check_no_orphan_llama() {
  echo "cleiton@host:\$(pwd)\$ ps aux | grep '[l]lama-server'"
  set +e
  ps aux | grep '[l]lama-server'
  local match_exit=$?
  set -e
  echo "match_exit=${match_exit}"
  echo
}

section() {
  echo "################################################################"
  echo "# $*"
  echo "################################################################"
  echo
}

section "Task 3.1 — garantir down inicial"
run sudo systemctl stop llama-server-generation.service llama-server-reranker.service llama-server-embedding.service
for u in llama-server-generation llama-server-reranker llama-server-embedding; do
  run systemctl is-active "${u}.service" || true
done
check_no_orphan_llama

section "Task 3.2 — cold start rag sync (só 8082)"
run "$WRAPPER" rag sync 2>&1 | tee /tmp/dod-sync.log
grep -E 'starting llama-server-(embedding|generation|reranker)' /tmp/dod-sync.log || true
if grep -q 'starting llama-server-generation' /tmp/dod-sync.log \
   || grep -q 'starting llama-server-reranker' /tmp/dod-sync.log; then
  echo "FALHA: sync subiu generation ou reranker (esperado só embedding)" >&2
  exit 1
fi

section "Task 3.3 — cold start rag search (8081+8082)"
run sudo systemctl stop llama-server-generation.service llama-server-reranker.service llama-server-embedding.service
run "$WRAPPER" rag search "vim comandos" 2>&1 | tee /tmp/dod-search1.log
if grep -q 'starting llama-server-generation' /tmp/dod-search1.log; then
  echo "FALHA: search subiu generation (esperado 8081+8082 only)" >&2
  exit 1
fi

section "Task 3.4 — skip start (segunda invocação search)"
run "$WRAPPER" rag search "vim comandos" 2>&1 | tee /tmp/dod-search2.log
grep 'already up — skip start' /tmp/dod-search2.log

section "Task 3.5 — cold start agent (os 3)"
run sudo systemctl stop llama-server-generation.service llama-server-reranker.service llama-server-embedding.service
run "$WRAPPER" agent -m "responda apenas: ok" 2>&1 | tee /tmp/dod-agent.log

section "Task 3.6 — llm status (up)"
run "$WRAPPER" llm status

section "Task 3.7 — llm stop + confirmação"
run "$WRAPPER" llm stop
for u in llama-server-generation llama-server-reranker llama-server-embedding; do
  run systemctl is-active "${u}.service" || true
done
check_no_orphan_llama

section "Task 3.8 — llm status (down, exit não-zero esperado)"
set +e
"$WRAPPER" llm status
echo "llm_status_down_exit=$?"
set -e

echo "DoD script concluído."
