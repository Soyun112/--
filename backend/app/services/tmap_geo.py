"""Tmap Open API 지오코딩 (동일 appKey로 POI·주소 검색).

SK Open API appKey 하나로 보행자 길찾기·POI·주소 지오코딩을 함께 쓸 수 있다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests

from ..config import settings

TMAP_POI_URL = "https://apis.openapi.sk.com/tmap/pois"
TMAP_FULLADDR_URL = "https://apis.openapi.sk.com/tmap/geo/fullAddrGeo"

_KO_BOUNDS = {"lat_min": 32.0, "lat_max": 39.5, "lng_min": 124.0, "lng_max": 132.0}


@dataclass
class TmapGeoHit:
    lat: float
    lng: float
    label: str
    source: str


def _in_korea(lat: float, lng: float) -> bool:
    return (
        _KO_BOUNDS["lat_min"] < lat < _KO_BOUNDS["lat_max"]
        and _KO_BOUNDS["lng_min"] < lng < _KO_BOUNDS["lng_max"]
    )


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _headers() -> dict[str, str]:
    return {"appKey": settings.tmap_app_key}


def search_poi(
    query: str,
    *,
    count: int = 5,
    near: tuple[float, float] | None = None,
    max_distance_m: float = 2500.0,
) -> Optional[TmapGeoHit]:
    """Tmap POI 통합검색 — 건물명·학원·역 이름."""
    if not settings.tmap_app_key:
        return None
    try:
        resp = requests.get(
            TMAP_POI_URL,
            params={
                "version": "1",
                "searchKeyword": query,
                "resCoordType": "WGS84GEO",
                "count": count,
            },
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        pois = resp.json().get("searchPoiInfo", {}).get("pois", {}).get("poi", [])
        if not pois:
            return None
        if not isinstance(pois, list):
            pois = [pois]

        def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
            from math import asin, cos, radians, sin, sqrt

            lat1, lng1 = radians(a[0]), radians(a[1])
            lat2, lng2 = radians(b[0]), radians(b[1])
            dlat, dlng = lat2 - lat1, lng2 - lng1
            h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
            return 6_371_000 * 2 * asin(sqrt(h))

        best: Optional[TmapGeoHit] = None
        best_score = float("inf")
        query_norm = query.strip().replace(" ", "").lower()
        for poi in pois:
            lat, lng = float(poi["noorLat"]), float(poi["noorLon"])
            if not _in_korea(lat, lng):
                continue
            if near is not None and _dist_m(near, (lat, lng)) > max_distance_m:
                continue
            name = _strip_tags(poi.get("name") or query)
            name_norm = name.replace(" ", "").lower()
            name_penalty = 0 if query_norm in name_norm or name_norm in query_norm else 500
            dist_penalty = _dist_m(near, (lat, lng)) if near else 0
            score = name_penalty + dist_penalty
            if score < best_score:
                best_score = score
                best = TmapGeoHit(lat=lat, lng=lng, label=name, source="TMAP_POI")
        return best
    except Exception:
        return None


def geocode_full_address(query: str) -> Optional[TmapGeoHit]:
    """Tmap Full Text Geocoding — 도로명·지번 주소."""
    if not settings.tmap_app_key:
        return None
    try:
        resp = requests.get(
            TMAP_FULLADDR_URL,
            params={
                "version": "1",
                "fullAddr": query,
                "addressFlag": "F00",
                "coordType": "WGS84GEO",
                "page": "1",
                "count": "1",
            },
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        coord_info = payload.get("coordinateInfo")
        items = coord_info.get("coordinate", []) if isinstance(coord_info, dict) else coord_info
        if isinstance(items, dict):
            items = [items]
        if not items:
            return None
        item = items[0]
        lat = float(item.get("lat") or item.get("newLat") or 0)
        lng = float(item.get("lon") or item.get("newLon") or 0)
        if not _in_korea(lat, lng):
            return None
        label = item.get("newAddress") or item.get("address") or query
        return TmapGeoHit(lat=lat, lng=lng, label=str(label), source="TMAP_FULLADDR")
    except Exception:
        return None
