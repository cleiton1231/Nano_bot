# Security Boundaries

The agent operates with significant power (file system, shell, web). The following guards must not be bypassed when modifying related code.

## Workspace Restriction

Filesystem tools (`read_file`, `write_file`, `edit_file`, `list_dir`, `apply_patch`) resolve paths through the workspace path resolver (`agent/tools/filesystem.py` / `agent/tools/path_utils.py`), which enforces that the resolved path must lie under the active workspace when workspace restriction is enabled. The media upload directory is always an internal extra read root while restricted.

Additional filesystem roots must be capability-specific. `extra_allowed_dirs` is a legacy read-only alias. Use `extra_read_allowed_dirs` for read-only roots, `extra_write_allowed_dirs` only when a write-capable tool is intentionally allowed to modify an extra directory, and exact file allowlists when a tool may modify only specific files.

Shell execution (`ExecTool`, `agent/tools/shell.py`) also respects `restrict_to_workspace` as an application-level guard: if enabled and `working_dir` is outside the workspace, the command is rejected before execution, and command text is checked for obvious workspace escapes. This is not process-level isolation; use an exec sandbox backend for that.

**Rule**: Any new path-handling logic must go through the workspace path resolver or perform an equivalent containment check with explicit read/write capability semantics.

## Instance Data Protection

`ExecTool._guard_instance_data_paths` (`agent/tools/shell.py`) blocks shell
commands that resolve to nanobot's own credential and state files under the
instance data directory: `config.json`, `security.log`, `pairing.json`,
`auth/`, and `whatsapp-auth/`. It runs on every command regardless of
`restrict_to_workspace`, because that setting is off by default and reading
`config.json` would echo plaintext API keys into a chat channel. The workspace,
the media directory, and `logs/` deliberately stay reachable — the default
workspace lives under the data directory.

Files at rest follow the same boundary: `utils/helpers.ensure_private_dir`
creates data directories `0700`, and `_write_text_atomic(..., mode=0o600)` pins
the mode on the temporary file so a secrets file is never observable at its
real name with the process umask.

**Rule**: A new file holding credentials or access-control state belongs in
`_PROTECTED_DATA_ENTRIES` and must be written with an explicit `mode`, not
chmod'ed after the fact.

**Known gap**: `_extract_absolute_paths` does not recognise a token beginning
with a shell variable, so `$HOME/.nanobot/config.json` reaches neither this
guard nor the workspace containment check. Any new path-based guard inherits
that blind spot.

## SSRF Protection

All outbound HTTP requests from agent tools must pass through the shared URL guards in `security/network.py` (`validate_url_target` or `resolve_url_target`). By default they block loopback, RFC1918 private addresses, CGNAT ranges, link-local ranges, and cloud metadata endpoints (including `169.254.169.254`).

For direct requests, the only escape hatch is `configure_ssrf_whitelist(cidrs)`, which reads from `config.tools.ssrf_whitelist` at load time. An explicitly configured `providers.<name>.proxy` is a separate user-authorized trust boundary for provider requests and provider-returned image URL downloads. Those downloads still reject malformed URLs and locally identifiable private/internal targets on every redirect, but hostnames unavailable to local DNS are delegated to the trusted proxy. The user-selected proxy owns final DNS resolution and network egress policy.

HTTP/SSE MCP transports are part of this boundary: validate configured MCP URLs before probing or constructing clients, and validate each outgoing HTTP request before redirects are followed. Local/private HTTP MCP endpoints are allowed only through the explicit SSRF whitelist. Stdio MCP servers are not part of the HTTP SSRF path.

**Rule**: Do not add direct `httpx.get` / `requests.get` calls in tools. Route through the existing web fetch utilities or replicate the `validate_url_target` check.

## Shell Sandbox

`tools/sandbox.py` provides optional command wrapping. The only backend currently shipped is `bwrap` (bubblewrap), intended for containerized deployments. On Windows and bare-metal Linux without `bwrap`, commands run in the native shell with workspace restriction as an application-level guard only.

**Rule**: If adding a new sandbox backend, implement `_wrap_<name>(command, workspace, cwd) -> str` and register it in `_BACKENDS`.
