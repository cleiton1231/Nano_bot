# AGENT.md — nanobot pessoal (RAG faculdade + utilitário leve)

> Baseado em HKUDS/nanobot (Python, WebUI local, tools, MCP, memória, canais de chat).
> Escopo deste documento: como este agente deve se comportar nesta máquina — não é o AGENTS.md interno do projeto nanobot.

## 0. Princípios não-negociáveis

1. **Privacidade e dados no host por padrão.** Nada sai da máquina que não seja explicitamente autorizado (busca web, canal de chat, MCP externo).
2. **Ajuste mínimo, não reescrita.** Usar os mecanismos de config/sandbox que o nanobot já expõe. Não fork, não patch de segurança "por conta própria" sem necessidade comprovada.
3. **Leve e utilitário.** Esse bot serve pra RAG sobre as notas da faculdade e tarefas de texto do dia a dia. Não é pra virar hub de automação com 10 canais de chat e 5 MCPs — cada superfície nova é mais rede exposta.
4. **Sem WebUI/gateway na LAN.** Bind em `127.0.0.1`. Se precisar acessar de outro dispositivo, usar túnel SSH, não abrir porta.

---

## 1. Hardware e inferência local

| Item | Valor |
|---|---|
| GPU | ASRock Radeon RX 9060 XT Steel Legend OC **16 GB** |
| Backend | `llama.cpp` com Vulkan (RADV GFX1200), já validado no Fedora |
| Servidor | `llama-server`, endpoint OpenAI-compatible em `127.0.0.1:8080/v1` |

O nanobot **não roda inferência própria** — ele fala com o `llama-server` via provider OpenAI-compatible. Isso já é bom pra privacidade: o LLM fica atrás de um endpoint local, sem SDK de nuvem, sem chave de API saindo da máquina.

Configuração de provider (`~/.nanobot/config.json`, exemplo mínimo):

```json
{
  "providers": {
    "local": {
      "apiBase": "http://127.0.0.1:8080/v1",
      "apiKey": "not-needed"
    }
  }
}
```

Não usar `0.0.0.0` no `llama-server` a menos que você realmente precise servir outro host — mantém a superfície de ataque em loopback.

---

## 2. Modelos recomendados (16 GB, papéis separados)

Reaproveitando o catálogo já validado (`Modelos locais RX 9060 XT`), com um adicional específico pra RAG que não estava lá: um **reranker**.

| Papel | Modelo | Quant | Tamanho aprox. | Nota |
|---|---|---:|---:|---|
| Geração/resposta | Qwen3.5-9B | Q5_K_M | ~6,5 GB | já é o seu pick #1 generalista |
| Embedding (RAG) | Qwen3-Embedding-0.6B | Q8_0 | ~0,6 GB | recupera trechos, não gera texto |
| **Reranker (RAG) — novo** | Qwen3-Reranker-0.6B | Q8_0 | ~0,6 GB | reordena os trechos recuperados antes de montar o contexto |

Soma residente simultânea: ~7,7 GB + KV cache/contexto/buffers → folga real dentro da faixa "confortável" da sua própria tabela (8–11 GB). Dá pra rodar os três ao mesmo tempo sem disputar VRAM com o Zed/desktop.

### Cautela importante sobre o reranker

A maioria das conversões GGUF comunitárias do Qwen3-Reranker está **quebrada**: falta o tensor `cls.output.weight`, e o modelo retorna scores lixo (~4.5e-23) em vez de relevância real (ver `ggml-org/llama.cpp#16407` e `#17743`). Use uma conversão feita com `convert_hf_to_gguf.py` oficial, verificada:

- `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` (conversão oficial ggml-org), ou
- `Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp` (verificado, scores corretos).

Servir:

```bash
llama-server \
  -m Qwen3-Reranker-0.6B-Q8_0.gguf \
  --reranking --pooling rank --embedding \
  --ctx-size 8192 \
  --host 127.0.0.1 --port 8081
```

Teste antes de confiar: rode uma query com um doc relevante e um irrelevante e confira se os `relevance_score` ficam de fato separados (perto de 1 vs. perto de 0). Se vier tudo achatado, a conversão está quebrada — troca de repo.

### Se a qualidade de recuperação do 0.6B for insuficiente

Upgrade natural é **Qwen3-Embedding-4B Q6_K (~3,3 GB)**. Ainda cabe tranquilo ao lado do Qwen3.5-9B (6,5 + 3,3 + 0,6 reranker ≈ 10,4 GB, faixa "utilizável" — controlar contexto). Não comece por aí; só suba se o 0.6B mostrar recall ruim nas suas perguntas reais sobre as notas.

