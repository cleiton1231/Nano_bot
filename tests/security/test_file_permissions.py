"""Permissions of the on-disk state nanobot keeps under the data directory.

SECURITY.md instructs operators to run ``chmod 700 ~/.nanobot``,
``chmod 600 ~/.nanobot/config.json`` and ``chmod 700 ~/.nanobot/whatsapp-auth``
by hand. These tests pin the code enforcing those modes, so a fresh install is
never briefly world-readable and a legacy install is repaired in place.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from nanobot.config.loader import set_config_path
from nanobot.config.paths import get_data_dir, get_runtime_subdir
from nanobot.security import audit

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="Windows does not expose POSIX file modes"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def data_dir(tmp_path: Path):
    """Point the instance data directory at a fresh tmp_path under a lax umask."""
    previous_umask = os.umask(0o022)
    set_config_path(tmp_path / "instance" / "config.json")
    try:
        yield tmp_path / "instance"
    finally:
        set_config_path(None)
        os.umask(previous_umask)


def test_data_dir_is_owner_only(data_dir: Path) -> None:
    assert _mode(get_data_dir()) == 0o700


def test_runtime_subdirs_are_owner_only(data_dir: Path) -> None:
    for name in ("whatsapp-auth", "logs", "media", "cron"):
        assert _mode(get_runtime_subdir(name)) == 0o700, name


def test_loose_data_dir_is_repaired(data_dir: Path) -> None:
    path = get_data_dir()
    os.chmod(path, 0o755)
    assert _mode(path) == 0o755

    assert _mode(get_data_dir()) == 0o700


def test_audit_log_is_owner_only(data_dir: Path) -> None:
    audit.audit_security_event("auth.failure", origin="api.server", result="denied")
    assert _mode(audit.audit_log_path()) == 0o600


def test_pairing_store_is_owner_only(data_dir: Path) -> None:
    """The channel allow-list decides who may talk to the agent."""
    from nanobot.pairing import store

    code = store.generate_code("telegram", "123456789")
    assert store.approve_code(code) == ("telegram", "123456789")

    path = get_data_dir() / "pairing.json"
    assert path.exists()
    assert _mode(path) == 0o600
