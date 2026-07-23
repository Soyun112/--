"""API 요청/응답 스키마."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class LatLng(BaseModel):
    lat: float
    lng: float


class Waypoint(BaseModel):
    """좌표(lat/lng) 또는 이름(query)을 받는다. query만 있으면 서버가 지오코딩한다."""

    lat: Optional[float] = None
    lng: Optional[float] = None
    name: Optional[str] = None
    query: Optional[str] = Field(default=None, description="건물명/역이름/주소 (좌표 없을 때 지오코딩)")


class RouteRequest(BaseModel):
    origin: Waypoint
    destination: Waypoint
    audience_age: int = Field(default=8, ge=3, le=15, description="아이용 설명 난이도 조정을 위한 나이")
    mock: Optional[bool] = Field(default=None, description="지정 시 서버 기본 MOCK 설정을 덮어씀")
    force_night: Optional[bool] = Field(
        default=None,
        description="True면 실제 시각과 무관하게 야간 가중치·배너로 채점",
    )


class GeocodeResponse(BaseModel):
    query: str
    lat: float
    lng: float
    label: str
    source: str


class DocMatch(BaseModel):
    source_doc: str
    page: Optional[int] = None
    snippet: str
    risk_type: str
    is_risk: bool
    distance_m: float
    lat: float
    lng: float


class SafetyFeatures(BaseModel):
    distance_km: float
    cctv_count: int  # 표시용: 보호구역 CCTV + 안심 302
    cctv_density: float  # 안심 302 폴 / km (점수 cctv_density)
    child_zone_coverage_pct: float  # 거리감쇠 평균 × 100
    accident_hotspot_count: int
    crime_risk_proxy: float
    guardian_house_count: int = 0
    streetlight_count: int = 0
    streetlight_density: float = 0.0
    speed_camera_count: int = 0
    doc_risk_count: int
    doc_safety_count: int
    matched_documents: List[DocMatch] = []
    # 안심귀갓길 CSV — 경로 주변(40m) 시설물 개수 (폴 단위)
    safety_facility_cctv_count: int = 0
    safety_facility_streetlight_count: int = 0
    safety_bell_count: int = 0
    emergency112_count: int = 0
    # 301∪307 폴 수 (점수 emergency_density용)
    emergency_pole_count: int = 0
    # 매칭된 보호구역이 보유한 CCTV 총합 (경로 길이로 나누지 않음)
    zone_cctv_count: int = 0


class StampOut(BaseModel):
    id: str
    emoji: str
    label: str
    description: str
    count: int = 1


class NavigationStep(BaseModel):
    """경로 제공자가 반환한 보행 안내 한 단계."""

    description: str
    turn_type: Optional[int] = None
    distance_m: float = 0.0
    landmark: Optional[str] = None


class RouteCandidate(BaseModel):
    id: str
    coordinates: List[LatLng]
    distance_m: float
    duration_s: float
    features: SafetyFeatures
    safety_score: float
    is_recommended: bool = False
    source: str
    stamps: List[StampOut] = []
    star_rating: int = 1
    navigation_steps: List[NavigationStep] = []
    # 경로길이 ÷ 직선거리. 2.5 초과면 access_warning 표시
    detour_ratio: Optional[float] = None
    access_warning: Optional[str] = None


class TimeContext(BaseModel):
    """현재 시각·낮/밤·도착 예상·시간대별 추천 안내."""

    current_time: str
    is_night: bool
    period_label: str
    period_emoji: str = "☀️"
    recommendation_message: str
    scoring_context: str
    sunset_time: str
    night_start_time: str
    night_end_time: str = "오전 6:00"
    arrival_time: Optional[str] = None
    eta_message: Optional[str] = None
    duration_minutes: Optional[int] = None


class RouteResponse(BaseModel):
    origin: Waypoint
    destination: Waypoint
    candidates: List[RouteCandidate]
    recommended_id: str
    parent_report: str
    parent_report_v2: str = ""  # 비교용: 좋은점·우회 2그룹만 반영
    kid_report: str
    used_mock: dict
    weather: Optional[dict] = None
    time_context: Optional[TimeContext] = None


class DocumentIngestResult(BaseModel):
    document_name: str
    extracted: dict
    risk_points_created: int
    used_mock: bool
    risk_points_skipped: int = 0


class DocumentPointConfirmRequest(BaseModel):
    location_text: str = ""
    geocode_query: str
    risk_type: str = ""
    is_risk: bool = True
    snippet: str = ""
    source_doc: str = ""
    page: Optional[int] = None
    report_date: Optional[str] = None
    recommendation: Optional[str] = None


class DocumentPointConfirmResult(BaseModel):
    id: int
    lat: float
    lng: float
    risk_type: str
    is_estimated: bool = False
    source_doc: str = ""
    geocode_query: str = ""


class ChildZonePoint(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    cctv_count: int = 0


class AccidentHotspotPoint(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    occurrence_count: int = 0


class GuardianHousePoint(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    category: Optional[str] = None


class StreetlightPoint(BaseModel):
    lat: float
    lng: float
    light_type: Optional[str] = None


class SpeedCameraPoint(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    speed_limit_kmh: Optional[int] = None


class CctvPoint(BaseModel):
    lat: float
    lng: float
    address: Optional[str] = None
    purpose: Optional[str] = None
    camera_count: int = 1


class SafetyFacilityPoint(BaseModel):
    """서울시 안심귀갓길 안전시설물 (WKT POINT + 시설코드)."""

    lat: float
    lng: float
    facility_type: str  # cctv | streetlight | safety_bell | emergency112
    facility_code: int
    label: str
    district: Optional[str] = None
    dong: Optional[str] = None
    route_name: Optional[str] = None
    install_count: int = 1
    note: Optional[str] = None


class DocumentRiskPoint(BaseModel):
    id: int
    lat: float
    lng: float
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None
    location_text: Optional[str] = None
    geocode_query: Optional[str] = None
    end_geocode_query: Optional[str] = None
    matched_label: Optional[str] = None
    risk_type: str
    is_risk: bool
    snippet: str
    source_doc: str
    page: Optional[int] = None
    report_date: Optional[str] = None
    recommendation: Optional[str] = None
    is_estimated: bool = False
    polyline: Optional[List[LatLng]] = None
    header_road: Optional[str] = None
    verify_status: Optional[str] = None


class PublicDataResponse(BaseModel):
    child_zones: List[ChildZonePoint]
    accident_hotspots: List[AccidentHotspotPoint]
    doc_risk_points: List[DocumentRiskPoint]
    guardian_houses: List[GuardianHousePoint] = []
    streetlights: List[StreetlightPoint] = []
    speed_cameras: List[SpeedCameraPoint] = []
    cctvs: List[CctvPoint] = []
    safety_facilities: List[SafetyFacilityPoint] = []
