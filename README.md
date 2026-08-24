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

Assistente pessoal local, rodando 100% na própria máquina via `llama.cpp`. Baseado no framework open-source [HKUDS/nanobot](https://github.com/HKUDS/nanobot), adaptado para dois usos concretos:

1. 📚 **RAG sobre notas e documentos de estudo** — indexar arquivos `.md` de um workspace dedicado, recuperar trechos relevantes via embedding + reranker, e responder perguntas com contexto real das notas.
2. 📝 **Utilitário leve de texto do dia a dia** — tarefas pontuais de texto e apoio pessoal, sem virar hub de automação.

> **Privacidade e Isolamento**: Projeto 100% local por design. Sem serviços em nuvem, sem canais de chat externos e com execução isolada sob usuário Linux dedicado. A governança completa do projeto está documentada em [GEMINI.md](./GEMINI.md).

---

## Arquitetura e Isolamento

```
Terminal (CLI)
  └─► /usr/local/bin/nanobot-local (sudo -u nanobot-svc)
        ├─► nanobot (Python venv em /home/nanobot-svc/.venv)
        │     ├─► Execução com sandbox configurável (bwrap via tools.exec.sandbox)
        │     └─► Workspace restrito (restrict_to_workspace: true)
        ├─► llama-server (Qwen3.5-9B Q5_K_M em 127.0.0.1:8080/v1)
        └─► llama-server --rerank (Qwen3-Reranker-0.6B em 127.0.0.1:8081)
```

- **Isolamento de Processo**: Executado sob o usuário de serviço dedicado `nanobot-svc` (UID 960) com suporte a sandbox nativa via `bubblewrap` (`bwrap`), sem Docker e sem daemon persistente (sem systemd/gateway, sem cron de background ou heartbeat). Invocado sob demanda via wrapper `/usr/local/bin/nanobot-local`.
- **Interface 100% CLI**: WebUI não instalada (`NANOBOT_SKIP_WEBUI_BUILD=1`), eliminando portas de interface gráfica e serviços de rede expostos na máquina.
- **Configuração Segura**: Arquivo de configuração em `/home/nanobot-svc/.nanobot/config.json` com permissões `chmod 600`, sem chaves em texto puro.

---

## Modelos e Inferência Local

Inferência servida localmente via `llama-server` (Vulkan/RADV, GPU RX 9060 XT 16GB):

| Papel | Modelo | Quantização | Endpoint Local | Nota |
|---|---|---|---|---|
| **Geração/Resposta** | Qwen3.5-9B | Q5_K_M (~6,5 GB) | `127.0.0.1:8080/v1` | Contexto `-c 16384` |
| **Reranker (RAG)** | Qwen3-Reranker-0.6B | Q8_0 (~0,6 GB) | `127.0.0.1:8081` | Servido com `--rerank` |
| **Embedding (RAG)** | Qwen3-Embedding-0.6B | Q8_0 (~0,6 GB) | Local | Recuperação de trechos |

---

## Superfície de Segurança e Rede

| Componente | Estado no Setup | Mecanismo de Proteção |
|---|---|---|
| **Canais de chat externos** | Desativados (`channels: {}`) | 0 adaptadores externos (Telegram/Discord/WhatsApp fora de escopo) |
| **Web Search & Fetch** | Desativados (`tools.web.enable: false`) | Removidos do registro de ferramentas do agente |
| **Restrição de Workspace** | Ativa (`restrict_to_workspace: true`) | Bloqueio de leitura, escrita e exec fora da pasta permitida |
| **Sandbox de Comandos** | Configurável (`tools.exec.sandbox: "bwrap"`) | Isolamento de kernel/namespaces (em ativação/validação) |
| **WebUI** | Não instalada | Build ignorada via `NANOBOT_SKIP_WEBUI_BUILD=1` |

---

## Definição de Pronto (DoD)

Status: **100% VERIFICADA em 2026-08-24** (com evidências empíricas registradas nas Seções 10 e 12 do [GEMINI.md](./GEMINI.md)):

- [x] `llama-server` local ativo e respondendo (`Qwen3.5-9B Q5_K_M`, `-c 16384`).
- [x] Reranker testado com separação real de scores (`0.99915` vs `0.00001` no `Qwen3-Reranker-0.6B-Q8_0`).
- [x] Restrição de workspace (`restrict_to_workspace`) testada e bloqueando acessos externos.
- [x] `channels: {}` e `tools.web.enable: false` confirmados no processo real sob `nanobot-svc`.
- [x] Invocação sob demanda via wrapper `nanobot-local` validada sob usuário `nanobot-svc`.
- [x] `config.json` com `chmod 600` e sem credenciais em texto puro.
- [x] WebUI não instalada (interface exclusivamente CLI local).

---

## Como Usar

### 1. Iniciar os Servidores Locais de Modelo

```bash
# Servidor de Geração (porta 8080)
llama-server -m /caminho/Qwen3.5-9B-Q5_K_M.gguf \
  --host 127.0.0.1 --port 8080 --ctx-size 16384

# Servidor de Rerank (porta 8081)
llama-server -m /caminho/qwen3-reranker-0.6b-q8_0.gguf \
  --host 127.0.0.1 --port 8081 --rerank
```

### 2. Invocar o nanobot via CLI

```bash
nanobot-local -m "sua pergunta ou instrução"
```

---

## Governança e Regras do Projeto

Este repositório segue regras estritas de governança, auditoria técnica e verificação empírica antes de qualquer alteração de código ou documentação. Para detalhes sobre o modelo de ameaças, regras não-negociáveis e arquitetura completa, consulte o **[GEMINI.md](./GEMINI.md)**.

---

## Créditos

Este projeto é um fork pessoal do [nanobot](https://github.com/HKUDS/nanobot), criado por [Xubin Ren](https://github.com/re-bin) e mantido pela comunidade open-source sob licença MIT.

A documentação original, guias de instalação e arquitetura completa estão disponíveis em [nanobot.wiki](https://nanobot.wiki).
