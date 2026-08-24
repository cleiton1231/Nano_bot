---
trigger: always_on
description: Exige os 3 estados de checklist (VERIFICADO, NÃO VERIFICADO, DIVERGENTE), inventário explícito de arquivos e ceticismo frente a docs.
---

# Regra de Verificação Empírica e Auditoria Técnica

Esta regra é mandatória para qualquer análise técnica, revisão de arquitetura, auditoria de segurança/rede ou checklist de conformidade neste repositório.

## 1. Os 3 Estados Exclusivos de Checklist
Qualquer item avaliado deve ser classificado exclusivamente em um destes três estados:

- **VERIFICADO**: O comando de inspeção empírica foi executado e seu output literal completo foi incluído na resposta.
- **NÃO VERIFICADO**: O arquivo relevante não existe ou não foi aberto/executado nesta sessão. Nunca assumir conformidade por omissão ou suposição.
- **DIVERGENTE**: O código/arquivo real contradiz a especificação do `AGENT.md` ou o requisito de segurança. Deve-se citar literalmente a divergência (o que o doc pede vs. o que o código faz).

> **Invariante**: É terminantemente proibido marcar `[x]` ou `✅` por inferência lógica, dedução teórica ou confiando cegamente em afirmações de documentações.

## 2. Inventário Obrigatório de Arquivos
Antes de emitir qualquer checklist ou parecer final:
- Apresente a lista explícita dos arquivos abertos e inspecionados durante a sessão.
- Se algum arquivo relevante para o escopo (ex.: `docker-compose.yml`, `docker-compose.bwrap.yml`, `.env*`, referências da Seção 7 do `AGENT.md`) estiver ausente dessa lista, o item correspondente DEVE permanecer como **NÃO VERIFICADO**.

## 3. Ceticismo Sistemático contra Documentação
- Todas as afirmações do `AGENT.md` ou de outros documentos de referência sobre o código (portas, flags, binds, capabilities, nomes de campos) são **hipóteses a verificar**, não verdades dadas.
- Valide empiricamente toda alegação contra a fonte primária (código-fonte, schemas Pydantic, arquivos compose, scripts).

## 4. Invariantes de Scripts de Diagnóstico e Automação
Todo script gerado para diagnóstico, verificação empírica, teste ou sincronização entre ambientes DEVE cumprir:
1. **Tratamento Estrito de Erros**: Conter obrigatoriamente `set -euo pipefail` (ou checagem estrita de `$? -eq 0` por comando) e NUNCA emitir mensagens de sucesso (`"OK"`, `"Sincronizado"`, `"Sucesso"`) sem validar previamente o código de saída de cada operação crítica (`cp`, `diff`, `grep`, `bwrap`).
2. **Isolamento de Logs Multi-Usuário**: Artefatos de log temporários em `/tmp` devem ser estritamente isolados por UID (ex.: `/tmp/diag_${EUID}/` ou `mktemp -d`) para evitar colisões de permissão entre usuários distintos (`cleiton` e `nanobot-svc`).
3. **Fronteira de Permissão entre Contas**: Nunca assumir que uma conta de serviço (`nanobot-svc`) possui permissão de leitura no `home` do usuário de desenvolvimento (`/home/cleiton/`). O compartilhamento de arquivos deve sempre ocorrer via local neutro (staging em `/tmp` com `chmod 644` criado pelo dono da origem) ou via privilégio administrativo explícito do operador.
4. **Verificação de Importação de Código Real**: Toda validação em ambiente de serviço deve inspecionar `sys.executable`, `sys.prefix` e o caminho real resolvido dos módulos (`module.__file__`) para garantir que o código testado corresponde ao checkout pretendido e não a cópias estáticas desatualizadas em `site-packages`.

