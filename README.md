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

# nanobot

Meu assistente pessoal de IA, rodando 100% local na minha máquina. Baseado no framework open-source [HKUDS/nanobot](https://github.com/HKUDS/nanobot), adaptado para três cenários:

- 📚 **Faculdade** — RAG sobre as notas e materiais da PUC Minas. Pergunto sobre conteúdo das aulas e ele responde com base nos meus próprios arquivos.
- 💼 **Profissional** — Assistente para tarefas do dia a dia: resumir textos, revisar código, organizar ideias, gerar rascunhos.
- 🔬 **Acadêmico** — Experimentar com agentes de IA, ferramentas (tools), memória de longo prazo e automações locais.

> **Nada sai da máquina sem autorização explícita.** O LLM roda em GPU local, os dados ficam no disco local, e a WebUI só aceita conexões de `localhost`.

---

## Como funciona

```
Eu (browser ou terminal)
  └─► nanobot (agente Python, WebUI local)
        ├─► llama-server (Qwen3.5-9B na GPU local)
        ├─► Embedding + Reranker (RAG sobre minhas notas)
        └─► Tools: arquivos, shell, memória, MCP
```

O nanobot não roda o modelo de IA — ele conversa com o `llama-server` que roda na minha GPU (RX 9060 XT 16GB) via API local. Isso significa:

- **Zero custo de API** — não pago por token, não dependo de serviço externo.
- **Privacidade real** — os dados nunca saem da máquina.
- **Controle total** — posso trocar o modelo, ajustar contexto, experimentar livremente.

---

## O que ele faz hoje

| Funcionalidade | Status |
|---|---|
| Chat via WebUI local (navegador) | ✅ Funcionando |
| Chat via terminal (`nanobot agent`) | ✅ Funcionando |
| Inferência local com Qwen3.5-9B | ✅ Funcionando |
| RAG sobre notas da faculdade | 🔧 Em setup |
| Memória de longo prazo (Dream) | 🔧 Em setup |
| Automações e tarefas agendadas | 📋 Planejado |
| Tools (arquivos, shell, busca web) | ✅ Disponível |

---

## Stack técnica

| Componente | Detalhe |
|---|---|
| **Framework** | [nanobot](https://github.com/HKUDS/nanobot) (Python, MIT) |
| **GPU** | ASRock Radeon RX 9060 XT Steel Legend OC 16 GB |
| **Backend de inferência** | `llama-server` (llama.cpp + Vulkan/RADV) |
| **Modelo principal** | Qwen3.5-9B (Q5_K_M, ~6.5 GB) |
| **Embedding (RAG)** | Qwen3-Embedding-0.6B (Q8_0, ~0.6 GB) |
| **Reranker (RAG)** | Qwen3-Reranker-0.6B (Q8_0, ~0.6 GB) |
| **SO** | Fedora Linux |

---

## Estrutura do repositório

```
nanobot/
├── nanobot/          # Código-fonte do framework (Python)
├── webui/            # Interface web (frontend)
├── docs/             # Documentação original do projeto
├── .agent/           # Regras e restrições para agentes de IA
│   └── rules/        # Regras mandatórias (ex.: verificação empírica)
├── .agents/          # Skills customizadas
│   └── skills/       # Playbooks operacionais (ex.: security-audit)
├── AGENT.md          # Spec do meu setup: modelos, segurança, RAG, rede
└── README.md         # Este arquivo
```

---

## Segurança e privacidade

Esse bot é pessoal e roda local. As medidas de isolamento são proporcionais:

- **WebUI** vinculada a `127.0.0.1` — não aceita conexão de outros dispositivos.
- **Sandbox** com bubblewrap (`bwrap`) para execução de comandos.
- **Workspace restrito** — o agente só lê/escreve na pasta permitida.
- **Sem canais de chat** — nenhum Telegram, Discord ou WhatsApp configurado.
- **Busca web desligada** por padrão — só liga quando eu decidir.
- **Firewall de saída** configurável para controle extra.

Os detalhes completos estão no [AGENT.md](./AGENT.md).

---

## Como rodar

```bash
# 1. Subir o modelo local
llama-server -m Qwen3.5-9B-Q5_K_M.gguf \
  --host 127.0.0.1 --port 8080

# 2. Iniciar o nanobot
nanobot webui
```

A WebUI abre em [http://127.0.0.1:8765](http://127.0.0.1:8765). Na primeira vez, configurar o provider local em **Settings → Models**.

---

## Créditos

Este projeto é um fork pessoal do [nanobot](https://github.com/HKUDS/nanobot), criado por [Xubin Ren](https://github.com/re-bin) e mantido pela comunidade open-source. Licença MIT.

A documentação original, guias de instalação e arquitetura completa estão disponíveis em [nanobot.wiki](https://nanobot.wiki).
