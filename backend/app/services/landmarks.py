"""경로 주변 랜드마크(편의점·문구점 등)를 아이 친화적 단어로 변환.

아이는 "58m"보다 "편의점 쪽으로"가 훨씬 이해하기 쉽다. 실제로는 네이버 지역검색
(NAVER_SEARCH_CLIENT_ID/SECRET)으로 좌표 주변 건물을 찾고, 키가 없거나 실패하면
좌표 기반 결정적(deterministic) MOCK 랜드마크를 돌려줘 오프라인 데모에서도 항상
자연스럽게 보이도록 한다. 백엔드에서 호출하므로 브라우저 CORS/시크릿 문제가 없다.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

import requests

from ..config import settings

# 통학로에서 흔히 보이고 아이에게 익숙한 랜드마크(문구는 프론트에서 "~ 쪽으로"로 조합).
_KID_LANDMARKS = [
    "편의점",
    "문구점",
    "빵집",
    "약국",
    "놀이터",
    "분식집",
    "카페",
    "마트",
    "은행",
    "태권도장",
    "우체국",
    "꽃집",
]

# 네이버 지역검색에 쓸 대표 키워드(아이 눈높이 랜드마크 위주).
_SEARCH_KEYWORDS = ["편의점", "문구점", "놀이터", "빵집", "약국"]

_NAVER_LOCAL_URL = "https://openapi.naver.com/v1/search/local.json"
_MAX_LANDMARK_DISTANCE_M = 300.0


def _rough_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """짧은 거리용 근사 Haversine(랜드마크 근접 판정에 충분)."""
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    dlat = (lat2 - lat1) * 111_320.0
    dlng = (lng2 - lng1) * 111_320.0 * math.cos(mean_lat)
    return math.hypot(dlat, dlng)


def _mock_landmark(lat: float, lng: float) -> str:
    """좌표를 시드로 항상 동일한 랜드마크를 고른다(새로고침해도 동일)."""
    seed = (int(round(lat * 1e5)) * 73856093) ^ (int(round(lng * 1e5)) * 19349663)
    return _KID_LANDMARKS[seed % len(_KID_LANDMARKS)]


def _naver_nearby(lat: float, lng: float) -> Optional[str]:
    """네이버 지역검색으로 좌표에 가장 가까운 랜드마크 종류를 찾는다."""
    if not (settings.naver_search_client_id and settings.naver_search_client_secret):
        return None

    headers = {
        "X-Naver-Client-Id": settings.naver_search_client_id,
        "X-Naver-Client-Secret": settings.naver_search_client_secret,
    }
    best_keyword: Optional[str] = None
    best_dist = _MAX_LANDMARK_DISTANCE_M
    for keyword in _SEARCH_KEYWORDS:
        try:
            resp = requests.get(
                _NAVER_LOCAL_URL,
                params={"query": keyword, "display": 5, "sort": "random"},
                headers=headers,
                timeout=6,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                try:
                    # 지역검색 mapx/mapy는 WGS84 경위도 * 1e7 정수
                    it_lng = float(item["mapx"]) / 1e7
                    it_lat = float(item["mapy"]) / 1e7
                except (KeyError, ValueError):
                    continue
                dist = _rough_distance_m(lat, lng, it_lat, it_lng)
                if dist < best_dist:
                    best_dist = dist
                    best_keyword = keyword
        except Exception:
            continue
    return best_keyword


@lru_cache(maxsize=1024)
def _landmark_cached(lat_r: float, lng_r: float) -> str:
    via_naver = _naver_nearby(lat_r, lng_r)
    if via_naver:
        return via_naver
    return _mock_landmark(lat_r, lng_r)


def landmark_for(lat: float, lng: float) -> Optional[str]:
    """좌표 주변 대표 랜드마크 단어를 반환. 좌표를 약 11m 격자로 반올림해 캐시한다."""
    if lat is None or lng is None:
        return None
    return _landmark_cached(round(lat, 4), round(lng, 4))
