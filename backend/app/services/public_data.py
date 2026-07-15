"""공공데이터(어린이보호구역/CCTV, 교통사고다발지역, 범죄지수 근사치) 수집·정제.

data.go.kr의 실제 활용신청 승인 후 발급되는 Endpoint URL/서비스키는 데이터셋마다
다르고 계정별로 부여되므로, 정확한 Endpoint는 팀이 활용신청 승인 메일의 "상세설명"
문서에서 확인해 .env의 DATA_GO_KR_SERVICE_KEY와 아래 *_API_URL 상수를 채워야 한다.
확인된 응답 필드명(위도/경도/CCTV설치대수 등)은 PROJECT_PLAN.md 3장 조사 결과를 그대로 반영했다.

서비스키가 없으면 자동으로 backend/app/data/sample_*.json 샘플 데이터를 사용해
동일한 파이프라인(수집 -> 정제 -> SQLite 적재)을 오프라인으로 시연할 수 있다.
"""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from typing import Any

import requests

from .. import db
from ..config import settings

# TODO(데이터 담당): data.go.kr에서 아래 데이터셋에 "활용신청" 후 발급되는 실제
# 요청주소(Endpoint URL)로 교체할 것. 서비스키는 .env의 DATA_GO_KR_SERVICE_KEY 그대로 사용 가능
# (data.go.kr은 계정당 서비스키 1개로 승인된 모든 데이터셋을 호출할 수 있음).
#   - 어린이보호구역: https://www.data.go.kr/data/15012891/openapi.do (전국어린이보호구역표준데이터)
#   - 교통사고다발지역: https://www.data.go.kr/data/15070586/openapi.do (한국도로교통공단 교통사고다발지역정보)
#   - 아동안전지킴이집: https://api.data.go.kr/openapi/tn_pubr_public_female_safety_prtchouse_api (전국안심지킴이집표준데이터)
#   - 보안등: https://api.data.go.kr/openapi/tn_pubr_public_scrty_lmp_api (전국보안등정보표준데이터)
#   - 무인교통단속카메라: https://api.data.go.kr/openapi/tn_pubr_public_unmanned_traffic_camera_api (전국무인교통단속카메라표준데이터)
CHILD_ZONE_API_URL = "https://api.odcloud.kr/api/15012891/v1/uddi:child-protection-zone"
ACCIDENT_HOTSPOT_API_URL = "https://apis.data.go.kr/1220000/EasyTrafficAccidentAreaService/getRestTrafficAccidentAreaList"
# 아래 3개는 "표준데이터 개방 표준 API"(api.data.go.kr/openapi/tn_pubr_public_*_api) 방식으로,
# 요청 파라미터가 pageNo/numOfRows/type=json이고 응답이 response.body.items로 감싸져 있다
# (odcloud.kr의 page/perPage/data 방식과 다름 — fetch_* 함수에서 별도 처리).
GUARDIAN_HOUSE_API_URL = "https://api.data.go.kr/openapi/tn_pubr_public_female_safety_prtchouse_api"
STREETLIGHT_API_URL = "https://api.data.go.kr/openapi/tn_pubr_public_scrty_lmp_api"
SPEED_CAMERA_API_URL = "https://api.data.go.kr/openapi/tn_pubr_public_unmanned_traffic_camera_api"


def _to_float(value: Any) -> float | None:
    """실제 공공데이터는 위도/경도가 비어있거나 공백 문자열인 레코드가 섞여 있는 경우가
    흔하므로, 변환 실패 시 예외를 던지지 않고 None을 반환해 해당 레코드만 건너뛸 수 있게 한다."""
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_sample(filename: str) -> list[dict[str, Any]]:
    path = settings.data_dir / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_gangnam_cctvs() -> list[dict[str, Any]]:
    """사용자가 제공한 강남구 CCTV CSV를 지도 마커용 좌표 목록으로 읽는다."""

    path = settings.data_dir / "cctv_gangnam.csv"
    if not path.exists():
        return []

    cctvs: list[dict[str, Any]] = []
    with open(path, "r", encoding="cp949", newline="") as f:
        for row in csv.DictReader(f):
            lat = _to_float(row.get("WGS84위도"))
            lng = _to_float(row.get("WGS84경도"))
            if lat is None or lng is None:
                continue
            cctvs.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "address": row.get("소재지도로명주소") or row.get("소재지지번주소") or "강남구 CCTV",
                    "purpose": row.get("설치목적구분") or "CCTV",
                    "camera_count": int(row.get("카메라대수") or 1),
                }
            )
    return cctvs


