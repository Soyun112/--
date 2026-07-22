"""건물명·역이름·주소 -> 좌표(위경도) 지오코딩.

  일반: 내장 사전 → Kakao keyword → Naver → Tmap
  문서 도로명주소: juso.go.kr → Kakao address.json → Kakao keyword.json
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests

from ..config import settings
from ..console_safe import safe_print
from .tmap_geo import geocode_full_address, search_poi


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    label: str
    source: str


DEMO_PLACES: dict[str, tuple[float, float, str]] = {
    "우리집": (37.5012, 127.0499, "개나리SK뷰5차아파트"),
    "집": (37.5012, 127.0499, "개나리SK뷰5차아파트"),
    "개나리SK뷰5차아파트": (37.5012, 127.0499, "개나리SK뷰5차아파트"),
    "개나리SK뷰5차": (37.5012, 127.0499, "개나리SK뷰5차아파트"),
    "필수학학원": (37.4989686, 127.0525688, "필수학학원"),
    "필수수학학원": (37.4989686, 127.0525688, "필수학학원"),
    "필수수학": (37.4989686, 127.0525688, "필수학학원"),
    "도성초등학교": (37.5009638, 127.0491450, "도성초등학교"),
    "도성초": (37.5009638, 127.0491450, "도성초등학교"),
    "OO초등학교": (37.5009638, 127.0491450, "도성초등학교"),
    "학교": (37.5009638, 127.0491450, "도성초등학교"),
    "초등학교": (37.5009638, 127.0491450, "도성초등학교"),
    "OO유치원": (37.4998, 127.0370, "OO유치원 (데모)"),
    "유치원": (37.4998, 127.0370, "OO유치원 (데모)"),
    "학원": (37.4989686, 127.0525688, "필수학학원"),
    "OO초등학교 정문": (37.5008, 127.0490, "도성초등학교 정문"),
    "OO초등학교 후문": (37.5011, 127.0493, "도성초등학교 후문"),
}

STATION_DICT: dict[str, tuple[float, float, str]] = {
    "강남역": (37.497942, 127.027621, "강남역 (서울 강남구)"),
    "역삼역": (37.500628, 127.036455, "역삼역"),
    "선릉역": (37.504503, 127.049008, "선릉역"),
    "삼성역": (37.508844, 127.063160, "삼성역"),
    "코엑스": (37.512670, 127.058859, "코엑스 (삼성동)"),
    "강남구청역": (37.517186, 127.041028, "강남구청역"),
    "신논현역": (37.504598, 127.025047, "신논현역"),
    "교대역": (37.493514, 127.014260, "교대역"),
    "양재역": (37.484445, 127.034513, "양재역"),
    "서울역": (37.554722, 126.970833, "서울역"),
    "서울시청": (37.566295, 126.977945, "서울시청"),
    "시청": (37.566295, 126.977945, "서울시청"),
    "홍대입구역": (37.557192, 126.925381, "홍대입구역"),
    "잠실역": (37.513301, 127.100158, "잠실역"),
    "여의도": (37.521624, 126.924191, "여의도"),
    "명동": (37.560989, 126.986324, "명동"),
    "사당역": (37.476452, 126.981618, "사당역"),
    "고속터미널역": (37.505289, 127.004942, "고속터미널역"),
}

_KO_BOUNDS = {"lat_min": 32.0, "lat_max": 39.5, "lng_min": 124.0, "lng_max": 132.0}


def _in_korea(lat: float, lng: float) -> bool:
    return (
        _KO_BOUNDS["lat_min"] < lat < _KO_BOUNDS["lat_max"]
        and _KO_BOUNDS["lng_min"] < lng < _KO_BOUNDS["lng_max"]
    )


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _lookup_dict(query: str) -> Optional[GeocodeResult]:
    key = query.strip().replace(" ", "")
    key_lower = key.lower()
    for table, src in ((DEMO_PLACES, "DEMO_DICT"), (STATION_DICT, "STATION_DICT")):
        for candidate in (key, key.rstrip("역"), key + "역", key_lower):
            for table_key, value in table.items():
                if table_key == candidate or table_key.lower() == candidate.lower():
                    lat, lng, label = value
                    return GeocodeResult(lat=lat, lng=lng, label=label, source=src)
    return None


def _kakao_address(query: str) -> Optional[GeocodeResult]:
    if not settings.kakao_rest_api_key:
        return None
    try:
        resp = requests.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            params={"query": query, "size": 1},
            headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        if not docs:
            return None
        d = docs[0]
        road = d.get("road_address") or {}
        addr = d.get("address") or {}
        lat = float(road.get("y") or addr.get("y") or d.get("y"))
        lng = float(road.get("x") or addr.get("x") or d.get("x"))
        if not _in_korea(lat, lng):
            return None
        label = (road.get("address_name") if road else None) or d.get("address_name") or query
        return GeocodeResult(lat=lat, lng=lng, label=label, source="KAKAO_ADDRESS")
    except Exception:
        return None


def _juso_address(query: str) -> Optional[GeocodeResult]:
    """도로명주소 API → 표준 roadAddr → Kakao address로 좌표."""
    if not settings.juso_confm_key:
        return None
    try:
        resp = requests.get(
            "https://business.juso.go.kr/addrlink/addrLinkApi.do",
            params={
                "confmKey": settings.juso_confm_key,
                "currentPage": 1,
                "countPerPage": 1,
                "keyword": query,
                "resultType": "json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        common = (data.get("results") or {}).get("common") or {}
        if str(common.get("errorCode", "0")) not in ("0", "000"):
            safe_print(f"[지오코딩] juso 오류: {common.get('errorMessage')}")
            return None
        rows = (data.get("results") or {}).get("juso") or []
        if not rows:
            return None
        road = (rows[0].get("roadAddr") or rows[0].get("roadAddrPart1") or "").strip()
        if not road:
            return None
        hit = _kakao_address(road)
        if hit:
            return GeocodeResult(lat=hit.lat, lng=hit.lng, label=road, source="JUSO+KAKAO_ADDRESS")
        return None
    except Exception as exc:
        safe_print(f"[지오코딩] juso 실패: {exc}")
        return None


def _kakao_keyword(query: str) -> Optional[GeocodeResult]:
    if not settings.kakao_rest_api_key:
        return None
    try:
        resp = requests.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": query, "size": 1},
            headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        if not docs:
            return None
        d = docs[0]
        lat, lng = float(d["y"]), float(d["x"])
        if not _in_korea(lat, lng):
            return None
        label = d.get("place_name") or d.get("road_address_name") or query
        return GeocodeResult(lat=lat, lng=lng, label=label, source="KAKAO_KEYWORD")
    except Exception:
        return None


def _naver_local(query: str) -> Optional[GeocodeResult]:
    if not (settings.naver_search_client_id and settings.naver_search_client_secret):
        return None
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/local.json",
            params={"query": query, "display": 1},
            headers={
                "X-Naver-Client-Id": settings.naver_search_client_id,
                "X-Naver-Client-Secret": settings.naver_search_client_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return None
        it = items[0]
        lng, lat = float(it["mapx"]) / 1e7, float(it["mapy"]) / 1e7
        if not _in_korea(lat, lng):
            return None
        return GeocodeResult(lat=lat, lng=lng, label=_strip_tags(it.get("title")) or query, source="NAVER_LOCAL")
    except Exception:
        return None


def _tmap_fulladdr(query: str) -> Optional[GeocodeResult]:
    hit = geocode_full_address(query)
    return GeocodeResult(hit.lat, hit.lng, hit.label, hit.source) if hit else None


def looks_like_road_address(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    return bool(re.search(r"(로|길|대로)\s*\d+", q))


def geocode(
    query: str,
    near: tuple[float, float] | None = None,
    *,
    prefer_address: bool | None = None,
) -> Optional[GeocodeResult]:
    q = (query or "").strip()
    if not q:
        return None

    hit = _lookup_dict(q)
    if hit:
        return hit

    use_address_first = prefer_address if prefer_address is not None else looks_like_road_address(q)
    poi_near = near or (settings.demo_center_lat, settings.demo_center_lng)

    if use_address_first:
        for name, provider in (
            ("juso", _juso_address),
            ("kakao_address", _kakao_address),
            ("tmap_fulladdr", _tmap_fulladdr),
            ("kakao_keyword", _kakao_keyword),
        ):
            if name == "tmap_fulladdr" and not settings.tmap_app_key:
                continue
            result = provider(q)
            if result:
                safe_print(f"[지오코딩] '{q}' → {result.source}")
                return result
        if settings.tmap_app_key:
            poi = search_poi(q, near=poi_near)
            if poi:
                return GeocodeResult(poi.lat, poi.lng, poi.label, poi.source)
        return None

    for provider in (_kakao_keyword, _naver_local):
        result = provider(q)
        if result:
            return result

    if settings.tmap_app_key:
        poi = search_poi(q, near=poi_near)
        if poi:
            return GeocodeResult(poi.lat, poi.lng, poi.label, poi.source)
        result = _tmap_fulladdr(q)
        if result:
            return result
    return None


def geocode_document_address(query: str) -> Optional[GeocodeResult]:
    """문서 구간 폴백 체인.

    1) juso.go.kr  2) Kakao address.json  3) Kakao keyword.json  4) Tmap fullAddr
    (Kakao 앱에 로컬 권한이 없으면 3에서 떨어지고 Tmap이 받음)
    """
    q = (query or "").strip()
    if not q:
        return None

    variants = [q]
    # 서울특별시 ↔ 서울 표기 차이
    if "서울특별시" in q:
        variants.append(q.replace("서울특별시", "서울", 1))
    elif q.startswith("서울 "):
        variants.append(q.replace("서울 ", "서울특별시 ", 1))

    chain = [
        ("juso", _juso_address),
        ("kakao_address", _kakao_address),
        ("kakao_keyword", _kakao_keyword),
        ("tmap_fulladdr", _tmap_fulladdr),
    ]
    for variant in variants:
        for name, provider in chain:
            if name == "tmap_fulladdr" and not settings.tmap_app_key:
                continue
            result = provider(variant)
            if result:
                safe_print(f"[문서지오코딩] '{variant}' → {result.source} (단계={name})")
                return result
            safe_print(f"[문서지오코딩] '{variant}' 단계={name} 실패")
    safe_print(f"[문서지오코딩] '{q}' 전부 실패")
    return None
