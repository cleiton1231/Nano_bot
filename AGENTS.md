# AGENTS.md — nanobot pessoal (RAG faculdade + utilitário leve)

Documento de orquestração para o agente **Cursor** neste projeto.
Define escopo, arquitetura, regras de execução e quando cada skill deve
ser invocada. Isso não é um README de usuário — é a constituição do
agente para este projeto. Baseado em HKUDS/nanobot (Python, WebUI local,
tools, MCP, memória, canais de chat).

**Origem:** adaptado de `GEMINI.md` (histórico/fonte original — **não
editar** `GEMINI.md` neste fluxo de migração Cursor). Em caso de
divergência factual com o código, o código vence; atualizar **este**
arquivo (`AGENTS.md`), não silenciar a divergência.

**Convenção Cursor:** este arquivo é o instructions file do projeto.
Aprendizados cristalizados em sessão vão para
`.cursor/rules/nanobot-learnings.mdc` (append-only via skill
`consolidate-learning`), não para cá nem para `GEMINI.md`, salvo pedido
explícito separado.

---

## 1. Objetivo do projeto

Assistente pessoal local, rodando 100% na própria máquina via `llama.cpp`,
com dois usos concretos:

1. **RAG sobre notas e documentos de estudo** — indexar `.md` de um
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
- Escrita/edição/deleção no vault de notas de estudo (`faculdade/`) — o nanobot
  possui acesso **SOMENTE LEITURA** à pasta sincronizada pelo Syncthing.
  Write-back de qualquer tipo (anotação, resumo, tag) exige decisão
  explícita (Plan Mode / gate de bifurcação) antes de entrar em escopo.

Se alguma dessas entrar no roadmap no futuro, precisa passar por
**Plan Mode** (gate de decisão nativo do Cursor) antes de qualquer
implementação — são decisões de bifurcação que mudam a superfície de
risco do projeto inteiro, não features incrementais.

---

## 3. Stack técnica

- Python (base do nanobot, HKUDS/nanobot upstream).
- `llama.cpp` + `llama-server` (Vulkan/RADV GFX1200), endpoint
  OpenAI-compatible em `127.0.0.1:8080/v1` (`-c 16384` / context window de 16k tokens,
  necessário para acomodar system prompt do nanobot + schemas das tools).
- Modelos GGUF locais (ver Seção 4).
- Sandbox de exec via `bubblewrap` (`bwrap`).
- Isolamento de processo: usuário Linux dedicado (`nanobot-svc`) + `bwrap` nativo
  (sem Docker). Processo invocado sob demanda via CLI (`sudo -u nanobot-svc` ou wrapper
  `nanobot-local`), sem daemon persistente e sem root em nenhum momento.
  Tarefas em background (cron periódico, heartbeat de 30min e consolidação automática
  de memória) ficam fora de uso nesta configuração (dependem do modo gateway).
- `firewalld` como camada adicional de controle de saída, quando
  alguma tool de rede estiver habilitada.
