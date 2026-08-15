# Modelo: Gemini 3.7 Flash (High)

# Relatório de Análise Técnica e Auditoria Empírica do nanobot

> **Data da Análise**: 2026-08-15  
> **Referência Central**: `AGENT.md` (Seções 0 a 8)  
> **Repositório**: `https://github.com/cleiton1231/Nano_bot` (Baseado em `HKUDS/nanobot`)  
> **Regra Mandatória Aplicada**: `.agent/rules/empirical_verification.md`  

---

## 1. Entendimento da Arquitetura e Escopo Pessoal

### 1.1 Arquitetura do Projeto
O `nanobot` é um framework em Python voltado para agentes autônomos com execução de ferramentas, suporte a MCP (Model Context Protocol), sessões com autocompactação e canais de mensageria.

- **AgentLoop e Runner (`nanobot/agent/loop.py`, `nanobot/agent/runner.py`)**:
  - `AgentLoop`: É o núcleo de processamento assíncrono. Gerencia o ciclo de vida do agente, orquestra a montagem de contexto (`ContextBuilder`), subagentes (`SubagentManager`), despacho de ferramentas (`ToolRegistry`), hooks de turno e consolidação de memória (`Consolidator` / jobs "Dream").
  - `AgentRunner`: Executa o loop iterativo passo a passo por turno (reagir a mensagens, invocar o modelo via streaming ou chamada única, disparar tool calls sucessivas até o limite de `max_tool_iterations`, default `200`).
- **Providers de Inferência (`nanobot/providers/`)**:
  - O nanobot não executa pesos de modelos em seu próprio processo Python; ele consome APIs externas ou locais compatíveis com o formato OpenAI (`OpenAICompatProvider`).
  - Para o escopo local, a inferência é delegada ao `llama-server` exposto em `http://127.0.0.1:8080/v1`.
- **Barramento de Mensagens (`nanobot/bus/queue.py`)**:
  - Implementa um barramento desacoplado com `asyncio.Queue` para tráfego de entrada (`inbound`) e saída (`outbound`), isolando adaptadores de canais (CLI, WebUI, Telegram, WhatsApp, etc.) da lógica de execução do agente.
- **Sistema de Ferramentas (`nanobot/agent/tools/`)**:
  - Registro dinâmico com `ToolRegistry` (`registry.py`), descoberta por `ToolLoader` (`loader.py`), sandboxing com bubblewrap (`sandbox.py`), restrição de escopo de diretório (`restrict_to_workspace`) e proteção contra SSRF (`nanobot/security/network.py`).
- **Sistema de Memória (`nanobot/agent/memory.py`, `nanobot/session/`)**:
  - Persistência local em disco no workspace ativo: `SOUL.md`, `USER.md`, `memory/MEMORY.md` e `memory/history.jsonl`. O `Consolidator` / `DreamConfig` executa compactação e sumarização periódica das sessões.

### 1.2 Escopo Pessoal Definido no `AGENT.md`
- **Finalidade**: RAG local sobre notas de estudo da faculdade (PUC Minas) em Markdown e utilitário leve de texto.
- **Hardware e Inferência**:
  - GPU: AMD Radeon RX 9060 XT Steel Legend OC (16 GB VRAM).
  - Backend: `llama.cpp` compilado com suporte a Vulkan (RADV GFX1200) no Fedora.
  - Servidor: `llama-server` rodando em `127.0.0.1:8080/v1` (OpenAI-compatible endpoint).
  - Arquitetura de Modelos (orçamento de ~7,7 GB VRAM, mantendo folga no desktop):
    1. **Geração**: Qwen3.5-9B (Quant Q5_K_M, ~6,5 GB).
    2. **Embedding**: Qwen3-Embedding-0.6B (Quant Q8_0, ~0,6 GB) ou upgrade para 4B Q6_K.
    3. **Reranker**: Qwen3-Reranker-0.6B (Quant Q8_0, ~0,6 GB) rodando em `127.0.0.1:8081` com flag `--reranking --pooling rank --embedding`. Cautela documentada sobre conversões GGUF quebradas sem o tensor `cls.output.weight`.

