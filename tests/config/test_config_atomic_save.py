"""Tests for atomic config.json writes."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def test_save_config_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_config(Config(), path)
    loaded = load_config(path)
    assert loaded.agents.defaults.model


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX file modes")
def test_save_config_preserves_existing_file_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)

    save_config(Config(), path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_config_preserves_existing_file_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    save_config(Config(), path)
    before = path.read_text(encoding="utf-8")

    def boom(self: Path, target: Path) -> Path:  # noqa: ARG001
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="simulated crash"):
        save_config(Config(), path)

    assert path.read_text(encoding="utf-8") == before
    assert json.loads(before)  # still valid JSON


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX file modes")
def test_save_config_creates_owner_only_file(tmp_path: Path) -> None:
    """A fresh config.json is 0600 even under a permissive umask."""
    path = tmp_path / "fresh" / "config.json"
    previous_umask = os.umask(0o022)
    try:
        save_config(Config(), path)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX file modes")
def test_save_config_tightens_world_readable_file(tmp_path: Path) -> None:
    """A config.json left readable by an installer or entrypoint is repaired."""
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)

    save_config(Config(), path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX file modes")
def test_save_config_creates_owner_only_data_dir(tmp_path: Path) -> None:
    """The directory holding config.json is created 0700, not umask-default."""
    path = tmp_path / "fresh" / "config.json"
    previous_umask = os.umask(0o022)
    try:
        save_config(Config(), path)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
