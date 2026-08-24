# GEMINI.md — nanobot pessoal (RAG faculdade + utilitário leve)

Documento raiz de orquestração para o agente que implementa neste projeto.
Define escopo, arquitetura, regras de execução e quando cada skill deve
ser invocada. Isso não é um README de usuário — é a constituição do
agente para este projeto. Baseado em HKUDS/nanobot (Python, WebUI local,
tools, MCP, memória, canais de chat).

---

## 1. Objetivo do projeto

Assistente pessoal local, rodando 100% na própria máquina via `llama.cpp`,
com dois usos concretos:

1. **RAG sobre as notas da faculdade (PUC Minas)** — indexar `.md` de um
   workspace dedicado, recuperar trechos relevantes via embedding +
   reranker, responder perguntas com contexto real das notas.
2. **Utilitário leve de texto do dia a dia** — tarefas pontuais, sem
   virar hub de automação.

Não é um projeto de infraestrutura multi-canal. O valor está em ser
**local, privado e pequeno o suficiente pra auditar sozinho** — cada
superfície nova (canal de chat, MCP remoto, tool de rede) é decisão
consciente, nunca default silencioso.

---

## 2. Escopo e não-escopo

### Dentro do escopo

- Inferência local via `llama-server` (Vulkan/RADV, RX 9060 XT 16GB).
- RAG sobre workspace de faculdade (embedding + reranker + geração).
- Isolamento de processo/sandbox/firewall de saída.
- Config mínima segura, auditável, sem chave em texto puro.

### Fora do escopo (não pular pra isso sem decisão explícita)

- Canais de chat externos (Telegram, Discord, WhatsApp) — esse bot não
  precisa ficar acessível de fora.
- MCP remoto sem necessidade comprovada — cada MCP é uma conexão de
  saída própria assumida conscientemente, não added by default.
- Deploy em nuvem/Render — projeto é local-only por design.
- WebUI exposta na LAN — bind sempre em `127.0.0.1`; acesso remoto é
  via túnel SSH, nunca porta aberta.

Se alguma dessas entrar no roadmap no futuro, precisa passar por
`/grill-me` antes de qualquer plano — são decisões de bifurcação que
mudam a superfície de risco do projeto inteiro, não features incrementais.

---

## 3. Stack técnica

- Python (base do nanobot, HKUDS/nanobot upstream).
- `llama.cpp` + `llama-server` (Vulkan/RADV GFX1200), endpoint
  OpenAI-compatible em `127.0.0.1:8080/v1`.
- Modelos GGUF locais (ver Seção 4).
- Sandbox de exec via `bubblewrap` (`bwrap`).
- Isolamento de processo: usuário Linux dedicado (`nanobot-svc`) ou
  Docker com override de bwrap.
- `firewalld` como camada adicional de controle de saída, quando
  alguma tool de rede estiver habilitada.

---

## 4. Modelos e orçamento de VRAM (16 GB)

| Papel            | Modelo               |  Quant | Tamanho aprox. | Nota                                     |
| ---------------- | -------------------- | -----: | -------------: | ---------------------------------------- |
| Geração/resposta | Qwen3.5-9B           | Q5_K_M |        ~6,5 GB | pick #1 generalista                      |
| Embedding (RAG)  | Qwen3-Embedding-0.6B |   Q8_0 |        ~0,6 GB | recupera trechos, não gera texto         |
| Reranker (RAG)   | Qwen3-Reranker-0.6B  |   Q8_0 |        ~0,6 GB | reordena trechos antes do contexto final |

Soma residente: ~7,7 GB + KV cache/contexto/buffers — dentro da faixa
"confortável" (8–11 GB). Cabe rodar os três junto sem disputar VRAM com
desktop/editor.

**Upgrade condicional, não default**: se o embedding 0.6B mostrar recall
ruim nas perguntas reais sobre as notas, subir pra
Qwen3-Embedding-4B Q6_K (~3,3 GB) — total sobe pra ~10,4 GB (faixa
"utilizável", controlar contexto). Não trocar preventivamente; só depois
de evidência real de recall insuficiente.

### Cautela nomeada: conversões GGUF do reranker frequentemente quebradas

A maioria das conversões comunitárias do Qwen3-Reranker está quebrada —
falta o tensor `cls.output.weight`, scores saem lixo (~4.5e-23) em vez
de relevância real (`ggml-org/llama.cpp#16407`, `#17743`). Usar apenas:

- `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`, ou
- `Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp`

