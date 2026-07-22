"""문서 위험 구간: 시점→종점 pedestrian 폴리라인 + 도로명 검증 + 캐시.

실패 시 직선을 그리지 않는다. 429면 해당 구간만 건너뛴다.
캐시 키: (문서 해시 + 구간 인덱스).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from ..config import settings
from ..console_safe import safe_print
from .geo import haversine_m
from .routing import _coords_from_tmap_features, _fetch_tmap_pedestrian_data

# 강남구 대략 bbox
_GANGNAM_BBOX = {"lat_min": 37.455, "lat_max": 37.535, "lng_min": 126.995, "lng_max": 127.125}
_MIN_SEG_M = 30.0
_MAX_SEG_M = 2000.0


def document_content_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes or b"").hexdigest()[:24]


def _cache_path(doc_hash: str, segment_index: int) -> Path:
    base = Path(settings.data_dir) / "cache" / "doc_segments"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{doc_hash}_{segment_index}.json"


def load_segment_cache(doc_hash: str, segment_index: int) -> dict[str, Any] | None:
    path = _cache_path(doc_hash, segment_index)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_segment_cache(doc_hash: str, segment_index: int, payload: dict[str, Any]) -> None:
    path = _cache_path(doc_hash, segment_index)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _in_gangnam(lat: float, lng: float) -> bool:
    b = _GANGNAM_BBOX
    return b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]


def straight_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(
        haversine_m(np.array([a[0]]), np.array([a[1]]), np.array([b[0]]), np.array([b[1]]))[0]
    )


def _normalize_road_token(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().lower())


def _header_in_route_names(header_road: str, route_names: list[str]) -> bool:
    """Tmap 구간 name에 헤더 도로명이 포함되는지."""
    target = _normalize_road_token(header_road)
    if not target:
        return False
    # 논현로76길 ↔ 논현로 76길
    variants = {target}
    # 길 없는 본선만 헤더인 경우(선릉로) — 부분 일치
    for n in route_names:
        nn = _normalize_road_token(n)
        if not nn or nn in ("보행자도로", "단지내도로", ""):
            continue
        if target in nn or nn in target:
            return True
        # 테헤란로108길 vs 테헤란로
        if target.startswith(nn) or nn.startswith(target[: max(2, len(target) // 2)]):
            # 너무 느슨하지 않게: 공통 base '로' 단위
            m = re.match(r"(.+로)", target)
            base = m.group(1) if m else target
            if base and base in nn:
                return True
    return False


def _extract_route_names(features: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for f in features or []:
        props = f.get("properties") or {}
        name = props.get("name") or ""
        if not isinstance(name, str) or not name.strip():
            continue
        token = name.strip().split()[0]
        if token in ("보행자도로", "단지내도로", "사이로", "목적지"):
            continue
        # 도로명만 (숫자m, 건물명 제외)
        if re.search(r"(로|길|대로)$", token) or re.search(r"(로|길|대로)\d", token):
            names.append(token)
    return names


def resolve_segment_polyline(
    *,
    start: tuple[float, float],
    end: tuple[float, float],
    header_road: str,
    doc_hash: str,
    segment_index: int,
    start_road: str = "",
    end_road: str = "",
) -> dict[str, Any]:
    """시점→종점 pedestrian. 검증 실패·API 실패 시 verified=False, polyline 없음.

    직선 폴백 없음. 헤더 도로가 끝점과 다르면 헤더 경유 via를 한 번 시도.
    """
    cached = load_segment_cache(doc_hash, segment_index)
    if cached is not None:
        safe_print(f"[문서구간] 캐시 히트 doc={doc_hash} idx={segment_index}")
        return cached

    result: dict[str, Any] = {
        "verified": False,
        "reason": "",
        "polyline": None,
        "route_names": [],
        "distance_m": None,
        "header_road": header_road,
    }

    if not (_in_gangnam(*start) and _in_gangnam(*end)):
        result["reason"] = "강남구 bbox 밖"
        save_segment_cache(doc_hash, segment_index, result)
        return result

    dist = straight_distance_m(start, end)
    result["distance_m"] = round(dist, 1)
    if dist < _MIN_SEG_M or dist > _MAX_SEG_M:
        result["reason"] = f"직선거리 이상 ({dist:.0f}m, 허용 {_MIN_SEG_M:.0f}~{_MAX_SEG_M:.0f})"
        save_segment_cache(doc_hash, segment_index, result)
        return result

    pass_list: str | None = None
    header_n = _normalize_road_token(header_road)
    start_n = _normalize_road_token(start_road)
    end_n = _normalize_road_token(end_road)
    # 헤더가 끝점 도로와 다르면(③ 논현로57길 vs 도곡로) 헤더 도로 경유 시도
    if header_n and header_n not in {start_n, end_n}:
        try:
            from .geocoding import geocode_document_address

            via_hit = geocode_document_address(f"서울특별시 강남구 {header_road}")
            if via_hit and _in_gangnam(via_hit.lat, via_hit.lng):
                d_start = straight_distance_m(start, (via_hit.lat, via_hit.lng))
                d_end = straight_distance_m(end, (via_hit.lat, via_hit.lng))
                if d_start < 800 and d_end < 800:
                    pass_list = f"{via_hit.lng},{via_hit.lat}"
                    safe_print(
                        f"[문서구간] 헤더 via 사용 idx={segment_index} "
                        f"{header_road} ({via_hit.lat:.5f},{via_hit.lng:.5f})"
                    )
        except Exception as exc:
            safe_print(f"[문서구간] 헤더 via 실패: {exc}")

    try:
        data = _fetch_tmap_pedestrian_data(
            start, end, search_option="4", pass_list=pass_list
        )
    except Exception as exc:
        result["reason"] = f"pedestrian 실패: {type(exc).__name__}"
        safe_print(f"[문서구간] pedestrian 실패 idx={segment_index}: {exc}")
        if "429" not in str(exc):
            save_segment_cache(doc_hash, segment_index, result)
        return result

    if not data:
        result["reason"] = "pedestrian 빈 응답"
        save_segment_cache(doc_hash, segment_index, result)
        return result

    features = data.get("features") or []
    coords, total_distance, _, _ = _coords_from_tmap_features(features, search_option="4")
    names = _extract_route_names(features)
    result["route_names"] = names

    if len(coords) < 2:
        result["reason"] = "좌표 부족"
        save_segment_cache(doc_hash, segment_index, result)
        return result

    header_ok = _header_in_route_names(header_road, names)
    # 끝점이 같은 본선(도곡로~도곡로)이고 그 도로가 경로에 있으면 보조 통과
    endpoint_ok = False
    if start_road and end_road:
        sb = re.match(r"(.+로)", _normalize_road_token(start_road))
        eb = re.match(r"(.+로)", _normalize_road_token(end_road))
        if sb and eb and sb.group(1) == eb.group(1):
            endpoint_ok = _header_in_route_names(sb.group(1), names)

    if not header_ok and not endpoint_ok:
        result["reason"] = f"헤더 도로명 불일치 (기대={header_road}, 경로={names[:8]})"
        save_segment_cache(doc_hash, segment_index, result)
        return result

    result["verified"] = True
    result["reason"] = "ok" if header_ok else "ok_endpoint_roads"
    result["polyline"] = [{"lat": lat, "lng": lng} for lat, lng in coords]
    result["route_distance_m"] = round(float(total_distance or 0), 1)
    save_segment_cache(doc_hash, segment_index, result)
    safe_print(
        f"[문서구간] 검증 통과 idx={segment_index} header={header_road} "
        f"pts={len(coords)} names={names[:5]} via={bool(pass_list)}"
    )
    return result
