"""Tests for session retention (`security.sessionMaxAgeDays`).

Chat history is the most sensitive state nanobot keeps on disk. Retention is
opt-in: with the default of 0 nothing is ever deleted.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from nanobot.config.loader import set_config_path
from nanobot.config.schema import Config, SecurityConfig
from nanobot.session.manager import SessionManager


@pytest.fixture
def manager(tmp_path: Path):
    set_config_path(tmp_path / "instance" / "config.json")
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        yield SessionManager(workspace)
    finally:
        set_config_path(None)


def _seed(manager: SessionManager, key: str, *, age_days: float = 0.0) -> Path:
    session = manager.get_or_create(key)
    session.add_message("user", "hello")
    manager.save(session, fsync=True)
    path = manager._get_session_path(key)
    if age_days:
        stamp = time.time() - (age_days * 86400)
        os.utime(path, (stamp, stamp))
    return path


def test_retention_is_off_by_default() -> None:
    assert SecurityConfig().session_max_age_days == 0
    assert Config().security.session_max_age_days == 0


def test_zero_days_prunes_nothing(manager: SessionManager) -> None:
    path = _seed(manager, "telegram:old", age_days=400)

    assert manager.prune_expired(0) == []
    assert path.exists()


def test_negative_days_prunes_nothing(manager: SessionManager) -> None:
    """A misconfigured negative value must not be read as 'delete everything'."""
    path = _seed(manager, "telegram:old", age_days=400)

    assert manager.prune_expired(-1) == []
    assert path.exists()


def test_idle_sessions_past_the_window_are_deleted(manager: SessionManager) -> None:
    stale = _seed(manager, "telegram:old", age_days=40)
    fresh = _seed(manager, "telegram:fresh")

    assert manager.prune_expired(30) == ["telegram:old"]
    assert not stale.exists()
    assert fresh.exists()


def test_sessions_inside_the_window_survive(manager: SessionManager) -> None:
    path = _seed(manager, "telegram:recent", age_days=5)

    assert manager.prune_expired(30) == []
    assert path.exists()


def test_pruned_session_is_dropped_from_the_cache(manager: SessionManager) -> None:
    """A deleted session must not be served from memory afterwards."""
    _seed(manager, "telegram:old", age_days=40)
    assert manager.get_cached("telegram:old") is not None

    manager.prune_expired(30)

    assert manager.get_cached("telegram:old") is None


def test_pruned_key_is_recreated_empty(manager: SessionManager) -> None:
    _seed(manager, "telegram:old", age_days=40)
    manager.prune_expired(30)

    assert manager.get_or_create("telegram:old").messages == []
