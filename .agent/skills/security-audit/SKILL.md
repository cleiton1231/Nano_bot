---
name: security-audit
description: "Auditoria empírica de segurança, validação de portas Docker, checagem de binds localhost 127.0.0.1, capabilities Linux, volumes sensíveis e isolamento de rede."
---

# Runbook de Auditoria de Segurança e Rede

Execute estes comandos empíricos e cole o output literal na resposta antes de classificar os itens:

## 1. Exposição de Portas e Redes Docker
```bash
grep -rn "ports:\|0\.0\.0\.0\|network_mode" *compose*.yml *compose*.yaml 2>/dev/null || true
```

## 2. Capabilities e Privilégios Linux
```bash
grep -rn "cap_add\|cap_drop\|SYS_ADMIN\|privileged" *compose*.yml *compose*.yaml 2>/dev/null || true
```

## 3. Montagens de Volumes e Sockets Sensíveis
```bash
grep -rn "docker\.sock\|/proc\|/sys\|/etc" *compose*.yml *compose*.yaml 2>/dev/null || true
```

## 4. Binds de Gateway e WebUI no Código
```bash
grep -rn "bind\|host.*127\.0\.0\.1\|0\.0\.0\.0" nanobot/cli/ nanobot/gateway/ 2>/dev/null || true
```

## 5. Classificação Obrigatória no Relatório
- Se o comando rodou e confirmou conformidade -> **VERIFICADO** (+ output literal).
- Se não rodou / arquivo ausente -> **NÃO VERIFICADO**.
- Se detectou exposição indevida (ex.: `8765:8765` sem prefixo `127.0.0.1:`) -> **DIVERGENTE** (+ trecho exato).