---

## 3. RAG sobre as notas da faculdade

- Workspace dedicado, ex. `~/nanobot-workspace/faculdade/`, com os `.md` da PUC Minas sincronizados ali (symlink ou cópia — decida se quer live-edit ou snapshot).
- Ativar `restrict_to_workspace: true` (seção 5) pra o agente não vazar leitura/escrita pra fora dessa pasta por engano.
- Pipeline sugerido: embedding indexa os `.md` em chunks → pergunta do usuário vira query → embedding recupera top-K → reranker reordena → só os trechos reordenados entram no contexto do Qwen3.5-9B pra resposta final.
- Reindexar sob demanda (comando manual ou hook simples de "mudou o arquivo"), não em polling constante — evita I/O e uso de GPU desnecessário rodando em background o tempo todo.

---

## 4. O que o nanobot toca na rede por padrão — mapeado explicitamente

Isso é o que você pediu pra deixar explícito. Nada aqui é "malicioso", é o comportamento padrão de um framework de agente com tools — mas cada item é uma superfície de saída de dados que precisa de decisão consciente, não default silencioso.

| Superfície | Sai da máquina? | Comportamento padrão | O que fazer |
|---|---|---|---|
| **WebUI** | Não | Bind em `127.0.0.1:8765`, não exposto à LAN no primeiro run | Manter assim; não habilitar LAN a menos que necessário |
| **Web search** | **Sim** | Provider padrão usa DuckDuckGo (sem necessidade de API key) — cada busca sai pra fora | Desativar a tool se não for usar, ou trocar por provider que você confia/paga |
| **Web fetch** | **Sim** | Busca URLs arbitrárias que o LLM decidir buscar; tem guard SSRF embutido | Manter o SSRF guard ligado; não adicionar CIDRs exceção sem motivo forte |
| **MCP servers** | **Depende** | Cada MCP configurado é uma conexão de saída própria (stdio local ou HTTP/SSE remoto) | Só adicionar MCP que você configurou explicitamente; MCP remoto = mais uma parte confiando em terceiro |
| **Canais de chat** (Telegram, Discord, WhatsApp etc.) | **Sim** | Cada canal exige token próprio e abre uma sessão de longa duração com o serviço externo | Não configurar nenhum canal pra esse bot — ele é RAG pessoal, não precisa ficar acessível de fora |
| **Langfuse (observability)** | **Sim, se configurado** | Recurso opcional, exige chave própria pra ativar — não deveria estar ligado sem você ter posto a chave | Confirmar que não há bloco `langfuse` no seu `config.json` |
| **Deploy Render / cloud** | **Sim, se usado** | Só relevante se você seguir o botão de deploy no README | Não usar — esse projeto é local |
| **Atualização de versão** | Manual | `nanobot update` é comando explícito, não há phone-home automático de versão em background conhecido nas versões atuais | Rodar update manualmente quando quiser, não automatizar em cron sem revisar changelog |

Política de dados: o próprio projeto declara postura local-first pra memória/sessões (nada sai da máquina a menos que você empurre explicitamente via tool). Trate isso como "verificado até onde a doc e o código-fonte mostram", não como garantia formal — é um projeto individual, sem auditoria de terceiros publicada, então revise o `config.json` gerado depois do setup pra confirmar que nenhuma tool de rede foi habilitada sem você pedir.

---

## 5. Isolamento recomendado

### 5.1 Sandbox de execução (shell)

No Linux, ativar bubblewrap pra qualquer tool de exec:

```json
{
  "tools": {
    "exec": {
      "sandbox": "bwrap"
    },
    "fs": {
      "restrict_to_workspace": true
    }
  }
}
```

### 5.2 Isolamento de processo — usuário dedicado

Não rodar o nanobot com seu usuário principal (`cleiton`). Criar um usuário Linux sem privilégios pra isso:

```bash
sudo useradd -m -s /usr/sbin/nologin nanobot-svc
sudo -u nanobot-svc -H nanobot webui --background
```

Isso limita o dano de qualquer bug de tool (exec, fs) ao escopo desse usuário, mesmo sem container.

### 5.3 Alternativa mais forte — Docker

O projeto já publica imagem oficial não-root (UID 1000) com bwrap pré-instalado. Note que `docker compose up -d` sozinho **NÃO** ativa `SYS_ADMIN`/bwrap — é necessário usar o arquivo de override para isolamento de filesystem real:

```bash
docker compose -f docker-compose.yml -f docker-compose.bwrap.yml up -d
```

Monte só a pasta do workspace de faculdade como volume, nada além disso.

### 5.4 Firewall de saída (o item que mais importa aqui)

