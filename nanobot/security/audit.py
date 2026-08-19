"""Structured security audit trail.

Appends one JSON object per line to ``security.log`` in the instance data
directory. Only event metadata is recorded (timestamp, event type, origin,
result, remote address) — never message or command content.

The audit log records who was denied access and from where, so it is treated
as sensitive: the file is owner-only (0600) from the moment it is created.
"""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path
from typing import IO, Any

from loguru import logger

_log_lock = threading.Lock()
_enabled = True

# Owner read/write only. The audit trail lists remote addresses and denied
# access attempts; other local users have no business reading it.
_LOG_FILE_MODE = 0o600

# Paths whose permissions were already checked in this process, so the repair
# below costs one fstat per path instead of one per event.
_hardened_paths: set[Path] = set()


def set_audit_enabled(enabled: bool) -> None:
    """Globally enable or disable security audit logging."""
    global _enabled
    _enabled = bool(enabled)


def audit_log_path() -> Path:
    """Return the security audit log file path (without creating it)."""
    from nanobot.config.paths import get_data_dir

    return get_data_dir() / "security.log"


def _harden_log_file(fd: int, path: Path) -> None:
    """Ensure an already-existing audit log is not readable by other users.

    ``os.open(..., 0o600)`` applies its mode only when it actually creates the
    file. A log written by an older build (before the mode was enforced), or
    restored from a backup, or copied with a permissive umask, can therefore
    still be world-readable. Tighten it in place on first use in this process.

    Permission repair is best effort: on Windows and on filesystems without
    POSIX modes it cannot succeed, and losing the audit record would be worse
    than leaving the mode alone.
    """
    if path in _hardened_paths:
        return
    try:
        if stat.S_IMODE(os.fstat(fd).st_mode) != _LOG_FILE_MODE:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, _LOG_FILE_MODE)
            else:  # pragma: no cover - Windows has no fchmod
                os.chmod(path, _LOG_FILE_MODE)
    except OSError as exc:
        logger.warning("could not restrict permissions on security audit log {}: {}", path, exc)
    _hardened_paths.add(path)


def _open_log_for_append(path: Path) -> IO[bytes]:
    """Open the audit log for append, created 0600 rather than chmod'ed after.

    Creating with ``open("ab")`` and calling ``os.chmod`` afterwards leaves a
    window in which the file exists with the process umask (commonly 0644) and
    any local user can open it. ``os.open`` with an explicit mode closes that
    window: the file never exists with looser permissions.
    """
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, _LOG_FILE_MODE)
    try:
        _harden_log_file(fd, path)
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, "ab")


def audit_security_event(
    event: str,
    *,
    origin: str,
    result: str,
    **metadata: Any,
) -> None:
    """Record one structured security event.

    Args:
        event: Stable event type, e.g. ``auth.failure``, ``rate_limit``.
        origin: Where the event happened (module/channel/endpoint).
        result: Outcome, e.g. ``denied``, ``blocked``, ``allowed``.
        **metadata: Extra non-sensitive fields (remote address, path, ...).
    """
    if not _enabled:
        return
    record: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        "origin": origin,
        "result": result,
    }
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            record[key] = value
        else:
            record[key] = repr(value)

    path = audit_log_path()
    line = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    try:
        with _log_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _open_log_for_append(path) as handle:
                handle.write(line)
                handle.flush()
    except OSError as exc:
        logger.warning("failed to write security audit log {}: {}", path, exc)
