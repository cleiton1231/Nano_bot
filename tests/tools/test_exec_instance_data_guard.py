"""Tests for the exec guards over nanobot's own credential and state files.

`config.json` holds plaintext API keys, so `cat`-ing it from `exec` would echo
them straight back into a chat channel. These files are blocked regardless of
``restrict_to_workspace``, which is off by default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.tools.shell import ExecTool
from nanobot.config.loader import set_config_path
from nanobot.config.paths import get_data_dir, get_media_dir


@pytest.fixture
def instance(tmp_path: Path):
    """Point the instance data directory at tmp_path and yield its layout."""
    set_config_path(tmp_path / "instance" / "config.json")
    data_dir = get_data_dir()
    workspace = data_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        yield data_dir, workspace
    finally:
        set_config_path(None)


def _blocked(tool: ExecTool, command: str, workspace: Path) -> bool:
    return tool._guard_command(command, str(workspace)) is not None


@pytest.mark.parametrize(
    "template",
    [
        "cat {data}/config.json",
        "cat {data}/security.log",
        "cat {data}/pairing.json",
        "cat {data}/auth/xai.json",
        "cat {data}/auth/mcp.json",
        "cp {data}/whatsapp-auth/neonize.db /tmp/stolen.db",
        "echo malicious > {data}/config.json",
    ],
)
def test_credential_and_state_files_are_blocked(instance, template: str) -> None:
    data_dir, workspace = instance
    tool = ExecTool()
    assert _blocked(tool, template.format(data=data_dir), workspace)


@pytest.mark.parametrize(
    "template",
    [
        "ls {workspace}",
        "cat {workspace}/notes.md",
        "cat {data}/logs/nanobot.log",
    ],
)
def test_workspace_media_and_logs_stay_reachable(instance, template: str) -> None:
    data_dir, workspace = instance
    tool = ExecTool()
    command = template.format(data=data_dir, workspace=workspace)
    assert not _blocked(tool, command, workspace)


def test_media_dir_stays_reachable(instance) -> None:
    _data_dir, workspace = instance
    tool = ExecTool()
    assert not _blocked(tool, f"ls {get_media_dir()}", workspace)


@pytest.mark.parametrize(
    "command",
    ["cat config.json", "cat ./package/config.json", "cat src/auth/token.json"],
)
def test_same_named_project_files_are_not_blocked(instance, command: str) -> None:
    """The guard is anchored to the instance data dir, not to file names."""
    _data_dir, workspace = instance
    tool = ExecTool()
    assert not _blocked(tool, command, workspace)


@pytest.mark.parametrize(
    "command",
    [
        "rm --recursive --force /tmp/build",
        "rm -v --force /tmp/build",
        "rm --recursive /tmp/build",
    ],
)
def test_long_form_rm_flags_are_blocked(instance, command: str) -> None:
    """`rm -rf` was already blocked; the spelled-out flags were not."""
    _data_dir, workspace = instance
    assert _blocked(ExecTool(), command, workspace)


@pytest.mark.parametrize("command", ["rm file.txt", "npm install --force"])
def test_benign_commands_survive_the_rm_pattern(instance, command: str) -> None:
    _data_dir, workspace = instance
    assert not _blocked(ExecTool(), command, workspace)