def _fetch_standard_api_items(url: str, num_of_rows: int = 1000) -> list[dict[str, Any]]:
    """data.go.kr "표준데이터 개방 표준 API"(tn_pubr_public_*_api) 공통 호출.
    응답은 보통 {"response": {"body": {"items": [...]}}} 형태로 감싸져 있다.
    numOfRows는 1000을 넘기면 INVALID_REQUEST_PARAMETER_ERROR(resultCode 10)가 나는
    데이터셋이 있어 1000으로 고정한다(전국 단위라 totalCount가 수십만~수백만 건이라도
    페이지당 최대 1000건까지만 받아 데모용 부분 데이터로 사용)."""
    resp = requests.get(
        url,
        params={
            "serviceKey": settings.data_go_kr_service_key,
            "pageNo": 1,
            "numOfRows": min(num_of_rows, 1000),
            "type": "json",
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    header = data.get("response", {}).get("header", {})
    if header and header.get("resultCode") not in (None, "00", "0"):
        raise RuntimeError(f"data.go.kr API error: {header.get('resultCode')} {header.get('resultMsg')}")
    items = data.get("response", {}).get("body", {}).get("items", None)
    if items is None:
        # 일부 데이터셋은 감싸지 않은 형태로 응답하는 경우도 있어 방어적으로 처리
        items = data.get("items", data.get("data", []))
    if isinstance(items, dict):
        # items가 단일 객체(레코드 1건)로 오는 경우도 있음
        items = [items]
    return items or []


def fetch_child_zones() -> tuple[list[dict[str, Any]], bool]:
    """(레코드 목록, mock 여부)를 반환."""
    if settings.public_data_mock:
        return _load_sample("sample_child_zones.json"), True

    try:
        resp = requests.get(
            CHILD_ZONE_API_URL,
            params={"serviceKey": settings.data_go_kr_service_key, "page": 1, "perPage": 1000, "returnType": "JSON"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        records = data.get("data", data.get("items", []))
        return records, False
    except Exception:
        # 네트워크/승인 이슈 시 샘플로 안전하게 폴백 (데모 안정성 우선)
        return _load_sample("sample_child_zones.json"), True


def fetch_accident_hotspots() -> tuple[list[dict[str, Any]], bool]:
    if settings.public_data_mock:
        return _load_sample("sample_accident_hotspots.json"), True

    try:
        resp = requests.get(
            ACCIDENT_HOTSPOT_API_URL,
            params={"serviceKey": settings.data_go_kr_service_key, "numOfRows": 1000, "pageNo": 1, "type": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", data.get("StanReginCd", []))
        return items, False
    except Exception:
        return _load_sample("sample_accident_hotspots.json"), True


def fetch_guardian_houses() -> tuple[list[dict[str, Any]], bool]:
    """아동안전지킴이집(편의점/약국 등 위험 시 대피 가능한 지정 안전장소)."""
    if settings.public_data_mock:
        return _load_sample("sample_guardian_houses.json"), True

    try:
        return _fetch_standard_api_items(GUARDIAN_HOUSE_API_URL), False
    except Exception:
        return _load_sample("sample_guardian_houses.json"), True


def fetch_streetlights() -> tuple[list[dict[str, Any]], bool]:
    """보안등/가로등 설치 현황 — 야간 통학로의 조도(가시성) 근사 지표로 사용."""
    if settings.public_data_mock:
        return _load_sample("sample_streetlights.json"), True

    try:
        return _fetch_standard_api_items(STREETLIGHT_API_URL, num_of_rows=2000), False
    except Exception:
        return _load_sample("sample_streetlights.json"), True


def fetch_speed_cameras() -> tuple[list[dict[str, Any]], bool]:
    """무인 교통단속카메라 — 스쿨존 주변 설치 시 차량 감속 유도 효과의 근사 지표로 사용."""
    if settings.public_data_mock:
        return _load_sample("sample_speed_cameras.json"), True

    try:
        return _fetch_standard_api_items(SPEED_CAMERA_API_URL), False
    except Exception:
        return _load_sample("sample_speed_cameras.json"), True


def fetch_crime_grid() -> tuple[list[dict[str, Any]], bool]:
    """safemap.go.kr 범죄주의구간은 WMS(이미지) 위주라 좌표-등급 조인이 복잡하므로,
    MVP에서는 행정동 단위 근사 그리드로 단순화한다(향후 정밀화 로드맵 대상)."""
    return _load_sample("sample_crime_grid.json"), True


def ingest_all() -> dict[str, Any]:
    """공공데이터를 수집해 정제 후 SQLite에 적재한다. (배치 잡: scripts/ingest_public_data.py)"""
    db.init_db()

    child_zones, child_mock = fetch_child_zones()
    hotspots, hotspot_mock = fetch_accident_hotspots()
    crime_grid, crime_mock = fetch_crime_grid()
    guardian_houses, guardian_mock = fetch_guardian_houses()
    streetlights, streetlight_mock = fetch_streetlights()
    speed_cameras, speed_camera_mock = fetch_speed_cameras()

    db.clear_table("child_zones")
    db.clear_table("accident_hotspots")
    db.clear_table("crime_grid")
    db.clear_table("guardian_houses")
    db.clear_table("streetlights")
    db.clear_table("speed_cameras")

    skipped: dict[str, int] = {}

    with db.session() as conn:
        for rec in child_zones:
            lat, lng = _to_float(rec.get("위도") or rec.get("lat")), _to_float(rec.get("경도") or rec.get("lng"))
            if lat is None or lng is None:
                skipped["child_zones"] = skipped.get("child_zones", 0) + 1
                continue
            db.insert_child_zone(
                conn,
                name=rec.get("대상시설명") or rec.get("name"),
                lat=lat,
                lng=lng,
                cctv_count=int(rec.get("CCTV설치대수") or rec.get("cctv_count") or 0),
                managing_org=rec.get("관리기관명"),
                police_office=rec.get("관할경찰서명"),
                source=rec.get("출처", "data.go.kr_전국어린이보호구역표준데이터"),
            )
        for rec in hotspots:
            lat, lng = _to_float(rec.get("위도") or rec.get("lat")), _to_float(rec.get("경도") or rec.get("lng"))
            if lat is None or lng is None:
                skipped["accident_hotspots"] = skipped.get("accident_hotspots", 0) + 1
                continue
            db.insert_accident_hotspot(
                conn,
                spot_id=rec.get("다발지역ID") or rec.get("spot_id"),
                name=rec.get("지점명") or rec.get("name"),
                lat=lat,
                lng=lng,
                occurrence_count=int(rec.get("발생건수") or rec.get("occurrence_count") or 0),
                casualty_count=int(rec.get("사상자수") or 0),
                fatality_count=int(rec.get("사망자수") or 0),
                source=rec.get("출처", "data.go.kr_한국도로교통공단_교통사고다발지역"),
            )
        for rec in crime_grid:
            db.insert_crime_grid(
                conn,
                grid_key=rec["grid_key"],
                lat_center=rec["lat_center"],
                lng_center=rec["lng_center"],
                region_name=rec.get("region_name"),
                risk_index=float(rec.get("risk_index", 0)),
                source=rec.get("출처", "safemap.go.kr_생활안전지도"),
            )
        for rec in guardian_houses:
            lat = _to_float(rec.get("latitude") or rec.get("위도") or rec.get("lat"))
            lng = _to_float(rec.get("longitude") or rec.get("경도") or rec.get("lng"))
            if lat is None or lng is None:
                skipped["guardian_houses"] = skipped.get("guardian_houses", 0) + 1
                continue
            db.insert_guardian_house(
                conn,
                # "전국안심지킴이집표준데이터"(data.go.kr ID 15034535) 실제 응답 필드명은
                # 로마자 표기(storNm, latitude, longitude, phoneNumber, cmptncPolcsttnNm 등)이다.
                # 시설명/업종/연락처는 샘플(sample_guardian_houses.json)용 한글 필드명이라 함께 폴백한다.
                name=rec.get("storNm") or rec.get("점포명") or rec.get("시설명") or rec.get("name"),
                category=rec.get("cmptncPolcsttnNm") or rec.get("업종") or rec.get("category"),
                lat=lat,
                lng=lng,
                contact=rec.get("phoneNumber") or rec.get("여성안심지킴이집전화번호") or rec.get("연락처") or rec.get("contact"),
                source=rec.get("출처", "data.go.kr_전국안심지킴이집표준데이터"),
            )
        for rec in streetlights:
            lat = _to_float(rec.get("latitude") or rec.get("위도") or rec.get("lat"))
            lng = _to_float(rec.get("longitude") or rec.get("경도") or rec.get("lng"))
            if lat is None or lng is None:
                skipped["streetlights"] = skipped.get("streetlights", 0) + 1
                continue
            db.insert_streetlight(
                conn,
                # "전국보안등정보표준데이터"(data.go.kr ID 15017320) 실제 응답 필드명: lmpLcNm(보안등위치명)/installationType(설치형태).
                facility_id=rec.get("lmpLcNm") or rec.get("보안등위치명") or rec.get("관리번호") or rec.get("facility_id"),
                lat=lat,
                lng=lng,
                light_type=rec.get("installationType") or rec.get("설치형태") or rec.get("등종류") or rec.get("light_type"),
                source=rec.get("출처", "data.go.kr_전국보안등정보표준데이터"),
            )
        for rec in speed_cameras:
            lat = _to_float(rec.get("latitude") or rec.get("위도") or rec.get("lat"))
            lng = _to_float(rec.get("longitude") or rec.get("경도") or rec.get("lng"))
            if lat is None or lng is None:
                skipped["speed_cameras"] = skipped.get("speed_cameras", 0) + 1
                continue
            db.insert_speed_camera(
                conn,
                # "전국무인교통단속카메라표준데이터"(data.go.kr ID 15028200) 실제 응답 필드명:
                # mnlssRegltCameraManageNo(관리번호)/itlpc(설치장소)/lmttVe(제한속도, km/h).
                facility_id=rec.get("mnlssRegltCameraManageNo") or rec.get("무인교통단속카메라관리번호") or rec.get("관리번호") or rec.get("facility_id"),
                name=rec.get("itlpc") or rec.get("설치장소") or rec.get("name"),
                lat=lat,
                lng=lng,
                speed_limit_kmh=int(rec.get("lmttVe") or rec.get("제한속도") or rec.get("speed_limit_kmh") or 0) or None,
                source=rec.get("출처", "data.go.kr_전국무인교통단속카메라표준데이터"),
            )

    return {
        "child_zones": {"count": len(child_zones) - skipped.get("child_zones", 0), "mock": child_mock, "skipped": skipped.get("child_zones", 0)},
        "accident_hotspots": {"count": len(hotspots) - skipped.get("accident_hotspots", 0), "mock": hotspot_mock, "skipped": skipped.get("accident_hotspots", 0)},
        "crime_grid": {"count": len(crime_grid), "mock": crime_mock},
        "guardian_houses": {"count": len(guardian_houses) - skipped.get("guardian_houses", 0), "mock": guardian_mock, "skipped": skipped.get("guardian_houses", 0)},
        "streetlights": {"count": len(streetlights) - skipped.get("streetlights", 0), "mock": streetlight_mock, "skipped": skipped.get("streetlights", 0)},
        "speed_cameras": {"count": len(speed_cameras) - skipped.get("speed_cameras", 0), "mock": speed_camera_mock, "skipped": skipped.get("speed_cameras", 0)},
    }


def get_child_zones() -> list[dict[str, Any]]:
    return [dict(r) for r in db.fetch_all("child_zones")]


def get_accident_hotspots() -> list[dict[str, Any]]:
    return [dict(r) for r in db.fetch_all("accident_hotspots")]


def get_crime_grid() -> list[dict[str, Any]]:
    return [dict(r) for r in db.fetch_all("crime_grid")]


def get_guardian_houses() -> list[dict[str, Any]]:
    return [dict(r) for r in db.fetch_all("guardian_houses")]


def get_streetlights() -> list[dict[str, Any]]:
    return [dict(r) for r in db.fetch_all("streetlights")]


def get_speed_cameras() -> list[dict[str, Any]]:
    return [dict(r) for r in db.fetch_all("speed_cameras")]


def get_doc_risk_points() -> list[dict[str, Any]]:
    return [dict(r) for r in db.fetch_all("doc_risk_points")]


def crime_risk_for_point(lat: float, lng: float, grid: list[dict[str, Any]] | None = None) -> float:
    """가장 가까운 그리드 셀의 risk_index를 근사치로 사용 (행정동 단위 정밀도 제약 반영)."""
    import numpy as np

    from .geo import haversine_m

    cells = grid if grid is not None else get_crime_grid()
    if not cells:
        return 0.0

    dists = [
        float(haversine_m(np.array([lat]), np.array([lng]), np.array([c["lat_center"]]), np.array([c["lng_center"]]))[0])
        for c in cells
    ]
    nearest = cells[dists.index(min(dists))]
    return float(nearest["risk_index"])
