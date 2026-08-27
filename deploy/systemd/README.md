# systemd units — llama-server (nanobot local stack)

Three user-space inference services for the nanobot RAG + agent stack:

| Unit | Port | Role |
|------|-----:|------|
| `llama-server-embedding.service` | 8082 | Qwen3-Embedding-0.6B-Q8_0 |
| `llama-server-reranker.service` | 8081 | Qwen3-Reranker-0.6B-Q8_0 |
| `llama-server-generation.service` | 8080 | Qwen3.5-9B-Q5_K_M |

All bind to `127.0.0.1` only. Processes run as `nanobot-svc`.

## Install (manual — operator with sudo)

```bash
sudo cp deploy/systemd/llama-server-*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## Start / stop (no boot auto-start in current phase)

```bash
sudo systemctl start llama-server-embedding.service
sudo systemctl start llama-server-reranker.service
sudo systemctl start llama-server-generation.service

sudo systemctl stop llama-server-{embedding,reranker,generation}.service
```

**Do not run `systemctl enable`** unless boot auto-start is explicitly decided later. Units ship with `[Install] WantedBy=multi-user.target` for future use only.

Verify disabled:

```bash
systemctl is-enabled llama-server-{embedding,reranker,generation}.service
# expected: disabled
```

## Operational dependencies

- Binary (systemd): `/usr/local/bin/llama-server`
- Build output (source of manual copy): `/home/cleiton/Projetos/llama.cpp/build/bin/llama-server`
- Models under `/home/cleiton/local/models/...`

Services run as `nanobot-svc` but read model paths under the operator home (traverse + world-readable GGUF). Model moves require `systemctl restart` on all three units.

### SELinux: why `/usr/local/bin`

systemd starts services under the `init_t` domain. SELinux denies executing a binary under `$HOME` with label `user_home_t` from that domain (AVC: `execute` denied, `scontext=system_u:system_r:init_t:s0`, `tcontext=...:user_home_t`). The copy in `/usr/local/bin` carries the native `bin_t` context and is allowed.

Install or refresh the runtime binary after build:

```bash
sudo cp /home/cleiton/Projetos/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
sudo chmod 755 /usr/local/bin/llama-server
```

### After llama.cpp rebuild

`/usr/local/bin/llama-server` is a **manual copy** — it does not track rebuilds automatically. Before any `systemctl restart` on the three units:

1. Rebuild llama.cpp as usual.
2. Run the `sudo cp` above to refresh `/usr/local/bin/llama-server`.
3. Then restart: `sudo systemctl restart llama-server-{embedding,reranker,generation}.service`

Restarting units without copying first leaves the old binary running from disk until the next copy.

## GPU acceptance (post-cutover)

Compare `journalctl -u <unit>` against nohup baseline:

- `WARNING: radv is not a conformant Vulkan implementation, testing use only.`
- `load_model:` timing (generation ~6 s loading→initializing; embedding/reranker ~0.5 s)

If GPU fails under systemd but worked under nohup, add documented `Environment=` lines to the unit file with evidence (e.g. `VK_ICD_FILENAMES`, `LD_LIBRARY_PATH`).

## Restart policy

`Restart=on-failure`, `RestartSec=10`, `StartLimitBurst=5` per 300 s window.