Como o agente decide sozinho quando chamar `web_search`/`web_fetch`/MCP, o controle mais confiável não é confiar na config do nanobot — é bloquear saída na camada de rede e liberar só o necessário. Com `firewalld` (Fedora):

```bash
# zona restrita pro usuário/processo nanobot-svc (ou pro namespace do container)
sudo firewall-cmd --permanent --new-zone=nanobot-out
sudo firewall-cmd --permanent --zone=nanobot-out --set-target=DROP
# libere só o que você decidir usar, ex. Brave Search API:
sudo firewall-cmd --permanent --zone=nanobot-out --add-rich-rule='rule family="ipv4" destination address="<ip-brave-api>" accept'
sudo firewall-cmd --reload
```

Na prática, mais simples: se você **não vai usar web_search nem canais de chat**, desative essas tools na config (seção 6) e não precisa nem chegar no firewall — a superfície já fica fechada na origem. O firewall entra como cinto de segurança se algum dia habilitar alguma tool de rede e quiser garantir que ela só fale com o host esperado.

---

## 6. Config mínima segura — checklist de `~/.nanobot/config.json`

```json
{
  "gateway": {
    "host": "127.0.0.1",
    "port": 18790
  },
  "providers": {
    "local": {
      "apiBase": "http://127.0.0.1:8080/v1",
      "apiKey": "not-needed"
    }
  },
  "tools": {
    "restrictToWorkspace": true,
    "exec": {
      "sandbox": "bwrap"
    },
    "web": {
      "enable": false
    },
    "ssrfWhitelist": [],
    "mcpServers": {}
  },
  "channels": {}
}
```

- `tools.web.enable`: `false` até você decidir que precisa e escolher provider conscientemente.
- `channels: {}`: nenhum canal de chat exposto — sem Telegram/Discord/WhatsApp nesse bot.
- `tools.mcpServers: {}`: nenhum MCP até você adicionar um específico, sabendo o que ele acessa.
- `apiKey` de qualquer provider: sempre via `${VAR_DE_AMBIENTE}` no JSON, nunca em texto puro — o próprio `SECURITY.md` do projeto recomenda isso. `chmod 600` no arquivo de config.

---

## 7. Referências internas do projeto (fonte primária, não terceiro)

A seção 4 deste documento foi montada via docs públicas e busca web. O repo tem fontes primárias mais confiáveis — usar pra validar/corrigir o mapeamento de rede antes de confiar cegamente nele:

| Referência | Onde | Pra que serve |
|---|---|---|
| Limites de segurança do projeto | `.agent/security.md` | Documento oficial do que é considerado fronteira de segurança — deveria ser a fonte de verdade da seção 4, não meu levantamento |
| Restrições de arquitetura | `.agent/design.md` | Decisões de design que explicam *por que* algo é feito assim (relevante se for questionar um default) |
| Módulo de segurança | `nanobot/security/` | Código real: proteção SSRF, controle de acesso a workspace, rate limit e auditoria |
| Registro de tools | `nanobot/agent/tools/registry.py` | Nome exato de cada tool registrada — usar pra confirmar a chave certa se `web_search: false` no config não for suficiente |
| Config schema | `nanobot/config/schema.py`, `nanobot/config/loader.py` | Schema Pydantic real — confirma quais chaves de config existem de fato, incluindo aliases camelCase |
| Gotchas conhecidos | `.agent/gotchas.md` | Comportamentos não-óbvios já mapeados pelos mantenedores — vale ler antes de debugar algo "estranho" sozinho |

Isso é o `AGENTS.md` de contribuição do próprio nanobot (comandos de dev, arquitetura interna, lint/test) — relevante só se você for mexer no código-fonte do projeto, não pra operar o bot. Guardei aqui só os apontadores que importam pro seu uso (RAG + segurança), não o resto (pytest, ruff, build do webui).

---

## 8. Checklist antes de deixar rodando de fato

- [ ] `llama-server` local no ar e testado (`curl 127.0.0.1:8080/v1/models`)
- [ ] Reranker testado com par relevante/irrelevante — scores realmente separados
- [ ] `restrict_to_workspace` ativo, workspace = só a pasta da faculdade (+ o que mais decidir)
- [ ] `channels: {}` — nenhum canal externo habilitado
- [ ] `web_search` desligado, ou ligado com provider e custo/rate limit conscientes
- [ ] Rodando como usuário dedicado ou container, não como seu usuário principal
- [ ] `config.json` com `chmod 600`, sem chave em texto puro
- [ ] WebUI só em `127.0.0.1`, sem porta exposta na LAN/roteador
