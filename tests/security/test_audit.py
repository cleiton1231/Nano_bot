"""Tests for the structured security audit trail."""

from __future__ import annotations

import json

import pytest

from nanobot.config.loader import set_config_path
from nanobot.security import audit
from nanobot.security.network import resolve_url_target
from nanobot.security.workspace_policy import WorkspaceBoundaryError, require_path_within


@pytest.fixture
def audit_log(tmp_path):
    set_config_path(tmp_path / "config.json")
    log_path = audit.audit_log_path()
    if log_path.exists():
        log_path.unlink()
    yield log_path
    set_config_path(None)


def _read_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_writes_json_line_per_event(audit_log) -> None:
    audit.audit_security_event(
        "auth.failure", origin="api.server", result="denied", remote="10.0.0.1", reason="invalid_key"
    )
    audit.audit_security_event(
        "rate_limit", origin="api.server", result="denied", remote="10.0.0.1", path="/v1/models"
    )
    lines = _read_lines(audit_log)
    assert len(lines) == 2
    assert lines[0]["event"] == "auth.failure"
    assert lines[0]["origin"] == "api.server"
    assert lines[0]["result"] == "denied"
    assert lines[0]["remote"] == "10.0.0.1"
    assert "ts" in lines[0]
    assert lines[1]["event"] == "rate_limit"


def test_ssrf_block_is_audited(audit_log) -> None:
    ok, _err, _ips = resolve_url_target("http://169.254.169.254/latest/meta-data")
    assert ok is False
    lines = _read_lines(audit_log)
    assert any(line["event"] == "ssrf.block" for line in lines)
    blocked = next(line for line in lines if line["event"] == "ssrf.block")
    assert blocked["result"] == "blocked"
    assert "addr" in blocked


def test_workspace_boundary_is_audited(audit_log) -> None:
    with pytest.raises(WorkspaceBoundaryError):
        require_path_within("/etc/passwd", "/tmp/workspace")
    lines = _read_lines(audit_log)
    assert any(line["event"] == "workspace_boundary" for line in lines)
    assert lines[-1]["result"] == "blocked"


def test_exec_denied_is_audited(audit_log) -> None:
    from nanobot.agent.tools.shell import ExecTool

    tool = ExecTool()
    result = tool._prepare_command("rm -rf /tmp/build", "/tmp")
    assert isinstance(result, str)
    lines = _read_lines(audit_log)
    assert any(line["event"] == "exec.denied" for line in lines)
    assert "deny pattern" in lines[-1]["reason"].lower()


def test_disabled_audit_writes_nothing(audit_log) -> None:
    audit.set_audit_enabled(False)
    try:
        audit.audit_security_event("auth.failure", origin="api.server", result="denied")
    finally:
        audit.set_audit_enabled(True)
    assert _read_lines(audit_log) == []


def test_log_file_is_created_with_restricted_permissions(audit_log) -> None:
    audit.audit_security_event("auth.failure", origin="api.server", result="denied")
    import os

    mode = os.stat(audit_log).st_mode & 0o777
    assert mode == 0o600