- Invocação do CLI neste projeto: `uv run nanobot ...` ou
  `.venv/bin/nanobot ...` — nunca `~/.local/bin/nanobot` diretamente
  (shebang aponta para Python do sistema, sem deps do `.venv` como
  `sqlite-vec`).

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
falta o tensor `cls.output.weight`; scores saem lixo (~4.5e-23) em vez
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
├── faculdade/              # workspace RAG — só .md das notas de estudo
└── ~/.nanobot/config.json  # config real, chmod 600, nunca commitado
```

Referências no repo (fonte primária — não confiar em resumo
próprio quando essas existirem e divergirem):

| Referência                      | Onde                                                   | Pra que serve                                                                                       |
| ------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| Limites de segurança do projeto | `.agent/security.md`                                   | Fonte de verdade sobre fronteira de segurança — usar pra validar/corrigir a Seção 7 deste documento |
| Restrições de arquitetura       | `.agent/design.md`                                     | Decisões de design — relevante antes de questionar um default                                       |
| Módulo de segurança             | `nanobot/security/`                                    | Código real: SSRF, controle de acesso a workspace, rate limit, auditoria                            |
| Registro de tools               | `nanobot/agent/tools/registry.py`                      | Nome exato de cada tool registrada — confirmar chave certa se desativar via config não bastar       |
| Config schema                   | `nanobot/config/schema.py`, `nanobot/config/loader.py` | Schema Pydantic real — confirma quais chaves existem, incluindo aliases camelCase                   |
| Gotchas conhecidos              | `.agent/gotchas.md`                                    | Comportamentos não-óbvios já mapeados — ler antes de debugar algo "estranho" sozinho                |
| Regra de Verificação Empírica   | `.agent/rules/empirical_verification.md`               | Diretiva mandatória dos 3 estados exclusivos (VERIFICADO, NÃO VERIFICADO, DIVERGENTE)               |
| Skill de Auditoria de Segurança | `.agent/skills/security-audit/SKILL.md`                | Procedimento empírico de auditoria de rede, binds locais, capabilities e sandbox                    |
| Aprendizados Cursor (append)    | `.cursor/rules/nanobot-learnings.mdc`                  | Regras cristalizadas via `consolidate-learning`                                                     |
| Relatórios de Auditoria         | `docs/audits/`                                         | Histórico de auditorias empíricas formais e pareceres reconciliados do projeto                      |
| Fonte histórica (Antigravity)  | `GEMINI.md`                                            | Constituição original — intocada neste fluxo; preferir `AGENTS.md` no Cursor                        |

---

## 6. Critério importante — mapa de rede não é opinião, é levantamento a validar

Toda alegação sobre "isso sai da máquina" ou "isso é seguro por padrão"
neste documento (Seção 7) foi montada via docs públicas e busca web —
**não é fonte primária**. Antes de confiar cegamente, validar contra
`.agent/security.md` e `nanobot/security/` do repo real. Se o código
divergir do que está documentado aqui, o código vence — corrigir este
documento (`AGENTS.md`), não silenciar a divergência.

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
| Atualização de versão    | Manual              | Manual via `git pull` + `pip install -e .` (não há comando `nanobot update` no CLI) | Rodar manualmente, revisar changelog/commits antes                    |
| RAG vault (`studyRag.notesDir`) | Não (leitura local) | Lê paths arbitrários do config; módulo `nanobot/rag/` **não** consulta `tools.restrict_to_workspace` | Barreira real: ACL POSIX no host + path explícito no config; sem guard em app no RAG |

---

## 8. Orquestração de skills — quando usar cada uma (Cursor)

Skills de processo/usuário: `~/.cursor/skills/<nome>/SKILL.md`.
Skill de projeto no repo: `.agent/skills/security-audit/SKILL.md`.
Aprendizados locais: `.cursor/rules/nanobot-learnings.mdc`.

| Skill | Quando usar neste projeto |
| ----- | ------------------------- |
| `brainstorming` + `writing-plans` / Plan Mode | Obrigatório antes de mudança complexa multi-arquivo, multi-etapa, ou que toque schema/lógica core (ex: RAG, banco vetorial, adicionar dependência). Plan Mode nativo do Cursor cobre o gate de decisão (substitui `/grill-me`). |
| `requesting-code-review` / `review-bugbot` / `review-security` | Obrigatório após implementação não-trivial, antes de declarar a tarefa concluída. |
| `test-driven-development` | Obrigatório ao implementar lógica ou módulos novos (ex: pipeline RAG, parsers, stores). Red-Green-Refactor com output literal do teste falhando antes da implementação. |
| `dependency-audit` | Obrigatório antes de qualquer dependência Python nova (`pyproject.toml`) ou modelo/conversão GGUF nova. Nunca aceitar GGUF comunitário sem teste de sanidade real (cautela do reranker quebrado — Seção 4). |
| `security-audit` | Obrigatório para binds `127.0.0.1`, isolamento `bwrap`/namespaces, firewall do host e auditoria empírica de SSRF / DNS pinning. |
| `local-llm-serving` | Ao dimensionar VRAM, configurar portas/flags de `llama-server`, e testar endpoints de embedding, reranker e geração. |
| `systematic-debugging` | Obrigatório pra qualquer bug — scores de reranker suspeitos, rede inesperada, sandbox falhando silenciosamente. |
| `verification-before-completion` | Regra permanente genérica: nunca reportar "funcionando" sem comando fresco e output real. |
| `verification-before-completion-nanobot-addendum` | Sempre que alegar config efetivo/carregado ou código em produção — Regra 7 (UID, usuário, `Path.home()`, `get_config_path()`, `sys.executable`, `sys.prefix`, `module.__file__` no **mesmo** bloco). |
| `consolidate-learning` | Só sob pedido explícito ("consolidar aprendizado", "cristalizar regra", `/learn`). Append em `.cursor/rules/nanobot-learnings.mdc` com diff + aprovação. |
| `executing-plans` / `subagent-driven-development` | Ao executar plano escrito multi-etapa. |
| `top-web-vulnerabilities` | **Pendente** — não criada nesta migração; checklist OWASP complementar ao `security-audit` quando houver necessidade real. |
| `threat-modeling` | **Pendente** — não criada; considerar antes de superfície nova da Seção 2 (canal, MCP remoto, WebUI exposta). Scope minimalism: não criar skill para superfície fora de uso. |

---

## 9. Regras não-negociáveis

1. Nunca declarar "seguro" ou "funcionando" sem execução real mostrada
   (curl no `llama-server`, teste de score do reranker, `config.json`
   efetivo colado — não assumido). "Output esperado" ou qualquer
   previsão do que um script deveria imprimir NUNCA substitui output
   real colado do terminal.
2. Nunca habilitar `tools.web.enable`, canal de chat, ou MCP novo sem
   decisão consciente registrada — não é default, é opt-in.
3. Nunca aceitar conversão GGUF de reranker/embedding sem teste de
   sanidade (par relevante/irrelevante, scores separados).
4. Nunca rodar o nanobot como o usuário principal (`cleiton`) — invocar
   exclusivamente como `nanobot-svc` via `sudo -u` ou wrapper `nanobot-local`.
   Sem Docker, sem container.
5. `apiKey` de qualquer provider sempre via variável de ambiente,
   nunca em texto puro no `config.json`. `chmod 600` obrigatório.
6. Toda alegação sobre superfície de rede/segurança neste documento
   precisa ser validada contra `.agent/security.md` e
   `nanobot/security/` reais antes de virar decisão operacional —
   ver Seção 6.
7. Nenhuma alegação de "config efetivo/carregado" ou "código em execução"
   é válida sem o output do MESMO script mostrar explicitamente UID,
   usuário, `Path.home()`, `get_config_path()` resolvido e os paths reais
   de `sys.executable`, `sys.prefix` e do módulo Python inspecionado
   (`module.__file__`) — não basta rodar e imprimir os valores, tem que
   provar qual identidade/processo gerou aquele resultado e qual arquivo
   está sendo importado. Isso evita falsos positivos onde um teste roda como
   `cleiton` lendo `~/.nanobot/config.json` ou executando do checkout de
   desenvolvimento (`/home/cleiton/opencode/nanobot`), enquanto a produção
   sob `nanobot-svc` está lendo `/home/nanobot-svc/.nanobot/config.json` e
   importando de um `site-packages` copiado/separado.
   Comandos sob `sudo -u nanobot-svc`, o cwd do processo chamador é preservado —
   não reseta para o home de `nanobot-svc`. Evidência Regra 7 inválida se o cwd
   está no checkout dev: usar `cd /tmp &&` antes do comando de verificação.
8. O agente NUNCA deve propor adicionar `NOPASSWD` a sudoers (ou qualquer
   mecanismo que remova autenticação interativa de sudo) como forma de
   contornar bloqueio de automação — nem como "opção alternativa" ao lado
   de uma opção manual. Senhas e autenticação de privilégios de sudo nunca
   devem ser contornadas, enfraquecidas ou desabilitadas para conveniência
   do assistente.
9. Scripts de verificação/sincronização devem checar exit code
   explicitamente em cada etapa crítica (cp, diff, grep — `$? -eq 0` ou
   `set -euo pipefail`) antes de reportar sucesso. Nunca aceitar mensagem
   de "sucesso" de script sem confirmação independente (ex: grep direto
   no arquivo final, rodado à parte).
10. O nanobot tem acesso estritamente SOMENTE LEITURA à pasta de notas
    (`faculdade/`) sincronizada pelo Syncthing. Nenhuma escrita, edição ou
    deleção de arquivos `.md` do vault é permitida. Write-back de qualquer
    tipo (anotação, resumo, tag) exige decisão explícita (Plan Mode / gate
    de bifurcação) antes de entrar em escopo.
11. O pipeline de sincronização (`sync_notes()`) segue política *skip-and-log*:
    falha em uma nota (leitura em disco, decodificação/encoding inválido, erro
    de rede/timeout/resposta malformada de embedding) não aborta o lote, mas o
    resultado do sync deve expor contagem de sucesso/falha e lista de paths falhos,
    com exit code não-zero no CLI se `failed_count > 0`. Nunca reportar sucesso
    silencioso com falha pendente.
12. O pipeline de recuperação semântica adota arquitetura de dois estágios:
    KNN vetorial via `search_knn` busca `candidate_k` candidatos brutos (default 30,
    `ge=1, le=200` no `StudyRagConfig`), seguido por reranking fino via porta 8081
    que seleciona os `top_k` melhores (default 10). Se o KNN retornar menos candidatos
    que `top_k` (ex: vault inicial com poucas notas ou filtro restritivo de pasta),
    o pipeline processa e retorna os candidatos existentes sem erro (resultado parcial válido).
13. O subsistema de reranking (`RerankerClient` / porta 8081) adota política estrita
    de *fail-fast*: indisponibilidade da porta 8081, timeout de rede ou erro HTTP
    dispara `RerankerError` duro, sem fallback silencioso ou degradação não auditada
    nesta fase de homologação.
14. O filtro de relevância `score_threshold` é inicializado em `0.0` (permissivo)
    nesta fase — todos os candidatos rerankeados até `top_k` são retornados ordenados
    por relevância decrescente, sem descarte cego antes da calibração empírica com notas
    reais de estudo. O embedding de query é estritamente simétrico ao embedding de documentos
    (payload de texto puro sem prefixo artificial de instrução).
15. O retorno da ferramenta `search_study_notes` exposta ao agente segue contrato
    padronizado em blocos Markdown estruturados: título do documento, caminho/pasta,
    seção (`heading`), `relevance_score` formatado com 3 casas decimais (`{score:.3f}`)
    e o conteúdo literal do trecho.
16. O subsistema RAG (`nanobot/rag/`) não consulta
    `tools.restrict_to_workspace`. Esse guard protege apenas tools de
    exec/filesystem — não o pipeline de sync/search do RAG. A única
    barreira contra `study_rag.notes_dir` escapar do escopo pretendido
    é ACL POSIX aplicada manualmente no host sobre o path configurado.
    Isso é aceitável enquanto `notes_dir` for um subpath estreito e
    auditado (ex: `Puc/2026-2`), mas não escala sozinho: se
    `notes_dir` for ampliado (ex: para a raiz do vault) sem
    reaplicar/reconferir a ACL no novo escopo, ou se o path contiver
    um symlink que escape da árvore autorizada, não há segunda camada
    de defesa em nível de aplicação. Qualquer mudança de `notes_dir`
    deve reconfirmar a ACL do novo path antes do próximo sync — não
    assumir herança do escopo anterior.

---

## 10. Definição de pronto (DoD) — checklist operacional

Status: **100% VERIFICADA em 2026-08-24** (ver detalhes e evidências no histórico da [Seção 12](#12-notas-operacionais)).

- [x] `llama-server` local no ar e testado: `curl -s 127.0.0.1:8080/v1/models`
      confirmado com output real: `{"object":"list","data":[{"id":"Qwen3.5-9B-Q5_K_M.gguf",...}]}`,
      `n_ctx: 16384`, `ftype: "Q5_K - Medium"`, endpoint local respondendo com sucesso.
- [x] Reranker testado com par relevante/irrelevante — `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`
      rodando em `llama-server --rerank` na porta 8081, scores separados com sucesso:
      relevante (`0.9991523027420044`) vs irrelevante (`1.1015563359251246e-05`), output literal colado.
- [x] `restrict_to_workspace` ativo — testado e confirmado bloqueio real de leitura fora do workspace,
      leitura de `/etc/hosts`, escrita externa, listagem de `/etc`, exec com `working_dir` externo e
      exec referenciando caminhos fora do workspace (`/etc/passwd`).
- [x] Sandbox de kernel `bwrap` ativa e testada — ativada via `"tools": {"exec": {"sandbox": "bwrap"}}`
      no `config.json` de produção sob `/home/nanobot-svc/.nanobot/config.json`. `bwrap` isola `mnt`, `user` e
      `pid` namespaces via `--unshare-pid` (confinamento de filesystem, isolamento de processos em `/proc`
      com apenas PIDs da própria sandbox visíveis). `net` namespace permanece compartilhado com o host
      (necessário para acesso a `127.0.0.1:8080/8081`).
- [x] `channels: {}` confirmado no config real carregado — `config.channels.model_extra: {}`,
      0 canais/adaptadores externos configurados ou habilitados.
- [x] `web_search`/`web_fetch` desligados — confirmado no config efetivo com
      `"tools": {"web": {"enable": false}}`, com ausência total de `web_search` e `web_fetch` no `ToolRegistry`.
- [x] Invocação sob demanda como `nanobot-svc` confirmada via `ps` durante execução real do wrapper:
      PID rodando `/home/nanobot-svc/.venv/bin/python3 .../nanobot agent -m teste` sob usuário `nanobot-svc`
      (não `cleiton`, não `root`).
- [x] `config.json` com `chmod 600` confirmado via `sudo -u nanobot-svc ls -l /home/nanobot-svc/.nanobot/config.json`
      → `-rw-------. 1 nanobot-svc nanobot-svc`, sem chave em texto puro.
- [x] WebUI: N/A, confirmada como não instalada (`NANOBOT_SKIP_WEBUI_BUILD=1`), interface 100% CLI local.

---

## 11. Convenções

- Documentação em português (mesmo padrão do projeto de xadrez).
- Comandos e nomes de config em inglês (padrão upstream do nanobot).
- Commits pequenos, conventional commits, mensagem em inglês.
- Nunca commitar `~/.nanobot/config.json` real (tem estrutura de
  chave, mesmo sem valor de chave em texto puro — path de exemplo
  vai num `config.example.json` versionado, não o real).
- Invocação do CLI: `uv run nanobot ...` ou `.venv/bin/nanobot ...`;
  nunca `~/.local/bin/nanobot` diretamente (Python do sistema, sem
  `.venv`).

---

## 12. Notas operacionais

- `GEMINI.md` foi a constituição sob Antigravity (migrado do `AGENT.md`
  original em 2026-08-22). Em 2026-08-27 este `AGENTS.md` foi criado
  para o Cursor sem alterar `GEMINI.md`. Gate `/grill-me` foi substituído
  pelo Plan Mode nativo do Cursor.
- Histórico de auditoria em 2026-08-24:
  - Validação empírica de separação de scores do reranker `Qwen3-Reranker-0.6B-Q8_0` via `llama-server --rerank`.
  - Validação de restrição de workspace em ferramentas de filesystem e exec.
  - Correção de divergência do default upstream `tools.web.enable: true` para `false` explícito no `config.json`.
  - Cristalização da regra de identificação de identidade de processo (UID/Path.home/config_path) em scripts de verificação.
    - Hardening de PID namespace e incidente de sincronização concluídos em 2026-08-24:
      - Incidente de sincronização durante hardening `--unshare-pid`: script de sync imprimiu "Arquivo sincronizado com sucesso!" mesmo após `cp` falhar com "Permissão negada" — origem da regra 9.
      - Resolução com presença de `--unshare-pid` atestada via `grep` no `site-packages` real, suíte unitária aprovada (19/19 PASS) e isolamento de `/proc` (PIDs restritos) e rede (`llama-server 127.0.0.1:8080`) 100% verificados sob `nanobot-svc` (commits `1e795ba4` e `9a62623f`).
  - Fechamento de 100% da DoD operacional com execução real sob o usuário `nanobot-svc`.
  - Achados de auditoria colateral de rede/host (fora do escopo do nanobot, mas sanados nesta data):
    - **Firewall do host (Fedora / zona `FedoraWorkstation`)**: faixa indevida `1025-65535/tcp+udp` aberta sem motivo documentado foi removida e reduzida estritamente para as 3 portas que o Syncthing de fato utiliza (`22000/tcp`, `22000/udp`, `21027/udp` — essencial para a sincronização das notas de estudo, manter liberadas).
    - **MariaDB**: identificado bindado em `0.0.0.0:3306` por default de pacote (`bind-address` comentado no `.cnf`) e corrigido para `127.0.0.1`.
    - **Container Docker `nanobot_api`**: resquício de projeto não relacionado (`jarvis-gemini`) foi identificado inativo e completamente removido/confirmado ausente.
  - Relatório formal e consolidado da auditoria empírica arquivado em [`docs/audits/2026-08-24-empirical-audit.md`](./docs/audits/2026-08-24-empirical-audit.md).
- Histórico e notas de RAG em 2026-08-25:
  - Topologia confirmada: 8080 geração (`Qwen3.5-9B`), 8081 reranker (`Qwen3-Reranker-0.6B`), 8082 embedding (`Qwen3-Embedding-0.6B`).
  - Validação empírica do `Qwen3-Embedding-0.6B-Q8_0` baixado do repo oficial `Qwen/Qwen3-Embedding-0.6B-GGUF` (SHA-256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439` verificado contra LFS OID do Hugging Face).
  - Teste de sanidade do endpoint `http://127.0.0.1:8082/v1/embeddings` confirmado com vetor unitário de 1024 dimensões e separação semântica válida (Cálculo vs Limites: 0.7636 vs Cálculo vs Pão de Queijo: 0.5280).
  - Contrato de sincronização incremental: `sync_notes()` utiliza `rag_documents.checksum` (SHA-256) para decidir reprocessamento incremental — só re-embeda nota se o checksum divergir do salvo no banco. Arquivos `.md` que sumiram do vault disparam `delete_document()` automático (limpando dados relacionais e vetores no `vec0`).
  - Contrato de falha parcial: política *skip-and-log* no sync de notas — falha individual de nota (leitura, decode UTF-8 ou embedding) não aborta o lote, mas expõe métricas de sucesso/falha e paths com erro, resultando em exit code não-zero no CLI se `failed_count > 0`.
  - Contratos de retrieval e reranker (Fase B):
    - Dois estágios: KNN com `candidate_k` (default 30) para recall + Reranker (`Qwen3-Reranker-0.6B`) com `top_k` (default 10) para precisão. Retorno parcial sem erro se o pool for menor que `top_k`.
    - Fail-fast estrito: `RerankerClient` (porta 8081) levanta `RerankerError` se o endpoint falhar/timeout/down. Sem fallback silencioso nesta fase.
    - Threshold permissivo: `score_threshold` padrão em `0.0` até calibração com notas reais. Embeddings de query simétricos sem prefixo.
    - Formatação padronizada para tool `search_study_notes`: Markdown com título, caminho, heading, score (3 decimais) e conteúdo.
