"""Tmap Free 티어 일일 한도 관리 + 응답 캐시.

Free 기준(2026 SK Open API):
  - 경로안내(보행 포함): 1,000건/일
  - Road API: 1,000건/일
  - POI 검색: 20,000건/일
  - 지오코딩: 20,000건/일

검색 1회 목표: 보행 1 + Road 0~1 + POI 0~2 (캐시/사전命中 시 0)
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from typing import Any, Callable, TypeVar

from ..config import settings

T = TypeVar("T")

_lock = Lock()
_day = date.today()
_counts: dict[str, int] = {"route": 0, "road": 0, "poi": 0, "geocode": 0}
_cache: dict[str, tuple[Any, datetime]] = {}


def _limits() -> dict[str, int]:
    return {
        "route": settings.tmap_daily_limit_route,
        "road": settings.tmap_daily_limit_road,
        "poi": settings.tmap_daily_limit_poi,
        "geocode": settings.tmap_daily_limit_geocode,
    }


def _reserve() -> dict[str, int]:
    return {
        "route": settings.tmap_daily_reserve_route,
        "road": settings.tmap_daily_reserve_road,
        "poi": 0,
        "geocode": 0,
    }


def _reset_if_new_day() -> None:
    global _day, _counts
    today = date.today()
    if today != _day:
        _day = today
        _counts = {key: 0 for key in _counts}


def usage_snapshot() -> dict[str, int]:
    with _lock:
        _reset_if_new_day()
        return dict(_counts)


def can_use(category: str) -> bool:
    with _lock:
        _reset_if_new_day()
        limit = _limits().get(category, 999_999)
        reserve = _reserve().get(category, 0)
        return _counts.get(category, 0) < max(0, limit - reserve)


def record_use(category: str) -> None:
    with _lock:
        _reset_if_new_day()
        _counts[category] = _counts.get(category, 0) + 1


def get_cached(key: str, ttl_seconds: int) -> Any | None:
    with _lock:
        entry = _cache.get(key)
        if not entry:
            return None
        value, expires = entry
        if datetime.now(UTC) >= expires:
            del _cache[key]
            return None
        return value


def set_cached(key: str, value: Any, ttl_seconds: int) -> None:
    with _lock:
        _cache[key] = (value, datetime.now(UTC) + timedelta(seconds=ttl_seconds))


def make_key(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def cached_api_call(
    *,
    cache_key: str,
    category: str,
    ttl_seconds: int,
    fetch: Callable[[], T | None],
) -> T | None:
    """캐시 → 한도 확인 → API 1회. 실패 시 None."""
    cached = get_cached(cache_key, ttl_seconds)
    if cached is not None:
        return cached

    if not can_use(category):
        print(
            f"[TmapQuota] {category} 일일 한도 근접 "
            f"(used={usage_snapshot().get(category, 0)}, limit={_limits().get(category)})"
        )
        return None

    result = fetch()
    if result is not None:
        record_use(category)
        set_cached(cache_key, result, ttl_seconds)
    return result