**Nunca aceitar reranker como "funcionando" sem teste real**: rodar
query com um doc relevante e um irrelevante, conferir que
`relevance_score` fica de fato separado (perto de 1 vs. perto de 0). Se
vier achatado, a conversão está quebrada — não é bug do nanobot, é
conversão ruim, trocar de repo.

---

## 5. Estrutura relevante

```
nanobot-workspace/
├── faculdade/              # workspace RAG — só .md das notas PUC Minas
└── ~/.nanobot/config.json  # config real, chmod 600, nunca commitado
```

Referências no repo upstream (fonte primária — não confiar em resumo
próprio quando essas existirem e divergirem):

| Referência                      | Onde                                                   | Pra que serve                                                                                       |
| ------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| Limites de segurança do projeto | `.agent/security.md`                                   | Fonte de verdade sobre fronteira de segurança — usar pra validar/corrigir a Seção 7 deste documento |
| Restrições de arquitetura       | `.agent/design.md`                                     | Decisões de design — relevante antes de questionar um default                                       |
| Módulo de segurança             | `nanobot/security/`                                    | Código real: SSRF, controle de acesso a workspace, rate limit, auditoria                            |
| Registro de tools               | `nanobot/agent/tools/registry.py`                      | Nome exato de cada tool registrada — confirmar chave certa se desativar via config não bastar       |
| Config schema                   | `nanobot/config/schema.py`, `nanobot/config/loader.py` | Schema Pydantic real — confirma quais chaves existem, incluindo aliases camelCase                   |
| Gotchas conhecidos              | `.agent/gotchas.md`                                    | Comportamentos não-óbvios já mapeados — ler antes de debugar algo "estranho" sozinho                |

---

## 6. Critério importante — mapa de rede não é opinião, é levantamento a validar

Toda alegação sobre "isso sai da máquina" ou "isso é seguro por padrão"
neste documento (Seção 7) foi montada via docs públicas e busca web —
**não é fonte primária**. Antes de confiar cegamente, validar contra
`.agent/security.md` e `nanobot/security/` do repo real. Se o código
divergir do que está documentado aqui, o código vence — corrigir este
documento, não silenciar a divergência.

Isso é o mesmo princípio de "toda alegação de performance é hipótese a
medir" do projeto de xadrez, aplicado a segurança: toda alegação de
superfície de rede é hipótese a confirmar contra o código-fonte real.

---

## 7. Superfícies de rede — mapeamento explícito

| Superfície               | Sai da máquina?     | Comportamento padrão                                                        | Decisão                                                               |
| ------------------------ | ------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| WebUI                    | Não aplicável       | Upstream suporta bind `127.0.0.1:8765`, mas não instalada neste setup (`NANOBOT_SKIP_WEBUI_BUILD=1`) | Não instalada — interface 100% CLI local                             |
| Web search               | **Sim**             | Provider padrão DuckDuckGo, sem API key — cada busca sai                    | Desativado por padrão (`tools.web.enable: false`)                     |
| Web fetch                | **Sim**             | Busca URLs arbitrárias decididas pelo LLM; SSRF guard embutido              | Manter SSRF guard ligado; não adicionar CIDR exceção sem motivo forte |
| MCP servers              | **Depende**         | Cada MCP = conexão de saída própria (stdio local ou HTTP/SSE remoto)        | Só adicionar MCP configurado explicitamente                           |
| Canais de chat           | **Sim**             | Cada canal exige token próprio, sessão de longa duração com serviço externo | Nenhum canal habilitado — fora do escopo (Seção 2)                    |
| Langfuse (observability) | Sim, se configurado | Opcional, exige chave própria                                               | Confirmar ausência de bloco `langfuse` no config                      |
| Deploy cloud             | Sim, se usado       | Só relevante se seguir botão de deploy do README upstream                   | Não usar — projeto é local-only                                       |
| Atualização de versão    | Manual              | `nanobot update` é comando explícito                                        | Rodar manualmente, revisar changelog antes                            |

---

## 8. Orquestração de skills — quando usar cada uma