- **llama-server via systemd (2026-08-27 — débito fechado)**:
  - Os 3 processos `llama-server` (8080 geração, 8081 reranker, 8082 embedding) migraram de orquestração manual `nohup+disown` para units systemd em [`deploy/systemd/`](./deploy/systemd/): `User=nanobot-svc`, `Restart=on-failure`, `RestartSec=10`, bind `127.0.0.1`. Binário de runtime: `/usr/local/bin/llama-server` (cópia manual pós-build — ver README em `deploy/systemd/`). **`systemctl enable` não aplicado** — start manual; boot automático continua decisão futura separada.
  - **SELinux (achado permanente)**: systemd inicia serviços sob domínio `init_t`. SELinux nega `execute` de binário com contexto `user_home_t` nesse domínio — mesmo com permissões POSIX `755` OK e mesmo funcionando via `sudo -u` interativo (que herda `unconfined_t` do shell). Diagnóstico: `sudo ausearch -m avc -ts recent`. Fix aplicado: binário em `/usr/local/bin` (`bin_t` nativo), não executar direto do `$HOME` via systemd. **Não** usar `semanage`/`restorecon` como regra geral para binários dentro de home; preferir path fora do home para qualquer executável iniciado por unit systemd.
  - **Gotcha systemd**: `StartLimitIntervalSec` e `StartLimitBurst` pertencem à seção `[Unit]`, não `[Service]`. Em `[Service]` o parser não falha — só emite warning `Unknown key ... ignoring` no journal e ignora silenciosamente o rate-limit de restart.