---

## 2. Auditoria Empírica de Segurança e Rede

Comandos executados empiricamente conforme o runbook de segurança e regras do repositório:

### 2.1 Inspeção de Portas e Redes Docker
**Comando executado:**
```bash
grep -n "ports:\|0.0.0.0\|network_mode" docker-compose*.yml
```
**Output literal completo:**
```text
docker-compose.yml:27:    ports:
docker-compose.yml:43:      ["serve", "--host", "0.0.0.0", "-w", "/home/nanobot/.nanobot/api-workspace"]
docker-compose.yml:45:    ports:
```

### 2.2 Inspeção de Capabilities e Privilégios Linux
**Comando executado:**
```bash
grep -rn "cap_add\|cap_drop\|SYS_ADMIN\|privileged" docker-compose*.yml
```
**Output literal completo:**
```text
docker-compose.bwrap.yml:2:  cap_add:
docker-compose.bwrap.yml:3:    - SYS_ADMIN
docker-compose.yml:9:  cap_drop:
docker-compose.yml:12:  cap_add:
```

### 2.3 Inspeção de Montagens e Sockets Sensíveis
**Comando executado:**
```bash
grep -rn "docker\.sock\|/proc\|/sys\|/etc" *compose*.yml *compose*.yaml 2>/dev/null || true
```
**Output literal completo:**
```text

```
*(Sem montagens de sockets ou pseudo-filesystems sensíveis diretamente nos compose files)*

### 2.4 Inspeção de Binds de Gateway e WebUI no Código
**Comando executado:**
```bash
grep -rn "bind\|host.*127\.0\.0\.1\|0\.0\.0\.0" nanobot/cli/ nanobot/gateway/ 2>/dev/null || true
```
**Output literal completo:**
```text
nanobot/cli/gateway_runtime.py:22:    _gateway_health_bind_note,
nanobot/cli/gateway_runtime.py:221:    """Print a usable health URL and make non-loopback binds explicit."""
nanobot/cli/gateway_runtime.py:224:        f"{_gateway_health_bind_note(host)}"
nanobot/cli/gateway_runtime.py:803:        """Wait for the gateway to bind, then point the user's browser at the webui."""
nanobot/cli/gateway_runtime.py:822:        target_host = parsed.hostname or config.gateway.host or "127.0.0.1"
nanobot/cli/onboard.py:19:from prompt_toolkit.key_binding import KeyBindings
nanobot/cli/onboard.py:20:from prompt_toolkit.key_binding.key_processor import KeyPressEvent
nanobot/cli/onboard.py:205:    # Key bindings
nanobot/cli/onboard.py:206:    bindings = KeyBindings()
nanobot/cli/onboard.py:209:    @bindings.add(Keys.Up)
nanobot/cli/onboard.py:215:    @bindings.add(Keys.Down)
nanobot/cli/onboard.py:221:    @bindings.add(Keys.Enter)
nanobot/cli/onboard.py:226:    @bindings.add("escape")
nanobot/cli/onboard.py:231:    @bindings.add(Keys.Left)
nanobot/cli/onboard.py:236:    @bindings.add(Keys.ControlC)
nanobot/cli/onboard.py:247:    app = Application[object](layout=layout, key_bindings=bindings, style=style)
nanobot/cli/onboard.py:531:def _input_back_key_bindings() -> KeyBindings:
nanobot/cli/onboard.py:532:    """Return key bindings that make Escape behave like a local back action."""
nanobot/cli/onboard.py:533:    bindings = KeyBindings()
nanobot/cli/onboard.py:536:    @bindings.add("escape")
nanobot/cli/onboard.py:540:    return bindings
nanobot/cli/onboard.py:567:            key_bindings=_input_back_key_bindings(),
nanobot/cli/onboard.py:615:    value = _ask_prompt(prompt_factory(f"{display_name}:", key_bindings=_input_back_key_bindings()))
nanobot/cli/onboard.py:690:            key_bindings=_input_back_key_bindings(),
nanobot/cli/onboard.py:747:        key_bindings=_input_back_key_bindings(),
nanobot/cli/terminal.py:17:from prompt_toolkit.key_binding import KeyBindings
nanobot/cli/terminal.py:18:from prompt_toolkit.key_binding.key_processor import KeyPressEvent
nanobot/cli/terminal.py:132:def _build_cli_key_bindings() -> KeyBindings:
nanobot/cli/terminal.py:133:    """Key bindings for the interactive prompt.
nanobot/cli/terminal.py:191:        # bindings, while Alt+Enter adds a newline.
nanobot/cli/terminal.py:193:        key_bindings=_build_cli_key_bindings(),
nanobot/cli/webui.py:21:    _gateway_health_bind_note,
nanobot/cli/webui.py:34:    _warn_webui_bind_scope,
nanobot/cli/webui.py:156:        _warn_webui_bind_scope(setup_config)
nanobot/cli/webui.py:196:        f"{_gateway_health_bind_note(runtime_config.gateway.host)}"
nanobot/cli/webui_support.py:36:    "_gateway_health_bind_note",
nanobot/cli/webui_support.py:50:    "_warn_webui_bind_scope",
nanobot/cli/webui_support.py:90:    """Resolve the config path used by ``nanobot webui`` and bind loader state."""
nanobot/cli/webui_support.py:207:    """Map bind hosts to a browser-openable local host."""
nanobot/cli/webui_support.py:208:    if host in {"0.0.0.0", ""}:
nanobot/cli/webui_support.py:222:def _gateway_health_bind_note(host: str) -> str:
nanobot/cli/webui_support.py:223:    """Describe a non-local bind without presenting it as a usable URL."""
nanobot/cli/webui_support.py:236:    host = _host_for_local_browser(str(ws_cfg.get("host") or "127.0.0.1"))
nanobot/cli/webui_support.py:287:    if model.host != "127.0.0.1":
nanobot/cli/webui_support.py:288:        model.host = "127.0.0.1"
nanobot/cli/webui_support.py:307:def _warn_webui_bind_scope(config: Config) -> None:
nanobot/cli/webui_support.py:309:    host = str(ws_cfg.get("host") or "127.0.0.1")
nanobot/cli/webui_support.py:310:    if host in {"127.0.0.1", "localhost", "::1"}:
nanobot/cli/webui_support.py:313:        "[yellow]Warning: WebUI is configured to bind outside localhost. "
nanobot/cli/webui_support.py:324:    host = parsed.hostname or "127.0.0.1"
nanobot/cli/webui_support.py:374:    host = parsed.hostname or "127.0.0.1"
```

