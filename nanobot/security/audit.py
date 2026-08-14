"""Structured security audit trail.

Appends one JSON object per line to ``security.log`` in the instance data
directory. Only event metadata is recorded (timestamp, event type, origin,
result, remote address) — never message or command content.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

_log_lock = threading.Lock()
_enabled = True


def set_audit_enabled(enabled: bool) -> None:
    """Globally enable or disable security audit logging."""
    global _enabled
    _enabled = bool(enabled)


def audit_log_path() -> Path:
    """Return the security audit log file path (without creating it)."""
    from nanobot.config.paths import get_data_dir

    return get_data_dir() / "security.log"


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
            created = not path.exists()
            with path.open("ab") as handle:
                handle.write(line)
                handle.flush()
            if created:
                # Match the restricted permissions used for config.json.
                os.chmod(path, 0o600)
    except OSError as exc:
        logger.warning("failed to write security audit log {}: {}", path, exc)
