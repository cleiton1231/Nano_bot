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
