"""Web search provider usage fetchers for /status command."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast


@dataclass
class SearchUsageInfo:
    """Structured usage info returned by a provider fetcher."""

    provider: str
    supported: bool = False          # True if the provider has a usage API
    error: str | None = None         # Set when the API call failed

    # Usage counters (None = not available for this provider)
    used: int | None = None
    limit: int | None = None
    remaining: int | None = None
    reset_date: str | None = None    # ISO date string, e.g. "2026-05-01"

    # Tavily-specific breakdown
    search_used: int | None = None
    extract_used: int | None = None
    crawl_used: int | None = None

    def format(self) -> str:
        """Return a human-readable multi-line string for /status output."""
        lines: list[str] = [f"🔍 Web Search: {self.provider}"]

        if not self.supported:
            lines.append("   Usage tracking: not available for this provider")
            return "\n".join(lines)

        if self.error:
            lines.append(f"   Usage: unavailable ({self.error})")
            return "\n".join(lines)

        if self.used is not None and self.limit is not None:
            lines.append(f"   Usage: {self.used} / {self.limit} requests")
        elif self.used is not None:
            lines.append(f"   Usage: {self.used} requests")

        # Tavily breakdown
        breakdown_parts: list[str] = []
        if self.search_used is not None:
            breakdown_parts.append(f"Search: {self.search_used}")
        if self.extract_used is not None:
            breakdown_parts.append(f"Extract: {self.extract_used}")
        if self.crawl_used is not None:
            breakdown_parts.append(f"Crawl: {self.crawl_used}")
        if breakdown_parts:
            lines.append(f"   Breakdown: {' | '.join(breakdown_parts)}")

        if self.remaining is not None:
            lines.append(f"   Remaining: {self.remaining} requests")

        if self.reset_date:
            lines.append(f"   Resets: {self.reset_date}")

        return "\n".join(lines)


async def fetch_search_usage(
    provider: str,
    api_key: str | None = None,
) -> SearchUsageInfo:
    """
    Fetch usage info for the configured web search provider.

    Args:
        provider: Provider name (e.g. "tavily", "brave", "duckduckgo").
        api_key:  API key for the provider (falls back to env vars).

    Returns:
        SearchUsageInfo with populated fields where available.
    """
    p = (provider or "duckduckgo").strip().lower()

    if p == "tavily":
        return await _fetch_tavily_usage(api_key)
    else:
        # brave, duckduckgo, searxng, jina, unknown — no usage API
        return SearchUsageInfo(provider=p, supported=False)


# ---------------------------------------------------------------------------
# Tavily
# ---------------------------------------------------------------------------

async def _fetch_tavily_usage(api_key: str | None) -> SearchUsageInfo:
    """Fetch usage from GET https://api.tavily.com/usage."""
    import httpx

    key = api_key or os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return SearchUsageInfo(
            provider="tavily",
            supported=True,
            error="TAVILY_API_KEY not configured",
        )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://api.tavily.com/usage",
                headers={"Authorization": f"Bearer {key}"},
            )
            r.raise_for_status()
        data = cast(dict[str, Any], r.json())
        return _parse_tavily_usage(data)
    except httpx.HTTPStatusError as e:
        return SearchUsageInfo(
            provider="tavily",
            supported=True,
            error=f"HTTP {e.response.status_code}",
        )
    except Exception as e:
        return SearchUsageInfo(
            provider="tavily",
            supported=True,
            error=str(e)[:80],
        )


def _parse_tavily_usage(data: dict[str, Any]) -> SearchUsageInfo:
    """
    Parse Tavily /usage response.

    Actual API response shape:
    {
      "account": {
        "current_plan": "Researcher",
        "plan_usage": 20,
        "plan_limit": 1000,
        "search_usage": 20,
        "crawl_usage": 0,
        "extract_usage": 0,
        "map_usage": 0,
        "research_usage": 0,
        "paygo_usage": 0,
        "paygo_limit": null
      }
    }
    """
    raw_account = data.get("account")
    account = cast(dict[str, Any], raw_account) if isinstance(raw_account, dict) else {}
    used = _optional_int(account.get("plan_usage"))
    limit = _optional_int(account.get("plan_limit"))

    # Compute remaining
    remaining = None
    if used is not None and limit is not None:
        remaining = max(0, limit - used)

    return SearchUsageInfo(
        provider="tavily",
        supported=True,
        used=used,
        limit=limit,
        remaining=remaining,
        search_used=_optional_int(account.get("search_usage")),
        extract_used=_optional_int(account.get("extract_usage")),
        crawl_used=_optional_int(account.get("crawl_usage")),
    )