---

## 3. Checklist de Validação (Estados Exclusivos)

Classificação estrita baseada nas regras de auditoria técnica:

| Item / Superfície | Estado | Evidência Empírica e Citação |
|---|---|---|
| **Porta WebUI no Docker Compose** | **DIVERGENTE** | `docker-compose.yml:29` mapeia `- 8765:8765` sem `127.0.0.1:`. Expõe o WebUI para `0.0.0.0` (toda a LAN), violando o Princípio 4 e a Seção 4 do `AGENT.md`. |
| **Capabilities no `docker-compose.yml`** | **DIVERGENTE** | `docker-compose.yml:9-15` define `cap_drop: [ALL]` e `cap_add: [CHOWN, SETGID, SETUID]`. Não contém `SYS_ADMIN`. A capability `SYS_ADMIN` está apenas no arquivo separado `docker-compose.bwrap.yml:3`. |
| **Provider padrão de Web Search** | **DIVERGENTE** | `AGENT.md` (Seção 4) afirma que o padrão é Brave Search. O código em `nanobot/agent/tools/web.py:64` define `provider: str = "duckduckgo"`. |
| **Estrutura de Chaves no `config.json`** | **DIVERGENTE** | O JSON sugerido na Seção 6 do `AGENT.md` usa campos inexistentes no schema Pydantic (`nanobot/config/schema.py`), tais como `gateway.webui.bind`, `tools.fs.restrict_to_workspace`, `tools.web_search.enabled`, `tools.web_fetch.ssrfExemptCidrs` e `providers.<name>.baseUrl`. |
| **SSRF Protection & Guard no Código** | **VERIFICADO** | `nanobot/security/network.py:18-30` define `_BLOCKED_NETWORKS` bloqueando loopback, RFC1918, CGNAT, link-local e metadata (`169.254.0.0/16`). `configure_ssrf_whitelist` lê de `config.tools.ssrf_whitelist` (`nanobot/config/loader.py:143-147`). |
| **Bubblewrap Sandbox Implementation** | **VERIFICADO** | `nanobot/agent/tools/sandbox.py:48-101` implementa `_bwrap` com isolamento de namespace, mascarando diretório pai (`--tmpfs str(ws.parent)`), montando workspace (`--bind`) e media (`--ro-bind-try`). |
| **Gateway Host Default no Código** | **VERIFICADO** | `nanobot/config/schema.py:366` define `host: str = "127.0.0.1"` e `nanobot/cli/webui_support.py:287-288` força/avisa sobre escopo local. |
| **Rate Limiting e Audit Trail** | **VERIFICADO** | `nanobot/config/schema.py:382-387` e `nanobot/security/audit.py` implementam log de auditoria e limitação de requisições. |

