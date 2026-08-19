"""Tests for the in-process RateLimiter."""

from __future__ import annotations

from nanobot.security.rate_limit import RateLimiter


def test_allows_up_to_limit_per_window() -> None:
    limiter = RateLimiter(limit_per_minute=3, window_s=60.0)
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is False
    assert limiter.remaining("ip") == 0


def test_keys_are_isolated() -> None:
    limiter = RateLimiter(limit_per_minute=2, window_s=60.0)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True


def test_reset_clears_key() -> None:
    limiter = RateLimiter(limit_per_minute=1, window_s=60.0)
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is False
    limiter.reset("ip")
    assert limiter.allow("ip") is True


def test_reset_all_clears_every_key() -> None:
    limiter = RateLimiter(limit_per_minute=1, window_s=60.0)
    limiter.allow("a")
    limiter.allow("b")
    limiter.reset()
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True


def test_zero_limit_disables_enforcement() -> None:
    limiter = RateLimiter(limit_per_minute=0, window_s=60.0)
    for _ in range(10_000):
        assert limiter.allow("ip") is True
    assert limiter.remaining("ip") == -1


def test_window_rollover_allows_again() -> None:
    import time

    limiter = RateLimiter(limit_per_minute=1, window_s=0.2)
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is False
    time.sleep(0.3)
    assert limiter.allow("ip") is True


def test_remaining_does_not_allocate_a_bucket() -> None:
    """Asking about an unseen key must not grow the map (it is caller-supplied)."""
    limiter = RateLimiter(limit_per_minute=5, window_s=60.0)
    assert limiter.remaining("never-seen") == 5
    assert limiter._buckets == {}


def test_stale_keys_are_swept_on_window_rollover() -> None:
    """Keys are attacker-influenced, so elapsed windows must not accumulate."""
    import time

    limiter = RateLimiter(limit_per_minute=60, window_s=0.2)
    for index in range(500):
        limiter.allow(f"203.0.113.{index}")
    assert len(limiter._buckets) == 500

    time.sleep(0.3)
    limiter.allow("198.51.100.1")

    assert list(limiter._buckets) == ["198.51.100.1"]


def test_sweep_does_not_drop_the_current_window() -> None:
    limiter = RateLimiter(limit_per_minute=2, window_s=60.0)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.remaining("b") == 1
