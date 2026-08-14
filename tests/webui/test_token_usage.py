from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.webui.token_usage import (
    TokenUsageHook,
    record_response_token_usage,
    record_token_usage,
    token_usage_payload,
)


def _write_state(tmp_path, days: dict) -> None:
    state_dir = tmp_path / "webui"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "token-usage.json").write_text(
        json.dumps({"days": days}), encoding="utf-8"
    )


def test_payload_tolerates_malformed_persisted_day_keys(tmp_path, monkeypatch) -> None:
    """Day keys that are not real dates must not break settings payloads.

    normalize_token_usage_state only length-checks day keys, so a hand-edited
    10-char key survives reads and atomic rewrites; token_usage_payload then
    parsed it with an unguarded fromisoformat, failing every /api/settings and
    /api/settings/usage request until the file was fixed by hand.
    """
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    _write_state(tmp_path, {
        "not-a-dat3": {"total_tokens": 7, "requests": 1},
        "2026-13-01": {"total_tokens": 9, "requests": 1},
        "2026-06-02": {"total_tokens": 5, "requests": 1},
    })

    payload = token_usage_payload(
        timezone_name="UTC",
        now=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert payload["total_tokens"] == 5
    assert payload["total_tokens_30d"] == 5
    assert payload["requests_30d"] == 1
    assert payload["active_days_30d"] == 1


def test_record_scrubs_malformed_day_keys(tmp_path, monkeypatch) -> None:
    """Rewrites drop malformed day keys instead of persisting them forever."""
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    _write_state(tmp_path, {
        "not-a-dat3": {"total_tokens": 7, "requests": 1},
        "2026-06-02": {"total_tokens": 5, "requests": 1},
    })

    record_token_usage(
        {"prompt_tokens": 1, "completion_tokens": 1},
        timezone_name="UTC",
        now=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
    )

    raw = json.loads((tmp_path / "webui" / "token-usage.json").read_text(encoding="utf-8"))
    assert "not-a-dat3" not in raw["days"]
    assert "2026-06-02" in raw["days"]
    assert "2026-06-03" in raw["days"]


def test_record_token_usage_aggregates_by_local_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 40, "cached_tokens": 20},
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc),
    )
    record_token_usage(
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 2, 19, 0, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert payload["total_tokens_30d"] == 155
    assert payload["active_days_30d"] == 1
    assert payload["requests_30d"] == 2
    assert payload["days"] == [
        {
            "date": "2026-06-03",
            "prompt_tokens": 110,
            "completion_tokens": 45,
            "cached_tokens": 20,
            "total_tokens": 155,
            "provider_tokens": 155,
            "estimated_tokens": 0,
            "requests": 2,
            "provider_requests": 2,
            "estimated_requests": 0,
            "cost_usd": 0.0,
            "latency_ms": 0,
            "ok_requests": 0,
            "error_requests": 0,
            "sources": {
                "user": {
                    "prompt_tokens": 110,
                    "completion_tokens": 45,
                    "cached_tokens": 20,
                    "total_tokens": 155,
                    "provider_tokens": 155,
                    "estimated_tokens": 0,
                    "requests": 2,
                    "provider_requests": 2,
                    "estimated_requests": 0,
                    "cost_usd": 0.0,
                    "latency_ms": 0,
                    "ok_requests": 0,
                    "error_requests": 0,
                }
            },
        }
    ]


def test_record_token_usage_skips_empty_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert payload["days"] == []
    assert payload["total_tokens_30d"] == 0


def test_record_token_usage_keeps_estimated_split(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 25, "estimated_tokens": 125},
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert payload["days"][0]["total_tokens"] == 125
    assert payload["days"][0]["provider_tokens"] == 0
    assert payload["days"][0]["estimated_tokens"] == 125
    assert payload["days"][0]["estimated_requests"] == 1


def test_record_token_usage_keeps_source_breakdown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 25},
        source="user",
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    record_token_usage(
        {"prompt_tokens": 20, "completion_tokens": 5},
        source="dream",
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    row = payload["days"][0]

    assert row["total_tokens"] == 150
    assert row["sources"]["user"]["total_tokens"] == 125
    assert row["sources"]["user"]["requests"] == 1
    assert row["sources"]["dream"]["total_tokens"] == 25
    assert row["sources"]["dream"]["requests"] == 1


def test_record_response_token_usage_uses_response_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._local_day", lambda *_, **__: "2026-06-03")

    record_response_token_usage(
        SimpleNamespace(usage={"prompt_tokens": 20, "completion_tokens": 5}),
        source="dream",
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert payload["days"][0]["sources"]["dream"]["total_tokens"] == 25


@pytest.mark.asyncio
async def test_token_usage_hook_classifies_source_from_session_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._local_day", lambda *_, **__: "2026-06-03")

    hook = TokenUsageHook()
    await hook.after_iteration(
        AgentHookContext(
            iteration=0,
            messages=[],
            session_key="cron:drink-water",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert payload["days"][0]["sources"]["cron"]["total_tokens"] == 15


def test_record_token_usage_accumulates_cost_latency_and_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 50},
        source="user",
        latency_ms=150,
        cost_usd=0.0002,
        ok=True,
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    record_token_usage(
        {"prompt_tokens": 10, "completion_tokens": 5},
        source="user",
        latency_ms=300,
        ok=False,
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    row = payload["days"][0]
    assert row["latency_ms"] == 450
    assert row["ok_requests"] == 1
    assert row["error_requests"] == 1
    assert row["cost_usd"] == pytest.approx(0.0002)
    assert payload["cost_usd_30d"] == pytest.approx(0.0002)
    assert payload["error_requests_30d"] == 1
    assert payload["avg_latency_ms_30d"] == 225
    src = row["sources"]["user"]
    assert src["latency_ms"] == 450
    assert src["error_requests"] == 1


def test_estimate_cost_usd_matches_provider_model_then_provider_then_star(tmp_path, monkeypatch) -> None:
    from nanobot.webui.token_usage import estimate_cost_usd

    rates = {
        "openrouter/deepseek/deepseek-chat": {"input": 0.5, "output": 1.0},
        "openrouter": {"input": 0.1, "output": 0.2},
        "*": {"input": 1.0, "output": 2.0},
    }
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}
    assert estimate_cost_usd("openrouter", "deepseek/deepseek-chat", usage, rates) == pytest.approx(1.0)
    assert estimate_cost_usd("openrouter", "some-other-model", usage, rates) == pytest.approx(0.2)
    assert estimate_cost_usd("unknown", "x", usage, rates) == pytest.approx(2.0)
    assert estimate_cost_usd("unknown", "x", usage, None) == 0.0
    assert estimate_cost_usd("unknown", "x", usage, {}) == 0.0


@pytest.mark.asyncio
async def test_token_usage_hook_records_cost_and_latency(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._local_day", lambda *_, **__: "2026-06-03")

    hook = TokenUsageHook(
        cost_rates={
            "openrouter/deepseek/deepseek-chat": {"input": 1.0, "output": 2.0},
        }
    )
    await hook.after_iteration(
        AgentHookContext(
            iteration=0,
            messages=[],
            session_key="api:default",
            provider="openrouter",
            model="deepseek/deepseek-chat",
            latency_ms=250,
            usage={"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
            stop_reason="end_turn",
            error=None,
        )
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    row = payload["days"][0]
    assert row["cost_usd"] == pytest.approx(2.0)
    assert row["latency_ms"] == 250
    assert row["ok_requests"] == 1
