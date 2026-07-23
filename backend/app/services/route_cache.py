"""경로·리포트 인메모리 캐시 (동일 OD + 시간대 재사용)."""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

_LOCK = threading.Lock()
_ROUTE: dict[str, tuple[float, dict[str, Any]]] = {}
_REPORTS: dict[str, tuple[float, dict[str, Any]]] = {}

# 시연 중 같은 경로 반복 클릭 → 즉시 응답
TTL_S = 6 * 3600


def make_route_key(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    *,
    time_mode: str = "auto",
    is_night: bool = False,
    mock: bool | None = None,
) -> str:
    raw = (
        f"{origin_lat:.5f},{origin_lng:.5f}|"
        f"{dest_lat:.5f},{dest_lng:.5f}|"
        f"{time_mode}|{int(bool(is_night))}|{mock}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _get(store: dict[str, tuple[float, dict[str, Any]]], key: str) -> dict[str, Any] | None:
    with _LOCK:
        item = store.get(key)
        if not item:
            return None
        ts, data = item
        if time.time() - ts > TTL_S:
            del store[key]
            return None
        return data


def _put(store: dict[str, tuple[float, dict[str, Any]]], key: str, data: dict[str, Any]) -> None:
    with _LOCK:
        store[key] = (time.time(), data)


def get_route(key: str) -> dict[str, Any] | None:
    return _get(_ROUTE, key)


def put_route(key: str, data: dict[str, Any]) -> None:
    _put(_ROUTE, key, data)


def get_reports(key: str) -> dict[str, Any] | None:
    return _get(_REPORTS, key)


def put_reports(key: str, data: dict[str, Any]) -> None:
    _put(_REPORTS, key, data)


def clear_all() -> None:
    with _LOCK:
        _ROUTE.clear()
        _REPORTS.clear()
