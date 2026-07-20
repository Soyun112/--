"""건물명·역이름·주소 -> 좌표(위경도) 지오코딩.

사용자가 위/경도 숫자 대신 "강남역", "코엑스", "OO초등학교" 같은 이름을 입력할 수 있게
한다. 여러 제공자를 순서대로 시도하며, 하나라도 성공하면 그 결과를 사용한다:

  1) 내장 사전(DEMO_PLACES + STATION_DICT) — 데모 좌표/서울 주요 역은 키 없이 즉시 응답
  2) 카카오 로컬 키워드 검색 (KAKAO_REST_API_KEY) — 건물·상호·역 이름에 가장 강함
  3) 네이버 지역 검색 (NAVER_SEARCH_CLIENT_ID/SECRET)
  4) Tmap POI 통합검색 (TMAP_APP_KEY) — kids가 이미 보유한 키 재사용

키가 하나도 없거나 모두 실패하면 사전에 없는 이름은 None을 반환한다. 백엔드에서
호출하므로 브라우저 CORS 문제 없이 안전하게 시크릿 키를 쓸 수 있다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests

from ..config import settings


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    label: str
    source: str


# 데모 시나리오용 좌표(샘플 공공데이터가 몰려 있는 강남 일대). 실제 지오코딩보다 우선해
# 데모에서 이름을 입력해도 안전점수/스탬프가 제대로 나오도록 한다.
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

# 서울 주요 역(실제 이름 입력 시 키 없이도 동작하도록 최소 사전 제공).
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
    for table, src in ((DEMO_PLACES, "DEMO_DICT"), (STATION_DICT, "STATION_DICT")):
        # 정확 일치 우선, 없으면 "역" 유무를 보정해 재시도
        for candidate in (key, key.rstrip("역"), key + "역"):
            if candidate in table:
                lat, lng, label = table[candidate]
                return GeocodeResult(lat=lat, lng=lng, label=label, source=src)
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
        return GeocodeResult(lat=lat, lng=lng, label=label, source="KAKAO_LOCAL")
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
        # 지역검색 mapx/mapy는 WGS84 경위도 * 1e7 정수
        lng, lat = float(it["mapx"]) / 1e7, float(it["mapy"]) / 1e7
        if not _in_korea(lat, lng):
            return None
        return GeocodeResult(lat=lat, lng=lng, label=_strip_tags(it.get("title")) or query, source="NAVER_LOCAL")
    except Exception:
        return None


def _tmap_poi(query: str) -> Optional[GeocodeResult]:
    if not settings.tmap_app_key:
        return None
    try:
        resp = requests.get(
            "https://apis.openapi.sk.com/tmap/pois",
            params={"version": "1", "searchKeyword": query, "resCoordType": "WGS84GEO", "count": 1},
            headers={"appKey": settings.tmap_app_key},
            timeout=10,
        )
        resp.raise_for_status()
        pois = resp.json().get("searchPoiInfo", {}).get("pois", {}).get("poi", [])
        if not pois:
            return None
        poi = pois[0]
        lat, lng = float(poi["noorLat"]), float(poi["noorLon"])
        if not _in_korea(lat, lng):
            return None
        name = poi.get("name") or query
        return GeocodeResult(lat=lat, lng=lng, label=name, source="TMAP_POI")
    except Exception:
        return None


def geocode(query: str) -> Optional[GeocodeResult]:
    """이름/주소 문자열을 좌표로 변환. 실패 시 None."""
    q = (query or "").strip()
    if not q:
        return None

    hit = _lookup_dict(q)
    if hit:
        return hit

    for provider in (_kakao_keyword, _naver_local, _tmap_poi):
        result = provider(q)
        if result:
            return result
    return None
