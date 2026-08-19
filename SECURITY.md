# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in nanobot, please report it by:

1. **DO NOT** open a public GitHub issue
2. Create a private security advisory on GitHub or contact the repository maintainers (xubinrencs@gmail.com)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We aim to respond to security reports within 48 hours.

## Security Best Practices

### 1. API Key Management

**CRITICAL**: Never commit API keys to version control.

```bash
# ✅ Best: Use environment variable references in config (never writes the key to disk)
# In ~/.nanobot/config.json:
#   "apiKey": "${ANTHROPIC_API_KEY}"
# Then supply the key at runtime via env var or Docker secret.

# ✅ Good: Store in config file with restricted permissions
chmod 600 ~/.nanobot/config.json

# ❌ Bad: Hardcoding keys in code or committing them
```

**Recommendations:**
- **Prefer environment variable references** (`${VAR}`) in config — the config file stores the `${VAR}` placeholder, and the plaintext value only exists in memory at runtime. See [Configuration: Environment Variables for Secrets](https://nanobot.wiki/docs/latest/use-nanobot/configuration/#environment-variables-for-secrets) for details.
- When plaintext keys are stored in `~/.nanobot/config.json`, set file permissions to `0600` (`chmod 600`)
- Consider using an OS keyring/credential manager for production deployments
- Rotate API keys regularly
- Use separate API keys for development and production

### 2. Channel Access Control

**IMPORTANT**: Always configure `allowFrom` lists for production use.

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["123456789", "987654321"]
    },
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["1234567890"]
    }
  }
}
```

**Security Notes:**
- In `v0.1.4.post3` and earlier, an empty `allowFrom` allowed all users. Since `v0.1.4.post4`, empty `allowFrom` denies all access by default — set `["*"]` to explicitly allow everyone.
- Get your Telegram user ID from `@userinfobot`
- Use WhatsApp sender IDs as full phone numbers with country code and no leading `+`
- Review access logs regularly for unauthorized access attempts

### 3. Shell Command Execution

The `exec` tool can execute shell commands. While dangerous command patterns are blocked, you should:

- ✅ **Enable the bwrap sandbox** (`"tools.exec.sandbox": "bwrap"`) for kernel-level isolation (Linux only)
- ✅ Review all tool usage in agent logs
- ✅ Understand what commands the agent is running
- ✅ Use a dedicated user account with limited privileges
- ✅ Never run nanobot as root
- ❌ Don't disable security checks
- ❌ Don't run on systems with sensitive data without careful review

**Exec sandbox (bwrap):**

On Linux, set `"tools.exec.sandbox": "bwrap"` to wrap every shell command in a [bubblewrap](https://github.com/containers/bubblewrap) sandbox. This uses Linux kernel namespaces to restrict what the process can see:

- Workspace directory → **read-write** (agent works normally)
- Media directory → **read-only** (can read uploaded attachments)
- System directories (`/usr`, `/bin`, `/lib`) → **read-only** (commands still work)
- Config files and API keys (`~/.nanobot/config.json`) → **hidden** (masked by tmpfs)

Requires `bwrap` installed (`apt install bubblewrap`). Pre-installed in the official Docker image. **Not available on macOS or Windows** — bubblewrap depends on Linux kernel namespaces.

Enabling the sandbox also automatically activates `restrictToWorkspace` for file tools.

**Blocked patterns:**
- `rm -rf /` - Root filesystem deletion
- Fork bombs
- Filesystem formatting (`mkfs.*`)
- Raw disk writes
- Reads and writes of nanobot's own credential and state files, wherever the
  instance data directory lives: `config.json`, `security.log`, `pairing.json`,
  `auth/` (OAuth token stores), and `whatsapp-auth/`. The workspace, the media
  directory, and `logs/` stay reachable.
- Writes to session state (`history.jsonl`, `.dream_cursor`)
- Other destructive operations

**What it does not catch**: apart from the data-directory check, the filter
matches regexes against the command string, so it is a guard rail against
accidents rather than a security boundary. Flag spellings it does not
enumerate, shell indirection (`eval`, `base64 -d | sh`), piping a downloaded
script into a shell (`curl ... | sh`), and unusual quoting all get past it.
Path-based checks — both this one and `restrictToWorkspace` — only see paths
they can recognise in the command text; a path written as `$HOME/...` is not
matched. Use the bwrap sandbox when you need an actual boundary.

### 4. File System Access

File operations have path traversal protection, but:

- ✅ Enable `restrictToWorkspace` or the bwrap sandbox to confine file access
- ✅ Run nanobot with a dedicated user account
- ✅ Use filesystem permissions to protect sensitive directories
- ✅ Regularly audit file operations in logs
- ❌ Don't give unrestricted access to sensitive files

### 5. Network Security

**API Calls:**
- All external API calls use HTTPS by default
- Timeouts are configured to prevent hanging requests
- The OpenAI-compatible API server must set `api.api_key` when binding to `0.0.0.0` or `::`; otherwise startup fails to prevent unauthenticated network access
- Consider using a firewall to restrict outbound connections if needed

**WhatsApp:**
- Keep the neonize session database under `~/.nanobot/whatsapp-auth` secure (mode 0700).
- Use `nanobot channels login whatsapp --force` to remove and recreate the local session database when rotating linked devices.

### 6. Dependency Security

**Critical**: Keep dependencies updated!

```bash
# Check for vulnerable dependencies
pip install pip-audit
pip-audit