- Histórico de automação e subagentes Antigravity em 2026-08-26:
  - **Aninhamento de subagentes customizados**: subagentes customizados (`.md`, `mainAgent: true`) **NÃO** devem invocar outro subagente via `invoke_subagent` no seu system prompt. O aninhamento de 2 níveis perde silenciosamente o retorno da tool call no runtime. Padrão operacional obrigatório: orquestração externa sequencial pela sessão principal (`sessão -> plan`, depois `sessão -> plan-critic`), conforme documentado em [`.agent/gotchas.md`](./.agent/gotchas.md).
  - **Débito técnico em transclusões Obsidian (`_IMAGE_EMBED_RE`)**: `_IMAGE_EMBED_RE` em `markdown.py` remove qualquer transclusão Obsidian `![[...]]` como se fosse imagem, incluindo transclusões de notas markdown (ex: `![[Resumo Cálculo]]`), que são silenciosamente descartadas do texto indexado pelo RAG em vez de expandidas/preservadas. Achado via `systematic-debugging-agent` em 2026-08-26. Se o vault usar transclusão de notas com frequência, isso é perda de conteúdo relevante — avaliar se vale restringir a regex a extensões de mídia (`\.(png|jpe?g|gif|webp|svg|bmp|pdf)`) antes de expandir Fase B.
- Migração Cursor em 2026-08-27:
  - Skills ativas de alta prioridade: `dependency-audit`, `local-llm-serving`, `verification-before-completion-nanobot-addendum`, `consolidate-learning`.
  - `threat-modeling` e `top-web-vulnerabilities` ficam pendentes até necessidade real.
  - Artefatos Antigravity (`.agents/agents/`, `.agent/gotchas.md`, etc.) mantidos sem limpeza.
