"""서울시 안심귀갓길 안전시설물 CSV 로더.

CSV 컬럼:
  - 포인트 wkt: POINT(경도 위도) WGS84
  - 시설코드: 301 안심벨, 302 CCTV, 305 보안등, 307 112신고 등
  - 시군구명, 읍면동명

data/ 폴더(또는 backend/app/data/)에 CSV를 두면 전국(서울) 시설을 읽어
경로 주변 30~50m 버퍼 매칭·안전점수·지도 마커에 사용한다.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import settings

# 시설코드 → 내부 타입 (지도·점수 공통)
FACILITY_CODE_MAP: dict[int, str] = {
    301: "safety_bell",
    302: "cctv",
    305: "streetlight",
    307: "emergency112",
}

FACILITY_LABELS: dict[str, str] = {
    "safety_bell": "안심벨",
    "cctv": "CCTV",
    "streetlight": "보안등",
    "emergency112": "112신고",
}

_WKT_RE = re.compile(
    r"POINT\s*\(?\s*([-\d.]+)\s+([-\d.]+)\s*\)?",
    re.IGNORECASE,
)

_CSV_CANDIDATE_NAMES = (
    "서울시 안심귀갓길 안전시설물.csv",
    "안심귀갓길_안전시설물.csv",
    "safety_facilities.csv",
)


def _csv_search_paths() -> list[Path]:
    """사용자가 넣은 data/ 와 backend/app/data/ 모두 탐색."""
    roots = [settings.repo_data_dir, settings.data_dir]
    seen: set[Path] = set()
    paths: list[Path] = []
    for root in roots:
        for name in _CSV_CANDIDATE_NAMES:
            p = root / name
            if p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


def parse_wkt_point(wkt: str) -> tuple[float, float] | None:
    """POINT(경도 위도) → (lat, lng). WGS84 그대로 네이버/Leaflet에 사용."""
    if not wkt:
        return None
    m = _WKT_RE.search(wkt.strip())
    if not m:
        return None
    lng, lat = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _resolve_csv_path() -> Path | None:
    for path in _csv_search_paths():
        if path.exists():
            return path
    return None


def _open_csv(path: Path):
    """UTF-8 또는 Windows CP949로 저장된 CSV를 연다."""
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            f = open(path, "r", encoding=encoding, newline="")
            f.read(4096)
            f.seek(0)
            return f
        except UnicodeDecodeError:
            continue
    return open(path, "r", encoding="utf-8-sig", errors="replace", newline="")


@lru_cache(maxsize=1)
def load_safety_facilities() -> list[dict[str, Any]]:
    path = _resolve_csv_path()
    if path is None:
        return []

    facilities: list[dict[str, Any]] = []
    with _open_csv(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            wkt = row.get("포인트 wkt") or row.get("포인트WKT") or ""
            coords = parse_wkt_point(wkt)
            if coords is None:
                continue

            try:
                code = int(str(row.get("시설코드", "")).strip())
            except ValueError:
                continue

            facility_type = FACILITY_CODE_MAP.get(code)
            if facility_type is None:
                continue

            lat, lng = coords
            try:
                install_count = max(1, int(row.get("설치대수") or 1))
            except (TypeError, ValueError):
                install_count = 1

            facilities.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "facility_type": facility_type,
                    "facility_code": code,
                    "label": FACILITY_LABELS.get(facility_type, facility_type),
                    "district": (row.get("시군구명") or "").strip(),
                    "dong": (row.get("읍면동명") or "").strip(),
                    "route_name": (row.get("안심귀갓길 명") or "").strip(),
                    "install_count": install_count,
                    "note": (row.get("비고") or "").strip(),
                }
            )
    return facilities


def get_safety_facilities() -> list[dict[str, Any]]:
    return load_safety_facilities()


def facilities_in_bbox(
    facilities: list[dict[str, Any]],
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
) -> list[dict[str, Any]]:
    """경로 주변만 점수 계산에 쓰도록 대략적 bbox로 1차 필터."""
    return [
        f
        for f in facilities
        if min_lat <= f["lat"] <= max_lat and min_lng <= f["lng"] <= max_lng
    ]