---

## 4. Tabela Detalhada de Discrepâncias (Documento vs. Código Real)

### Discrepância 1: Exposição de Porta do WebUI no `docker-compose.yml`
- **O que o AGENT.md diz**:
  - Seção 0 (Princípio 4): *"Sem WebUI/gateway na LAN. Bind em 127.0.0.1."*
  - Seção 4: *"WebUI: Bind em 127.0.0.1:8765, não exposto à LAN no primeiro run"*
- **O que o código faz de fato**:
  - Em `docker-compose.yml:27-29`:
    ```yaml
    ports:
      - 127.0.0.1:18790:18790
      - 8765:8765
    ```
    A porta 8765 não possui o prefixo `127.0.0.1:`, vinculando-se automaticamente a `0.0.0.0:8765`.
- **Por que importa para o uso real**: Se o usuário subir o container via `docker compose up -d`, a interface WebUI ficará acessível para qualquer dispositivo na rede local (Wi-Fi/LAN), expondo sessões e execução de comandos sem autenticação.

---

### Discrepância 2: Capabilities do Docker para Bubblewrap
- **O que o AGENT.md diz**:
  - Seção 5.3: *"o docker-compose.yml já dropa capabilities exceto SYS_ADMIN (necessário pro namespace isolation do bwrap). Prefira essa rota se quiser isolamento de filesystem real: `docker compose up -d`"*
- **O que o código faz de fato**:
  - Em `docker-compose.yml:9-15`:
    ```yaml
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - SETGID
      - SETUID
    ```
  - A capability `SYS_ADMIN` e as flags `seccomp=unconfined` / `apparmor=unconfined` estão isoladas no arquivo `docker-compose.bwrap.yml:1-6`.
- **Por que importa para o uso real**: Se o usuário rodar apenas `docker compose up -d` com sandbox bwrap habilitado, as chamadas de shell do agente falharão no container por falta de permissão de criação de user namespace (`SYS_ADMIN`). É obrigatório rodar `docker compose -f docker-compose.yml -f docker-compose.bwrap.yml up -d`.

---

### Discrepância 3: Provedor Padrão de Busca Web (`WebSearch`)
- **O que o AGENT.md diz**:
  - Seção 4: *"Web search: Provider padrão usa Brave Search API (ou outro configurado) — cada busca sai pra fora"*
- **O que o código faz de fato**:
  - Em `nanobot/agent/tools/web.py:64`:
    ```python
    class WebSearchConfig(Base):
        """Web search configuration."""
        provider: str = "duckduckgo"
    ```
- **Por que importa para o uso real**: O nanobot usa DuckDuckGo como padrão sem necessidade de chave de API. Caso o usuário queira Brave Search, precisará configurá-lo explicitamente (`provider: "brave"` e `api_key: "..."`).

---