def _optional_int(value: Any) -> int | None:
    """Coerce JSON numerics (including string forms) to int; else None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Local search telemetry
#
# Providers without a usage API (or for quick local insight) still record
# per-call latency and ok/error counts locally, persisted per day.
# ---------------------------------------------------------------------------

_SEARCH_USAGE_SCHEMA_VERSION = 1
_MAX_SEARCH_DAYS_RETAINED = 400
_SEARCH_WRITE_LOCK = threading.Lock()
_search_enabled = True


def set_search_usage_enabled(enabled: bool) -> None:
    """Globally enable/disable local search call telemetry."""
    global _search_enabled
    _search_enabled = bool(enabled)


def search_usage_state_path() -> Path:
    """Return the local search-usage state file path (without creating it)."""
    from nanobot.config.paths import get_webui_dir

    return get_webui_dir() / "search-usage.json"


def _empty_search_state() -> dict[str, Any]:
    return {"schema_version": _SEARCH_USAGE_SCHEMA_VERSION, "days": {}}


def _sint(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _search_day(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def _read_search_state() -> dict[str, Any]:
    path = search_usage_state_path()
    if not path.is_file():
        return _empty_search_state()
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_search_state()
    if not isinstance(raw, dict):
        return _empty_search_state()
    state = cast(dict[str, Any], raw)
    if not isinstance(state.get("days"), dict):
        return _empty_search_state()
    return state


def _write_search_state(state: dict[str, Any]) -> None:
    path = search_usage_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def record_local_search_call(
    provider: str,
    *,
    latency_ms: int | None = None,
    ok: bool = True,
) -> None:
    """Record one local search call for *provider* (call count + latency)."""
    if not _search_enabled:
        return
    name = (provider or "unknown").strip().lower() or "unknown"
    latency = max(0, latency_ms) if latency_ms is not None else 0
    with _SEARCH_WRITE_LOCK:
        state = _read_search_state()
        days = cast(dict[str, Any], state["days"])
        day = _search_day()
        provider_row = cast(dict[str, Any], days.get(day, {}))
        row = cast(dict[str, Any], provider_row.get(name, {"calls": 0, "errors": 0, "latency_ms": 0}))
        row["calls"] = _sint(row.get("calls")) + 1
        row["latency_ms"] = _sint(row.get("latency_ms")) + latency
        if not ok:
            row["errors"] = _sint(row.get("errors")) + 1
        provider_row[name] = row
        days[day] = provider_row
        if len(days) > _MAX_SEARCH_DAYS_RETAINED:
            state["days"] = dict(sorted(days.items())[-_MAX_SEARCH_DAYS_RETAINED:])
        _write_search_state(state)


def search_usage_payload(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return aggregated local search telemetry for overview surfaces."""
    state = _read_search_state()
    days = cast(dict[str, Any], state["days"])
    today = _search_day(now)
    try:
        start = (datetime.fromisoformat(today).date() - timedelta(days=29)).isoformat()
    except ValueError:
        start = today
    providers_all: dict[str, dict[str, int]] = {}
    providers_30d: dict[str, dict[str, int]] = {}
    for date, provider_row in days.items():
        if not isinstance(provider_row, dict):
            continue
        typed_providers = cast(dict[str, Any], provider_row)
        in_window = start <= date <= today
        for name, row in typed_providers.items():
            if not isinstance(row, dict):
                continue
            typed_row = cast(dict[str, Any], row)
            calls = _sint(typed_row.get("calls"))
            errors = _sint(typed_row.get("errors"))
            latency = _sint(typed_row.get("latency_ms"))
            for bucket in (
                providers_all,
                providers_30d if in_window else None,
            ):
                if bucket is None:
                    continue
                acc = bucket.setdefault(name, {"calls": 0, "errors": 0, "latency_ms": 0})
                acc["calls"] += calls
                acc["errors"] += errors
                acc["latency_ms"] += latency
    return {
        "providers": {
            name: {
                "calls": row["calls"],
                "errors": row["errors"],
                "avg_latency_ms": round(row["latency_ms"] / row["calls"], 1) if row["calls"] else 0,
            }
            for name, row in sorted(providers_30d.items())
        },
        "calls_30d": sum(row["calls"] for row in providers_30d.values()),
        "errors_30d": sum(row["errors"] for row in providers_30d.values()),
        "calls_total": sum(row["calls"] for row in providers_all.values()),
    }


