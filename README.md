<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./images/readme-cover-dark.svg">
  <img alt="nanobot" src="./images/readme-cover-light.svg">
</picture>

<div align="center">
  <p>
    <a href="./LICENSE"><img src="https://img.shields.io/github/license/HKUDS/nanobot" alt="MIT License"></a>
    <img src="https://img.shields.io/badge/python-%3E%3D3.11-blue" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/GPU-RX%209060%20XT%2016GB-red" alt="RX 9060 XT">
    <img src="https://img.shields.io/badge/inferência-100%25%20local-green" alt="Inferência local">
  </p>
</div>

# nanobot pessoal

Assistente pessoal **local-only**, rodando na própria máquina via `llama.cpp`. Fork do framework open-source [HKUDS/nanobot](https://github.com/HKUDS/nanobot), adaptado para dois usos:

1. **RAG sobre notas de estudo (PUC Minas)** — indexar `.md` de um vault Obsidian, recuperar trechos via embedding + reranker e responder com contexto real das notas.
2. **Utilitário leve de texto** — tarefas pontuais do dia a dia, sem virar hub de automação.

Fora de escopo por design: canais de chat externos (Telegram, Discord, WhatsApp), MCP remoto por padrão, deploy em nuvem e WebUI exposta na LAN. Cada superfície de rede extra é opt-in consciente, não default.

Governança técnica e regras operacionais: **[AGENTS.md](./AGENTS.md)** (fonte de verdade deste repo).

---

## Arquitetura

```
Terminal
  └─► nanobot-local  (wrapper → sudo -u nanobot-svc)
        ├─► systemd: llama-server-generation   → 127.0.0.1:8080  (Qwen3.5-9B)
        ├─► systemd: llama-server-reranker     → 127.0.0.1:8081  (Qwen3-Reranker-0.6B)
        ├─► systemd: llama-server-embedding    → 127.0.0.1:8082  (Qwen3-Embedding-0.6B)
        └─► nanobot CLI (venv em /home/nanobot-svc/.venv)
              ├─► agent + tools (sandbox bwrap quando configurado)
              └─► rag sync / rag search
```

- **Usuário dedicado**: processos sob `nanobot-svc`, nunca como usuário interativo nem root.
- **Sem daemon do nanobot**: invocação sob demanda via CLI; os `llama-server` sobem via `nanobot-local` quando o subcomando precisa deles.
- **Sem Docker**: isolamento nativo com `bubblewrap` (`bwrap`) no host.
- **Interface CLI**: WebUI não instalada neste setup (`NANOBOT_SKIP_WEBUI_BUILD=1`).
- **Config**: `~/.nanobot/config.json` do usuário de serviço, `chmod 600`, sem chave em texto puro.

Detalhes de instalação dos units systemd e do wrapper: [`deploy/systemd/README.md`](./deploy/systemd/README.md).

---

## Modelos e inferência local

Inferência via `llama-server` (Vulkan/RADV, GPU RX 9060 XT 16 GB). Soma residente dos três modelos ~7,7 GB + KV cache — cabe confortável com desktop aberto.

| Papel | Modelo | Quant | Endpoint | Nota |
|-------|--------|-------|----------|------|
| Geração | Qwen3.5-9B | Q5_K_M (~6,5 GB) | `http://127.0.0.1:8080/v1` | Contexto `-c 16384` |
| Reranker (RAG) | Qwen3-Reranker-0.6B | Q8_0 (~0,6 GB) | `http://127.0.0.1:8081` | Flag `--rerank` |
| Embedding (RAG) | Qwen3-Embedding-0.6B | Q8_0 (~0,6 GB) | `http://127.0.0.1:8082/v1` | Recuperação vetorial |

**Reranker — usar só conversões validadas.** A maioria das conversões comunitárias do Qwen3-Reranker está quebrada (falta `cls.output.weight`; scores saem lixo). Repositórios aceitos:

- [`ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`](https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF)
- [`Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp`](https://huggingface.co/Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp)

Embedding oficial usado na homologação: [`Qwen/Qwen3-Embedding-0.6B-GGUF`](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF).

---

## Como rodar

### Pré-requisitos operacionais

1. Units systemd copiados e `daemon-reload` (ver [`deploy/systemd/README.md`](./deploy/systemd/README.md)).
2. Wrapper instalado: `sudo cp deploy/bin/nanobot-local /usr/local/bin/nanobot-local`
3. Config do `nanobot-svc` com `studyRag.notesDir`, URLs de embedding/reranker e paths do banco vetorial.

**Não usar `systemctl enable`** nos units de `llama-server` — boot automático continua decisão separada. Start é on-demand pelo wrapper.

### Lifecycle dos modelos (`nanobot-local`)

O wrapper inicia só os serviços necessários, faz polling de readiness em `GET /v1/models` (timeout 120 s) e delega ao `nanobot` como `nanobot-svc`. **Sem idle-timeout** — modelos ficam em VRAM até stop manual.

| Comando | LLMs iniciados (se down) |
|---------|--------------------------|
| `nanobot-local rag sync` | embedding (8082) |
| `nanobot-local rag search` | reranker (8081) + embedding (8082) |
| `nanobot-local agent -m "..."` | os 3 (8080/8081/8082) |
| `nanobot-local -m "..."` | os 3 (forma legada → `agent`) |
| `nanobot-local llm status` | nenhum (só verifica) |
| `nanobot-local llm stop` | para os 3 |

### Comandos CLI (RAG)

Confirmados em `nanobot/cli/rag.py` e `nanobot --help`:

```bash
# Sincronizar vault → banco vetorial (incremental por checksum SHA-256)
nanobot-local rag sync

# Forçar re-embed de todas as notas
nanobot-local rag sync --force

# Busca semântica (KNN + reranker)
nanobot-local rag search "derivadas parciais"

# Filtro por pasta do vault
nanobot-local rag search "vim comandos" --folder "2026-2/AEDS-I"
```

`rag sync` retorna métricas operacionais (`scanned_files`, `synced_docs`, `failed_docs`, etc.) e exit code não-zero se houver falhas de leitura/embedding. Symlinks que escapam de `notes_dir` são rejeitados em nível de aplicação (skip + warning), sem indexação.

### Agente conversacional

```bash
nanobot-local agent -m "resuma o que sei sobre limites de cálculo"
```

O agente pode usar a tool `search_study_notes` quando o RAG está configurado — pipeline de dois estágios (KNN `candidate_k` + reranker `top_k`).

### Desenvolvimento no checkout

No repo de desenvolvimento, invocar via venv (não `~/.local/bin/nanobot`):

```bash
uv run nanobot --help
uv run nanobot rag sync
```

---

## RAG — estado atual

Pipeline **Fase B** fechado: sync incremental, busca vetorial + reranker fail-fast, tool `search_study_notes` com saída Markdown estruturada.

**Vault de notas**: somente leitura (Syncthing). O nanobot não escreve, edita nem deleta `.md` do vault.

**Confinamento do vault**:

1. **Barreira em aplicação** — `sync_notes()` rejeita paths cujo `resolve()` sai de `notes_dir` (symlinks de arquivo/diretório).
2. **ACL POSIX** no host sobre o path configurado — defesa em profundidade para o processo `nanobot-svc`.

`tools.restrict_to_workspace` protege tools de exec/filesystem do agente, **não** o pipeline RAG.

**Nota Obsidian**: transclusões `![[nome-da-nota]]` sem extensão de mídia são descartadas pelo parser (`_IMAGE_EMBED_RE`) — conteúdo transcluído não entra no índice. Se o vault usa transclusão de notas com frequência, o recall pode ficar incompleto nesses trechos.

---

## Segurança e rede (resumo)

| Superfície | Estado neste setup |
|------------|-------------------|
| Inferência LLM | `127.0.0.1` apenas (8080/8081/8082) |
| WebUI | Não instalada |
| Web search / fetch | Desativados (`tools.web.enable: false`) |
| Canais de chat | Nenhum (`channels: {}`) |
| MCP | Só se configurado explicitamente |
| Sandbox de exec | `bwrap` quando `tools.exec.sandbox: "bwrap"` |
| Vault RAG | Leitura local; ACL + guard de symlink no sync |

Projeto **local-only** — sem exposição de porta na LAN; acesso remoto, se necessário, via túnel SSH.

---

## Créditos

Fork pessoal do [nanobot](https://github.com/HKUDS/nanobot) (MIT). Documentação upstream em [nanobot.wiki](https://nanobot.wiki).
