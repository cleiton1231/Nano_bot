---
name: consolidate-learning
description: Use when the user explicitly asks to consolidate learning, crystallize a rule, or run /learn — after a closed bugfix, architecture decision, or discovered gotcha in the current session.
---

# Consolidate Learning (/learn)

## Overview

Cristaliza um aprendizado **já fechado nesta sessão** em regra local do projeto nanobot, para sessões futuras carregarem automaticamente.

**Core principle:** Append-only, com data, após aprovação explícita. Nunca reescrever histórico. Nunca tocar `GEMINI.md`.

## When to Use

**Only when the user explicitly asks**, e.g.:
- "consolidar aprendizado"
- "cristalizar regra"
- "/learn"

**When NOT to use:** espontaneamente ao fim de toda tarefa; mudanças em `GEMINI.md`; reescrever gotchas antigos sem pedido.

## Target file (projeto nanobot)

Arquivo acumulado de regras locais (Cursor always-apply):

```
.cursor/rules/nanobot-learnings.mdc
```

Se o arquivo ainda não existir, o primeiro append **cria** o arquivo com frontmatter mínimo + a entrada nova — ainda assim só após aprovação do diff.

**Não editar:** `GEMINI.md`, `AGENTS.md` (salvo pedido explícito separado), nem skills em `~/.cursor/skills/` por este fluxo (aprendizados do *projeto* ficam no repo).

## Process

1. **Identificar o aprendizado fechado** nesta sessão (bug, decisão, gotcha). Se ambíguo, perguntar qual.
2. **Ler** `.cursor/rules/nanobot-learnings.mdc` (ou notar ausência).
3. **Redigir uma entrada objetiva** (não ensaio):
   - Data ISO (`YYYY-MM-DD`)
   - Título curto
   - Regra/ação concreta (o que fazer / o que nunca fazer)
   - Contexto mínimo (1–3 linhas) + evidência se houver
4. **Mostrar o diff proposto** (unified ou before/after) e **parar**.
5. **Só escrever o arquivo** após aprovação explícita do usuário.
6. Se rejeitado, revisar a proposta — não aplicar “quase igual”.

## Entry template

```markdown
## YYYY-MM-DD — <título curto>

**Regra:** <imperativo concreto>

**Contexto:** <1–3 linhas do que foi fechado nesta sessão>

**Evidência (opcional):** <veredito, path, issue, comando>
```

## Hard rules

- **Append only** — nunca deletar, reordenar ou reescrever entradas anteriores.
- **Não tocar `GEMINI.md`.**
- **Diff + aprovação antes de write** — aplicar direto é violação.
- Uma entrada por aprendizado (não misturar temas).

## Red Flags — STOP

- Começar a editar sem mostrar diff
- "Atualizar" entrada antiga em vez de append
- Propor mudança em `GEMINI.md` por este fluxo
- Consolidar aprendizado ainda aberto / não verificado
- Skill disparar sem pedido explícito do usuário

## Rationalizations

| Excuse | Reality |
|--------|---------|
| "É óbvio, aplico direto" | Diff + aprovação sempre. |
| "Melhor reescrever a entrada velha" | Append-only. Nova data, nova entrada. |
| "Cabe melhor no GEMINI.md" | Este fluxo não toca `GEMINI.md`. |
| "Vou consolidar sem o usuário pedir" | Só sob pedido explícito. |
