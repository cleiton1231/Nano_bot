"""Simple in-memory rate limiting.

A fixed-window counter keyed by an arbitrary string (IP, session id, user id).
Stdlib only; no external dependencies. Suitable for self-hosted single-user
instances where an in-process window is enough. Not a replacement for a
reverse-proxy rate limiter under heavy public load.

Why a fixed window and not a token bucket
----------------------------------------
A token bucket smooths bursts more precisely, but that precision is not what
this limiter is for. The threat model here is a self-hosted, usually
loopback-bound instance with one operator: the job is to stop a runaway agent
loop, a stuck client, or a leaked local endpoint from hammering the API, not
to allocate throughput fairly between competing tenants. Against that goal the
fixed window wins on the things that matter to a small core:

* State is two numbers per key (window index, count) that become stale simply
  by the clock moving on. A token bucket has to carry a fractional token
  balance plus a last-refill timestamp and recompute the refill on every call.
* Nothing has to run in the background. Counters roll over by comparing window
  indices on the next request; there is no refill timer and no reaper task to
  own, schedule, or shut down cleanly.
* The whole policy fits in one readable ``allow()`` that is obvious under
  review — which matters more for a security control than burst smoothing.

The cost is accepted and bounded: a client can send up to 2x the configured
limit when its requests straddle a window boundary. For a single-user instance
that is noise. If nanobot is ever put behind a public endpoint or shared
between tenants, the answer is a real limiter in the reverse proxy, not a
richer algorithm here.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Fixed-window token limiter per key.

    ``limit_per_minute <= 0`` disables limiting (every ``allow`` returns True).
    """

    __slots__ = ("_limit", "_window_s", "_buckets", "_lock", "_swept_window")

    def __init__(self, limit_per_minute: int = 60, window_s: float = 60.0) -> None:
        self._limit = int(limit_per_minute)
        self._window_s = float(window_s)
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()
        self._swept_window: float | None = None

    def _sweep_locked(self, window: float) -> None:
        """Drop counters left over from windows that have already elapsed.

        Keys come from the caller and are usually attacker-influenced — the
        remote address of an API request. Without this the map would keep one
        entry for every key ever seen, for the life of the process. A bucket
        from an earlier window carries no information, since ``allow`` resets
        any bucket whose window index differs; sweeping once per boundary keeps
        the map sized by *active* clients instead of total clients seen, at
        O(n) once per window rather than on every request.
        """
        if window == self._swept_window:
            return
        self._swept_window = window
        stale = [key for key, (start, _count) in self._buckets.items() if start != window]
        for key in stale:
            del self._buckets[key]

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
            self._sweep_locked(window)
            start, count = self._buckets.get(key, (window, 0))
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
            # ``.get`` rather than a defaultdict lookup: asking how much quota a
            # key has left must not allocate a bucket for it.
            start, count = self._buckets.get(key, (window, 0))
            if window != start:
                return self._limit
            return max(0, self._limit - count)

    def reset(self, key: str | None = None) -> None:
        """Drop the counter for *key*, or all counters when *key* is None."""
        with self._lock:
            if key is None:
                self._buckets.clear()
                self._swept_window = None
            else:
                self._buckets.pop(key, None)
