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
TMAP_ROAD_MATCH_URL = "https://apis.openapi.sk.com/tmap/road/matchToRoads"

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
    count: int = 10,
    near: tuple[float, float] | None = None,
    max_distance_m: float = 2500.0,
    radius_km: int = 2,
) -> Optional[TmapGeoHit]:
    """Tmap POI 통합검색 — 건물명·학원·역 이름 (반경 검색 우선)."""
    if not settings.tmap_app_key:
        return None
    try:
        params: dict[str, str | int | float] = {
            "version": "1",
            "searchKeyword": query,
            "resCoordType": "WGS84GEO",
            "count": count,
        }
        if near is not None:
            params.update(
                {
                    "searchtypCd": "R",
                    "centerLat": near[0],
                    "centerLon": near[1],
                    "radius": radius_km,
                }
            )

        resp = requests.get(
            TMAP_POI_URL,
            params=params,
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


def _append_unique_coord(
    coords: list[tuple[float, float]],
    lat: float,
    lng: float,
    *,
    min_gap_m: float = 0.5,
) -> None:
    if not coords:
        coords.append((lat, lng))
        return
    prev_lat, prev_lng = coords[-1]
    if prev_lat == lat and prev_lng == lng:
        return
    from math import asin, cos, radians, sin, sqrt

    lat1, lng1 = radians(prev_lat), radians(prev_lng)
    lat2, lng2 = radians(lat), radians(lng)
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    gap = 6_371_000 * 2 * asin(sqrt(h))
    if gap < min_gap_m:
        return
    coords.append((lat, lng))


def match_coords_to_roads(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Tmap Road API(이동한도로찾기)로 좌표를 도로망에 맞춰 보간점을 추가한다."""
    if not settings.tmap_app_key or len(coords) < 2:
        return coords
    if not settings.tmap_road_match_enabled:
        return coords

    # API 최대 100점 — 긴 경로는 구간별로 나눠 호출
    chunk_size = 90
    matched_all: list[tuple[float, float]] = []
    for start in range(0, len(coords), chunk_size):
        chunk = coords[start : start + chunk_size]
        if len(chunk) < 2:
            if chunk:
                _append_unique_coord(matched_all, chunk[0][0], chunk[0][1])
            continue
        coords_str = "|".join(f"{lng},{lat}" for lat, lng in chunk)
        try:
            resp = requests.post(
                TMAP_ROAD_MATCH_URL,
                params={"version": "1"},
                headers={
                    **_headers(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"responseType": "1", "coords": coords_str},
                timeout=15,
            )
            resp.raise_for_status()
            points = resp.json().get("resultData", {}).get("matchedPoints", [])
        except Exception:
            for lat, lng in chunk:
                _append_unique_coord(matched_all, lat, lng)
            continue

        for point in points:
            loc = point.get("matchedLocation") or point.get("mathedLocation")
            if not loc:
                continue
            try:
                _append_unique_coord(
                    matched_all,
                    float(loc["latitude"]),
                    float(loc["longitude"]),
                )
            except (TypeError, ValueError, KeyError):
                continue

    return matched_all if len(matched_all) >= 2 else coords
