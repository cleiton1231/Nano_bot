"""Workspace-scoped token usage telemetry for WebUI overview surfaces."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.config.paths import get_webui_dir

TOKEN_USAGE_SCHEMA_VERSION = 1
_MAX_STATE_FILE_BYTES = 512 * 1024
_MAX_DAYS_RETAINED = 400
_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "total_tokens",
    "provider_tokens",
    "estimated_tokens",
)
_REQUEST_KEYS = ("requests", "provider_requests", "estimated_requests")
_SOURCE_KEYS = ("user", "api", "cron", "dream", "system")
_COST_KEYS = ("cost_usd",)
_LATENCY_KEYS = ("latency_ms",)
_COUNT_KEYS = ("ok_requests", "error_requests")
_WRITE_LOCK = threading.Lock()


def token_usage_state_path() -> Path:
    return get_webui_dir() / "token-usage.json"


def default_token_usage_state() -> dict[str, Any]:
    return {
        "schema_version": TOKEN_USAGE_SCHEMA_VERSION,
        "days": {},
        "updated_at": None,
    }


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _zone(timezone_name: str | None) -> timezone | ZoneInfo:
    if not timezone_name:
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _local_day(now: datetime | None = None, *, timezone_name: str | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_zone(timezone_name)).date().isoformat()


def _clean_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _clean_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _clean_source(value: str | None) -> str:
    return value if value in _SOURCE_KEYS else "system"


def _source_from_session_key(session_key: str | None) -> str:
    key = session_key or ""
    if key.startswith("dream:"):
        return "dream"
    if key == "heartbeat" or key.startswith("cron:"):
        return "cron"
    if key.startswith("api:"):
        return "api"
    if key.startswith("system:"):
        return "system"
    return "user"


def _normalize_usage(raw: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    usage = {key: _clean_int(raw.get(key)) for key in _USAGE_KEYS}
    fallback_total = usage["prompt_tokens"] + usage["completion_tokens"]
    if usage["total_tokens"] <= 0:
        usage["total_tokens"] = fallback_total
    if usage["estimated_tokens"] <= 0 and usage["provider_tokens"] <= 0:
        usage["provider_tokens"] = usage["total_tokens"]
    elif usage["estimated_tokens"] > 0 and usage["provider_tokens"] <= 0:
        usage["estimated_tokens"] = min(usage["estimated_tokens"], usage["total_tokens"])
    elif usage["provider_tokens"] > 0 and usage["estimated_tokens"] <= 0:
        usage["provider_tokens"] = min(usage["provider_tokens"], usage["total_tokens"])
    return usage if usage["total_tokens"] > 0 else {}


def _normalize_usage_row(row: dict[str, Any]) -> dict[str, int | float]:
    cleaned = {key: _clean_int(row.get(key)) for key in _USAGE_KEYS}
    if cleaned["total_tokens"] <= 0:
        cleaned["total_tokens"] = cleaned["prompt_tokens"] + cleaned["completion_tokens"]
    if cleaned["provider_tokens"] <= 0 and cleaned["estimated_tokens"] <= 0:
        cleaned["provider_tokens"] = cleaned["total_tokens"]
    requests = {key: _clean_int(row.get(key)) for key in _REQUEST_KEYS}
    if (
        requests["requests"] > 0
        and requests["provider_requests"] <= 0
        and requests["estimated_requests"] <= 0
    ):
        if cleaned["estimated_tokens"] > 0 and cleaned["provider_tokens"] <= 0:
            requests["estimated_requests"] = requests["requests"]
        else:
            requests["provider_requests"] = requests["requests"]
    telemetry: dict[str, int | float] = {
        "cost_usd": _clean_float(row.get("cost_usd")),
        "latency_ms": _clean_int(row.get("latency_ms")),
        "ok_requests": _clean_int(row.get("ok_requests")),
        "error_requests": _clean_int(row.get("error_requests")),
    }
    return {**cleaned, **requests, **telemetry}


def _normalize_sources(raw: Any, fallback: dict[str, int]) -> dict[str, dict[str, int]]:
    sources: dict[str, dict[str, int]] = {}
    if isinstance(raw, dict):
        for source, row_value in cast(dict[Any, Any], raw).items():
            if not isinstance(row_value, dict):
                continue
            row = cast(dict[str, Any], row_value)
            normalized = _normalize_usage_row(row)
            if normalized["total_tokens"] <= 0 and normalized["requests"] <= 0:
                continue
            source_key = _clean_source(str(source))
            current = sources.get(source_key)
            if current is None:
                sources[source_key] = normalized
            else:
                for key in (*_USAGE_KEYS, *_REQUEST_KEYS, *_COST_KEYS, *_LATENCY_KEYS, *_COUNT_KEYS):
                    current[key] = (
                        (_clean_float(current[key]) if key in _COST_KEYS else _clean_int(current[key]))
                        + (_clean_float(normalized[key]) if key in _COST_KEYS else _clean_int(normalized[key]))
                    )
    if not sources and (fallback["total_tokens"] > 0 or fallback["requests"] > 0):
        sources["user"] = {
            key: fallback[key]
            for key in (*_USAGE_KEYS, *_REQUEST_KEYS, *_COST_KEYS, *_LATENCY_KEYS, *_COUNT_KEYS)
        }
    return sources


def normalize_token_usage_state(raw: Any) -> dict[str, Any]:
    state = default_token_usage_state()
    if not isinstance(raw, dict):
        return state
    raw = cast(dict[str, Any], raw)
    days_raw = raw.get("days")
    if not isinstance(days_raw, dict):
        return state

    days: dict[str, dict[str, Any]] = {}
    for date, row_value in sorted(cast(dict[Any, Any], days_raw).items())[-_MAX_DAYS_RETAINED:]:
        if not isinstance(date, str) or len(date) != 10 or not isinstance(row_value, dict):
            continue
        row = cast(dict[str, Any], row_value)
        try:
            datetime.fromisoformat(date)
        except ValueError:
            # A hand-edited or foreign day key that is not a real date would
            # otherwise reach token_usage_payload's date parsing and fail every
            # settings request; drop it like any other malformed row.
            continue
        normalized = _normalize_usage_row(row)
        if (
            normalized["total_tokens"] <= 0
            and normalized["requests"] <= 0
            and normalized["error_requests"] <= 0
            and normalized["cost_usd"] <= 0
        ):
            continue
        days[date] = {
            "date": date,
            **normalized,
            "sources": _normalize_sources(row.get("sources"), normalized),
        }

    state["days"] = days
    updated_at = raw.get("updated_at")
    state["updated_at"] = updated_at if isinstance(updated_at, str) else None
    return state


def read_token_usage_state() -> dict[str, Any]:
    path = token_usage_state_path()
    if not path.is_file():
        return default_token_usage_state()
    try:
        if path.stat().st_size > _MAX_STATE_FILE_BYTES:
            logger.warning("token usage state too large, ignoring: {}", path)
            return default_token_usage_state()
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("read token usage state failed {}: {}", path, e)
        return default_token_usage_state()
    return normalize_token_usage_state(raw)


def write_token_usage_state(raw: dict[str, Any]) -> dict[str, Any]:
    state = normalize_token_usage_state(raw)
    state["updated_at"] = _utc_now_iso()
    encoded = json.dumps(
        state,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_STATE_FILE_BYTES:
        raise ValueError("token usage state is too large")

    path = token_usage_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "wb") as f:
        f.write(encoded)
        f.write(b"\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return state
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return state


def record_token_usage(
    usage: dict[str, Any] | None,
    *,
    source: str = "user",
    timezone_name: str | None = None,
    now: datetime | None = None,
    latency_ms: int | None = None,
    cost_usd: float | None = None,
    ok: bool | None = None,
) -> dict[str, Any]:
    normalized = _normalize_usage(usage)
    if not normalized:
        return read_token_usage_state()

    with _WRITE_LOCK:
        state = read_token_usage_state()
        days_by_date = cast(dict[str, dict[str, Any]], state["days"])
        day = _local_day(now, timezone_name=timezone_name)
        row: dict[str, Any] = dict(days_by_date.get(day) or {"date": day, "requests": 0})
        for key in _USAGE_KEYS:
            row[key] = _clean_int(row.get(key)) + normalized.get(key, 0)
        row["requests"] = _clean_int(row.get("requests")) + 1
        if normalized.get("estimated_tokens", 0) > 0 and normalized.get("provider_tokens", 0) <= 0:
            row["estimated_requests"] = _clean_int(row.get("estimated_requests")) + 1
        else:
            row["provider_requests"] = _clean_int(row.get("provider_requests")) + 1
        if latency_ms is not None:
            row["latency_ms"] = _clean_int(row.get("latency_ms")) + max(0, latency_ms)
        if cost_usd is not None:
            row["cost_usd"] = _clean_float(row.get("cost_usd")) + max(0.0, cost_usd)
        _bump_ok_error(row, ok)

        source_key = _clean_source(source)
        sources: dict[str, dict[str, Any]] = dict(
            cast(Mapping[str, dict[str, Any]], row.get("sources") or {})
        )
        source_row: dict[str, Any] = dict(sources.get(source_key) or {"requests": 0})
        for key in _USAGE_KEYS:
            source_row[key] = _clean_int(source_row.get(key)) + normalized.get(key, 0)
        source_row["requests"] = _clean_int(source_row.get("requests")) + 1
        if normalized.get("estimated_tokens", 0) > 0 and normalized.get("provider_tokens", 0) <= 0:
            source_row["estimated_requests"] = _clean_int(source_row.get("estimated_requests")) + 1
        else:
            source_row["provider_requests"] = _clean_int(source_row.get("provider_requests")) + 1
        if latency_ms is not None:
            source_row["latency_ms"] = _clean_int(source_row.get("latency_ms")) + max(0, latency_ms)
        if cost_usd is not None:
            source_row["cost_usd"] = _clean_float(source_row.get("cost_usd")) + max(0.0, cost_usd)
        _bump_ok_error(source_row, ok)
        sources[source_key] = source_row
        row["sources"] = sources

        days_by_date[day] = row
        if len(days_by_date) > _MAX_DAYS_RETAINED:
            state["days"] = dict(sorted(days_by_date.items())[-_MAX_DAYS_RETAINED:])
        return write_token_usage_state(state)


def _bump_ok_error(row: dict[str, Any], ok: bool | None) -> None:
    """Increment ok/error request counters based on *ok* (None = unknown)."""
    if ok is True:
        row["ok_requests"] = _clean_int(row.get("ok_requests")) + 1
    elif ok is False:
        row["error_requests"] = _clean_int(row.get("error_requests")) + 1


def record_response_token_usage(
    response: Any,
    *,
    source: str,
    timezone_name: str | None = None,
) -> None:
    try:
        record_token_usage(
            getattr(response, "usage", None),
            source=source,
            timezone_name=timezone_name,
        )
    except Exception:
        logger.exception("failed to record {} token usage", source)


def token_usage_payload(
    *,
    days: int = 371,
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    state = read_token_usage_state()
    days_by_date = cast(dict[str, dict[str, Any]], state["days"])
    today = datetime.fromisoformat(_local_day(now, timezone_name=timezone_name)).date()
    start = today - timedelta(days=max(1, days) - 1)
    day_rows = [
        row
        for date, row in sorted(days_by_date.items())
        if start.isoformat() <= date <= today.isoformat()
    ]
    last_30_start = today - timedelta(days=29)
    last_30 = [
        row
        for date, row in days_by_date.items()
        if last_30_start.isoformat() <= date <= today.isoformat()
    ]
    last_365_start = today - timedelta(days=364)
    last_365 = [
        row
        for date, row in days_by_date.items()
        if last_365_start.isoformat() <= date <= today.isoformat()
    ]
    active_dates = {
        datetime.fromisoformat(date).date()
        for date, row in days_by_date.items()
        if _clean_int(row.get("total_tokens")) > 0
    }
    current_streak = 0
    cursor = today
    while cursor in active_dates:
        current_streak += 1
        cursor -= timedelta(days=1)

    longest_streak = 0
    running_streak = 0
    for cursor in sorted(active_dates):
        if cursor - timedelta(days=1) in active_dates:
            running_streak += 1
        else:
            running_streak = 1
        longest_streak = max(longest_streak, running_streak)

    all_rows = list(days_by_date.values())
    last_30_total_latency = sum(_clean_int(row.get("latency_ms")) for row in last_30)
    last_30_requests = sum(_clean_int(row.get("requests")) for row in last_30)
    return {
        "days": day_rows,
        "total_tokens": sum(_clean_int(row.get("total_tokens")) for row in all_rows),
        "total_tokens_30d": sum(_clean_int(row.get("total_tokens")) for row in last_30),
        "total_tokens_365d": sum(_clean_int(row.get("total_tokens")) for row in last_365),
        "peak_day_tokens": max([_clean_int(row.get("total_tokens")) for row in all_rows] or [0]),
        "current_streak_days": current_streak,
        "longest_streak_days": longest_streak,
        "active_days_30d": sum(1 for row in last_30 if _clean_int(row.get("total_tokens")) > 0),
        "requests_30d": last_30_requests,
        "total_cost_usd": round(sum(_clean_float(row.get("cost_usd")) for row in all_rows), 4),
        "cost_usd_30d": round(sum(_clean_float(row.get("cost_usd")) for row in last_30), 4),
        "cost_usd_365d": round(sum(_clean_float(row.get("cost_usd")) for row in last_365), 4),
        "error_requests_30d": sum(_clean_int(row.get("error_requests")) for row in last_30),
        "avg_latency_ms_30d": (
            round(last_30_total_latency / last_30_requests, 1) if last_30_requests else 0
        ),
        "total_latency_ms_30d": last_30_total_latency,
        "updated_at": state.get("updated_at"),
    }


def estimate_cost_usd(
    provider: str | None,
    model: str | None,
    usage: Mapping[str, Any] | None,
    cost_rates: Mapping[str, Any] | None,
) -> float:
    """Estimate USD cost from token usage and a configurable per-1M price table.

    Keys are matched ``"provider/model"`` → ``"provider"`` → ``"*"``. Each rate
    maps to an object/dict with ``input`` and ``output`` per-1M-token prices.
    Returns 0.0 when no matching rate is configured.
    """
    if not cost_rates:
        return 0.0
    rates = cast(Mapping[str, Any], cost_rates)
    provider = provider or ""
    model = model or ""
    rate: Any = None
    for key in (f"{provider}/{model}", provider, "*"):
        if key in rates:
            rate = rates[key]
            break
    if rate is None:
        return 0.0
    input_rate = _clean_float(getattr(rate, "input", None) if hasattr(rate, "input") else rate.get("input"))
    output_rate = _clean_float(getattr(rate, "output", None) if hasattr(rate, "output") else rate.get("output"))
    usage = usage or {}
    input_tokens = _clean_int(usage.get("prompt_tokens"))
    output_tokens = _clean_int(usage.get("completion_tokens"))
    return round(
        (input_tokens / 1_000_000) * input_rate
        + (output_tokens / 1_000_000) * output_rate,
        6,
    )


class TokenUsageHook(AgentHook):
    """Persist provider-reported token usage without coupling it to chat messages."""

    def __init__(
        self,
        *,
        timezone_name: str | None = None,
        cost_rates: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._timezone_name = timezone_name
        self._cost_rates = dict(cost_rates or {})

    async def after_iteration(self, context: AgentHookContext) -> None:
        try:
            ok = context.error is None and context.stop_reason not in ("error", "cancelled")
            cost_usd = estimate_cost_usd(
                context.provider,
                context.model,
                context.usage,
                self._cost_rates,
            )
            record_token_usage(
                context.usage,
                source=_source_from_session_key(context.session_key),
                timezone_name=self._timezone_name,
                latency_ms=context.latency_ms,
                cost_usd=cost_usd,
                ok=ok,
            )
        except Exception:
            logger.exception("failed to record token usage")