| Skill                             | Quando usar neste projeto                                                                                                                                                                                                                                                                                                  |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `concise-planning`                | Obrigatório antes de qualquer mudança que toque config + código, ou seja multi-etapa (ex: trocar modelo de embedding, adicionar MCP novo, mudar isolamento de processo).                                                                                                                                                   |
| `grounded-planning`               | Obrigatório em conjunto com `concise-planning` sempre que a mudança tocar superfície de rede (Seção 7), config de segurança (Seção 9), ou decisão que se propaga (ex: trocar de usuário dedicado pra Docker). Toda linha da Seção 7 precisa estar verificada contra `nanobot/security/` real, não assumida da doc pública. |
| `dependency-audit`                | Obrigatório antes de qualquer modelo GGUF novo ou dependência Python nova. Aplica-se também a **conversões de modelo** — a cautela do reranker quebrado (Seção 4) é o motivo desta linha existir: nunca aceitar um GGUF comunitário sem teste de sanidade real.                                                            |
| `systematic-debugging`            | Obrigatório pra qualquer bug — principalmente scores de reranker suspeitos, comportamento de rede inesperado, ou sandbox falhando silenciosamente.                                                                                                                                                                         |
| `verification-before-attestation` | Regra permanente. Nunca reportar "reranker funcionando", "sandbox ativo" ou "nenhuma tool de rede habilitada" sem rodar de fato e colar o output real (curl, teste de score, `config.json` efetivo pós-load).                                                                                                              |
| `threat-modeling`                 | Considerar antes de qualquer superfície nova da Seção 2 (canal de chat, MCP remoto, WebUI exposta) — não é bloqueante hoje porque nenhuma dessas está em uso, mas se entrar, passa por aqui primeiro.                                                                                                                      |

---

## 9. Regras não-negociáveis

1. Nunca declarar "seguro" ou "funcionando" sem execução real mostrada
   (curl no `llama-server`, teste de score do reranker, `config.json`
   efetivo colado — não assumido).
2. Nunca habilitar `tools.web.enable`, canal de chat, ou MCP novo sem
   decisão consciente registrada — não é default, é opt-in.
3. Nunca aceitar conversão GGUF de reranker/embedding sem teste de
   sanidade (par relevante/irrelevante, scores separados).
4. Nunca rodar o nanobot com o usuário principal (`cleiton`) em uso
   contínuo — usuário dedicado ou container.
5. `apiKey` de qualquer provider sempre via variável de ambiente,
   nunca em texto puro no `config.json`. `chmod 600` obrigatório.
6. Toda alegação sobre superfície de rede/segurança neste documento
   precisa ser validada contra `.agent/security.md` e
   `nanobot/security/` reais antes de virar decisão operacional —
   ver Seção 6.

---

## 10. Definição de pronto (DoD) — checklist operacional

Antes de considerar a configuração "pronta pra rodar de fato":

- [ ] `llama-server` local no ar e testado: `curl 127.0.0.1:8080/v1/models`
      com output colado.
- [ ] Reranker testado com par relevante/irrelevante — scores
      realmente separados (não achatados), output colado.
- [ ] `restrict_to_workspace` ativo, workspace = só a pasta da
      faculdade (+ o que mais for decidido explicitamente).
- [ ] `channels: {}` confirmado no config real carregado (não só no
      arquivo — no que o processo efetivamente leu).
- [ ] `web_search`/`web_fetch` desligados, ou ligados com provider e
      custo/rate limit conscientes e documentados aqui.
- [ ] Rodando como usuário dedicado ou container — confirmar via `ps`/
      `whoami` do processo real, não assumir.
- [ ] `config.json` com `chmod 600` confirmado (`ls -l` colado), sem
      chave em texto puro (grep confirmando uso de env var).
- [ ] WebUI só em `127.0.0.1` — confirmar via `curl` de outro host
      falhando, não só ler a config.

---

## 11. Convenções

- Documentação em português (mesmo padrão do projeto de xadrez).
- Comandos e nomes de config em inglês (padrão upstream do nanobot).
- Commits pequenos, conventional commits, mensagem em inglês.
- Nunca commitar `~/.nanobot/config.json` real (tem estrutura de
  chave, mesmo sem valor de chave em texto puro — path de exemplo
  vai num `config.example.json` versionado, não o real).

---

## 12. Notas operacionais

- Este documento foi migrado do `AGENT.md` original em 2026-08-22,
  reestruturado no padrão de governança do projeto xadrez
  (`github.com/cleiton1231/xadrez`), que já provou reduzir alegação
  não verificada e cristalizar decisão de bifurcação via `/grill-me`
  antes de `/plan`.
- Pendência conhecida herdada do `AGENT.md`: nenhuma das validações da
  Seção 10 foi confirmada com evidência literal ainda neste projeto —
  isso é o próximo passo real, não decoração de documento.
