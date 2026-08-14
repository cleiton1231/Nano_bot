"""Tests for local search call telemetry (latency/ok recording)."""

from __future__ import annotations

import json

import pytest

from nanobot.utils import searchusage
from nanobot.utils.searchusage import (
    record_local_search_call,
    search_usage_payload,
    set_search_usage_enabled,
)


@pytest.fixture
def state_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "nanobot.utils.searchusage.search_usage_state_path",
        lambda: tmp_path / "search-usage.json",
    )
    yield


def test_record_local_search_call_aggregates_by_provider(state_dir) -> None:
    record_local_search_call("brave", latency_ms=120, ok=True)
    record_local_search_call("brave", latency_ms=180, ok=True)
    record_local_search_call("brave", latency_ms=90, ok=False)

    payload = search_usage_payload()
    assert payload["providers"]["brave"]["calls"] == 3
    assert payload["providers"]["brave"]["errors"] == 1
    assert payload["providers"]["brave"]["avg_latency_ms"] == 130
    assert payload["calls_30d"] == 3
    assert payload["errors_30d"] == 1


def test_disabled_search_telemetry_writes_nothing(state_dir) -> None:
    set_search_usage_enabled(False)
    try:
        record_local_search_call("brave", latency_ms=10, ok=True)
        assert search_usage_payload()["calls_30d"] == 0
    finally:
        set_search_usage_enabled(True)


def test_payload_state_is_persisted(state_dir) -> None:
    record_local_search_call("tavily", latency_ms=50, ok=True)
    raw = json.loads(searchusage.search_usage_state_path().read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert any("tavily" in row for row in raw["days"].values())
