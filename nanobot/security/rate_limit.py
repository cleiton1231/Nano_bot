"""Simple in-memory rate limiting.

A fixed-window counter keyed by an arbitrary string (IP, session id, user id).
Stdlib only; no external dependencies. Suitable for self-hosted single-user
instances where an in-process window is enough. Not a replacement for a
reverse-proxy rate limiter under heavy public load.

NOTE: this is a fixed window, not a token bucket — a client can burst up to
2x the configured limit when the request straddles a window boundary. That is
acceptable for single-user self-hosting; review before reusing in a
multi-tenant context or when exposing beyond loopback.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import DefaultDict


class RateLimiter:
    """Fixed-window token limiter per key.

    ``limit_per_minute <= 0`` disables limiting (every ``allow`` returns True).
    """

    __slots__ = ("_limit", "_window_s", "_buckets", "_lock")

    def __init__(self, limit_per_minute: int = 60, window_s: float = 60.0) -> None:
        self._limit = int(limit_per_minute)
        self._window_s = float(window_s)
        self._buckets: DefaultDict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))
        self._lock = threading.Lock()

    @property
    def limit_per_minute(self) -> int:
        return self._limit

    def allow(self, key: str) -> bool:
        """Consume one unit for *key* and return True when the request is allowed."""
        if self._limit <= 0:
            return True
        now = time.monotonic()
        window = now // self._window_s
        with self._lock:
            start, count = self._buckets[key]
            if window != start:
                self._buckets[key] = (window, 1)
                return True
            if count < self._limit:
                self._buckets[key] = (start, count + 1)
                return True
            return False

    def remaining(self, key: str) -> int:
        """Return the number of requests *key* can still make this window."""
        if self._limit <= 0:
            return -1
        now = time.monotonic()
        window = now // self._window_s
        with self._lock:
            start, count = self._buckets[key]
            if window != start:
                return self._limit
            return max(0, self._limit - count)

    def reset(self, key: str | None = None) -> None:
        """Drop the counter for *key*, or all counters when *key* is None."""
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)