# Update to latest secure versions
pip install --upgrade nanobot-ai
```

**Important Notes:**
- Keep `litellm` updated to the latest version for security fixes
- Run `pip-audit` regularly after enabling the channels used in production; their manifest-declared dependencies are installed into the same environment
- Subscribe to security advisories for nanobot and its dependencies

### 7. Production Deployment

For production use:

1. **Isolate the Environment**
   ```bash
   # Run in a container or VM
   docker run --rm -it python:3.11
   pip install nanobot-ai
   ```

2. **Use a Dedicated User**
   ```bash
   sudo useradd -m -s /bin/bash nanobot
   sudo -u nanobot nanobot gateway
   ```

3. **Verify Permissions**

   nanobot sets these itself — it creates the data directory `0700` and
   `config.json` `0600`, and tightens them if it finds them looser. Verify
   rather than assume, especially after restoring a backup or copying the
   directory between hosts:
   ```bash
   ls -ld ~/.nanobot ~/.nanobot/whatsapp-auth   # expect drwx------
   ls -l  ~/.nanobot/config.json                # expect -rw-------
   ```

4. **Enable Logging**
   ```bash
   # Configure log monitoring
   tail -f ~/.nanobot/logs/nanobot.log
   ```

5. **Use Rate Limiting**
   - Tune the built-in API limiter via `security.rateLimit.requestsPerMinute`
     (default 60; `0` disables it)
   - Put a proper limiter in your reverse proxy for anything public — the
     built-in one is in-process and keyed by remote address
   - Configure rate limits on your API providers
   - Monitor usage for anomalies
   - Set spending limits on LLM APIs

6. **Regular Updates**
   ```bash
   # Check for updates weekly
   pip install --upgrade nanobot-ai
   ```

### 8. Development vs Production

**Development:**
- Use separate API keys
- Test with non-sensitive data
- Enable verbose logging
- Use a test Telegram bot

**Production:**
- Use dedicated API keys with spending limits
- Restrict file system access
- Enable audit logging
- Regular security reviews
- Monitor for unusual activity

### 9. Data Privacy

- **Logs may contain sensitive information** - secure log files appropriately
- **`security.log` records remote addresses** - it is created `0600`; it is not rotated, so prune or rotate it yourself
- **LLM providers see your prompts** - review their privacy policies
- **Chat history is stored locally** - protect the `~/.nanobot` directory, and set `security.sessionMaxAgeDays` if it should not accumulate indefinitely
- **API keys are in plain text** - use OS keyring for production

### 10. Incident Response

If you suspect a security breach:

1. **Immediately revoke compromised API keys**
2. **Review logs for unauthorized access**
   ```bash
   # Structured security events (JSON Lines), newest last
   grep '"result": "denied"' ~/.nanobot/security.log

   # Everything the audit trail recorded from one address
   grep '"remote": "203.0.113.9"' ~/.nanobot/security.log

   # Application log
   grep "Access denied" ~/.nanobot/logs/nanobot.log
   ```
3. **Check for unexpected file modifications**
4. **Rotate all credentials**
5. **Update to latest version**
6. **Report the incident** to maintainers

## Security Features

### Built-in Security Controls

✅ **Input Validation**
- Path traversal protection on file operations
- Dangerous command pattern detection
- Input length limits on HTTP requests

✅ **Authentication**
- Allow-list based access control — in `v0.1.4.post3` and earlier empty `allowFrom` allowed all; since `v0.1.4.post4` it denies all (`["*"]` explicitly allows all)
- Failed authentication attempt logging

✅ **Resource Protection**
- Command execution timeouts (60s default)
- Output truncation (10KB limit)
- HTTP request timeouts (10-30s)
- In-process rate limiting on the API server (`security.rateLimit`)

✅ **Audit Trail**
- Structured JSON Lines security log at `~/.nanobot/security.log` (`security.auditLog`, on by default)
- Records auth failures, rate-limit denials, SSRF blocks, workspace-boundary violations, `exec` denials, and session-retention sweeps
- Event metadata only — never message or command content

✅ **Retention**
- `security.sessionMaxAgeDays` deletes idle conversation sessions at startup (default `0`, disabled)
- Each sweep is recorded in the audit trail as a `session.expired` event

✅ **Permissions At Rest**
- `~/.nanobot` and its runtime subdirectories created `0700`
- `config.json`, `security.log`, `pairing.json`, and OAuth token stores created `0600`
- Existing files and directories found looser are tightened in place

✅ **Secure Communication**
- HTTPS for all external API calls
- TLS for Telegram API
- WhatsApp session secrets stay in the local session database

## Known Limitations

⚠️ **Current Security Limitations:**

1. **Rate Limiting Is In-Process Only** - `security.rateLimit.requestsPerMinute`
   (default 60, `0` disables) guards the OpenAI-compatible API server with a
   fixed-window counter keyed by remote address. Being a fixed window, a client
   can burst up to 2x the limit across a window boundary; being in-process, the
   counter is per-worker and resets on restart; and behind a reverse proxy every
   request shares the proxy's address, which collapses the limit to a global one.
   Put a real limiter in the proxy for anything public.
2. **Plain Text Config** - API keys are stored in plain text in `config.json`.
   nanobot now creates `~/.nanobot` as `0700` and `config.json` as `0600`, and
   tightens both if it finds them looser, so the keys are not readable by other
   local users — but they are still readable by any process running as you.
   Prefer `${VAR}` env references, or an OS keyring for production.

   *Design decision*: Application-level encryption of `config.json` was
   evaluated and consciously discarded. In the single-user self-hosted threat
   model, a symmetric key stored alongside the ciphertext (file or keyring
   readable by the same UID) is obfuscation, not a security boundary. `${VAR}`
   environment variable references already keep plaintext secrets out of the
   file entirely — the config stores only the placeholder and the real value
   lives in process memory at runtime. Protecting secrets on a powered-off disk
   is the responsibility of OS-level full-disk encryption (e.g. LUKS), not the
   application.
3. **Session Retention Is Opt-In** - Conversation history under
   `~/.nanobot/sessions` is kept indefinitely unless you set
   `security.sessionMaxAgeDays`. When set, sessions untouched for that many days
   are deleted in a single sweep at gateway startup — so a long-running gateway
   does not prune until it restarts, and deletion is permanent and unprompted.
   There is still no *authentication* session concept to expire; channel access
   is governed by `allowFrom` and pairing.
4. **Limited Command Filtering** - Apart from a path check that keeps `exec`
   away from nanobot's own credential files, the deny list is a regex filter
   over the command string. It stops obvious destructive patterns, not a
   determined agent or a prompt injection: shell indirection
   (`eval`, `base64 -d | sh`), `curl ... | sh`, and arbitrary reads of files
   elsewhere on the host all get through when `restrictToWorkspace` is off.
   Treat it as a guard rail against accidents. Enable the bwrap sandbox for
   kernel-level isolation on Linux.
5. **Audit Trail Covers Guard Decisions Only** - `~/.nanobot/security.log` records
   auth failures, rate-limit denials, SSRF blocks, workspace-boundary violations,
   `exec` denials, and session-retention sweeps as JSON Lines. It records *blocked* events, not a full
   activity log: allowed tool calls, model requests, and message content are not
   in it. Rotation is not handled — the file grows until you rotate it.

## Security Checklist

Before deploying nanobot:

- [ ] API keys stored securely (not in code)
- [ ] Config file and data directory permissions verified (`0600` / `0700`)
- [ ] `security.rateLimit.requestsPerMinute` reviewed for your exposure
- [ ] `security.auditLog` left enabled, and `security.log` rotation arranged
- [ ] `security.sessionMaxAgeDays` set if chat history should not be kept forever
- [ ] `allowFrom` lists configured for all channels
- [ ] Running as non-root user
- [ ] Exec sandbox enabled (`"tools.exec.sandbox": "bwrap"`) on Linux deployments
- [ ] File system permissions properly restricted
- [ ] Dependencies updated to latest secure versions
- [ ] Logs monitored for security events
- [ ] Rate limits configured on API providers
- [ ] Backup and disaster recovery plan in place
- [ ] Security review of custom skills/tools

## Updates

**Last Updated**: 2026-08-19

For the latest security updates and announcements, check:
- GitHub Security Advisories: https://github.com/HKUDS/nanobot/security/advisories
- Release Notes: https://github.com/HKUDS/nanobot/releases

## License

See LICENSE file for details.