### Discrepância 4: Nomes de Chaves e Estrutura no `config.json`
- **O que o AGENT.md diz** (Seções 1 e 6):
  ```json
  {
    "gateway": { "webui": { "bind": "127.0.0.1", "port": 8765 } },
    "tools": {
      "exec": { "sandbox": "bwrap" },
      "fs": { "restrict_to_workspace": true },
      "web_search": { "enabled": false },
      "web_fetch": { "enabled": true, "ssrfExemptCidrs": [] }
    },
    "channels": {},
    "mcpServers": {},
    "providers": {
      "local": {
        "type": "openai-compatible",
        "baseUrl": "http://127.0.0.1:8080/v1",
        "apiKey": "not-needed"
      }
    }
  }
  ```
- **O que o código faz de fato**:
  - Em `nanobot/config/schema.py:203-240`, o modelo `ProviderConfig` espera `api_base` (ou `apiBase`) e `api_key` (ou `apiKey`). Não existem as chaves `type` nem `baseUrl`.
  - Em `nanobot/config/schema.py:363-370`, `GatewayConfig` possui `host` e `port` (não há sub-bloco `webui`).
  - Em `nanobot/config/schema.py:438-465` e `nanobot/agent/tools/web.py:76-83`:
    - `restrict_to_workspace` fica na raiz de `tools` (`tools.restrict_to_workspace` ou `tools.restrictToWorkspace`), não em `tools.fs`.
    - Busca e Fetch web estão sob `tools.web.enable`, `tools.web.search` e `tools.web.fetch`.
    - Whitelist de SSRF é `tools.ssrf_whitelist`, não `tools.web_fetch.ssrfExemptCidrs`.
    - MCP Servers é `tools.mcp_servers` (ou `tools.mcpServers`), não `mcpServers` na raiz.
- **Por que importa para o uso real**: Se o usuário colar o JSON da Seção 6 diretamente no `~/.nanobot/config.json`, o carregador lançará `ConfigLoadError` / `ValidationError` no startup ou ignorará parâmetros críticos de segurança.

**Formato Real Correto para `~/.nanobot/config.json`:**
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

---

## 5. Teste de Git Commit e Push

### 5.1 Configuração dos Remotes
**Comando executado:** `git remote -v`  
**Output literal:**
```text
nano-bot	git@github.com:cleiton1231/Nano_bot.git (fetch)
nano-bot	git@github.com:cleiton1231/Nano_bot.git (push)
origin	https://github.com/HKUDS/nanobot (fetch)
origin	https://github.com/HKUDS/nanobot (push)
```

### 5.2 Teste do Remote HTTPS (`https://github.com/cleiton1231/Nano_bot`)
**Comando executado:**
```bash
git push --dry-run https://github.com/cleiton1231/Nano_bot
```
**Resultado literal:**
```text
Username for 'https://github.com': 
```
**Análise Técnica:** O comando bloqueia aguardando autenticação interativa (`Username:` e senha/token via `stdin`). Isso ocorre porque o protocolo HTTPS exige credenciais explícitas (Personal Access Token ou helper de credenciais configurado), que não estão presentes no ambiente headless/CLI.

### 5.3 Teste Comparativo via SSH (`nano-bot`)
**Comando executado:**
```bash
git push --dry-run nano-bot
```
**Resultado literal:**
```text
Everything up-to-date
```
**Análise Técnica:** O remote `nano-bot` utiliza chave SSH (`git@github.com:cleiton1231/Nano_bot.git`), que está devidamente provisionada e autentica com sucesso imediato sem exigir interação.

---

## 6. Conclusão e Recomendações Técnicas

1. **Correção de Segurança Imediata no Compose**: Alterar `docker-compose.yml:29` de `8765:8765` para `127.0.0.1:8765:8765`.
2. **Subida de Containers com Bubblewrap**: Para rodar o sandbox bwrap no Docker, utilizar sempre a composição de arquivos:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.bwrap.yml up -d
   ```
3. **Ajuste do Schema no `AGENT.md`**: Atualizar as seções 1 e 6 do `AGENT.md` para refletir os nomes de campos válidos do Pydantic (`apiBase`, `restrictToWorkspace`, `tools.web.enable`, `ssrfWhitelist`).
