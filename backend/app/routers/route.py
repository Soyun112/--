from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..models import (
    AccidentHotspotPoint,
    CctvPoint,
    ChildZonePoint,
    DocumentRiskPoint,
    GeocodeResponse,
    GuardianHousePoint,
    LatLng,
    NavigationStep,
    PublicDataResponse,
    RouteCandidate,
    RouteRequest,
    RouteResponse,
    SafetyFeatures,
    SafetyFacilityPoint,
    SpeedCameraPoint,
    StampOut,
    StreetlightPoint,
    TimeContext,
    Waypoint,
)
from ..services import gamification, geocoding, public_data, solar, weather
from ..console_safe import safe_print
from ..services.routing import (
    access_warning_for_ratio,
    detour_ratio_for_route,
    ensure_navigation_steps_for_coords,
    get_route_candidates,
)
from ..services.safety_facilities import get_safety_facilities
from ..services.scoring import score_candidates
from ..services.time_context import build_time_context, is_nighttime

router = APIRouter(prefix="/api", tags=["route"])


def _parse_doc_polyline(raw) -> list[LatLng] | None:
    if not raw:
        return None
    try:
        import json

        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, list) or len(data) < 2:
            return None
        out: list[LatLng] = []
        for p in data:
            if isinstance(p, dict) and "lat" in p and "lng" in p:
                out.append(LatLng(lat=float(p["lat"]), lng=float(p["lng"])))
        return out if len(out) >= 2 else None
    except Exception:
        return None


@router.get("/geocode", response_model=GeocodeResponse)
def geocode_place(q: str = Query(..., min_length=1, description="건물명/역이름/주소")) -> GeocodeResponse:
    """이름/주소를 좌표로 변환. 위경도 대신 이름으로 검색할 때 사용."""
    result = geocoding.geocode(q)
    if result is None:
        raise HTTPException(status_code=404, detail=f'"{q}" 위치를 찾지 못했습니다. 다른 이름이나 주소로 시도해보세요.')
    return GeocodeResponse(query=q, lat=result.lat, lng=result.lng, label=result.label, source=result.source)


def _resolve_waypoint(
    wp: Waypoint,
    role: str,
    *,
    near: tuple[float, float] | None = None,
) -> Waypoint:
    """좌표가 있으면 그대로, 없으면 query/name을 지오코딩해 좌표를 채운 Waypoint를 반환."""
    if wp.lat is not None and wp.lng is not None:
        return Waypoint(lat=wp.lat, lng=wp.lng, name=wp.name or wp.query)

    query = (wp.query or wp.name or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail=f"{role}: 좌표(lat/lng) 또는 이름(query)이 필요합니다.")

    result = geocoding.geocode(query, near=near)
    if result is None:
        raise HTTPException(status_code=404, detail=f'{role}: "{query}" 위치를 찾지 못했습니다.')
    return Waypoint(lat=result.lat, lng=result.lng, name=wp.name or result.label)


@router.get("/public-data", response_model=PublicDataResponse)
def get_public_data_layers() -> PublicDataResponse:
    """지도 위 STEP3 마커 시각화(CCTV/사고다발지역/문서기반 위험·안전지점)를 위한 원시 레이어."""
    return PublicDataResponse(
        child_zones=[
            ChildZonePoint(lat=z["lat"], lng=z["lng"], name=z.get("name"), cctv_count=z.get("cctv_count") or 0)
            for z in public_data.get_child_zones()
        ],
        accident_hotspots=[
            AccidentHotspotPoint(lat=h["lat"], lng=h["lng"], name=h.get("name"), occurrence_count=h.get("occurrence_count") or 0)
            for h in public_data.get_accident_hotspots()
        ],
        doc_risk_points=[
            DocumentRiskPoint(
                id=d["id"],
                lat=d["lat"],
                lng=d["lng"],
                end_lat=d.get("end_lat"),
                end_lng=d.get("end_lng"),
                location_text=d.get("location_text"),
                geocode_query=d.get("geocode_query"),
                end_geocode_query=d.get("end_geocode_query"),
                matched_label=d.get("matched_label"),
                risk_type=d.get("risk_type", ""),
                is_risk=bool(d.get("is_risk")),
                snippet=d.get("snippet", ""),
                source_doc=d.get("source_doc", ""),
                page=d.get("page"),
                report_date=d.get("report_date"),
                recommendation=d.get("recommendation"),
                is_estimated=bool(d.get("is_estimated")),
                polyline=_parse_doc_polyline(d.get("polyline_json")),
                header_road=d.get("header_road"),
                verify_status=d.get("verify_status"),
            )
            for d in public_data.get_doc_risk_points()
        ],
        guardian_houses=[
            GuardianHousePoint(lat=g["lat"], lng=g["lng"], name=g.get("name"), category=g.get("category"))
            for g in public_data.get_guardian_houses()
        ],
        streetlights=[
            StreetlightPoint(lat=s["lat"], lng=s["lng"], light_type=s.get("light_type"))
            for s in public_data.get_streetlights()
        ],
        speed_cameras=[
            SpeedCameraPoint(lat=c["lat"], lng=c["lng"], name=c.get("name"), speed_limit_kmh=c.get("speed_limit_kmh"))
            for c in public_data.get_speed_cameras()
        ],
        cctvs=[
            CctvPoint(
                lat=c["lat"],
                lng=c["lng"],
                address=c.get("address"),
                purpose=c.get("purpose"),
                camera_count=c.get("camera_count") or 1,
            )
            for c in public_data.get_gangnam_cctvs()
        ],
        safety_facilities=[
            SafetyFacilityPoint(
                lat=f["lat"],
                lng=f["lng"],
                facility_type=f["facility_type"],
                facility_code=f["facility_code"],
                label=f["label"],
                district=f.get("district"),
                dong=f.get("dong"),
                route_name=f.get("route_name"),
                install_count=f.get("install_count") or 1,
                note=f.get("note") or None,
            )
            for f in get_safety_facilities()
        ],
    )


@router.post("/route", response_model=RouteResponse)
def compute_route(req: RouteRequest) -> RouteResponse:
    origin = _resolve_waypoint(req.origin, "출발지")
    destination = _resolve_waypoint(
        req.destination,
        "목적지",
        near=(origin.lat, origin.lng),
    )

    origin_xy = (origin.lat, origin.lng)
    dest_xy = (destination.lat, destination.lng)

    routing_mock = settings.routing_mock if req.mock is None else req.mock
    safe_print(
        f"\n[API /route] 요청 - {origin.name or origin.lat} -> {destination.name or destination.lat} "
        f"(mock={routing_mock})"
    )

    raw_candidates = get_route_candidates(
        origin_xy,
        dest_xy,
        force_mock=req.mock,
        origin_name=origin.name or origin.query,
        destination_name=destination.name or destination.query,
    )
    if not raw_candidates:
        raise HTTPException(
            status_code=503,
            detail=(
                "Tmap 보행자 경로를 불러오지 못했습니다. "
                "API 호출 한도(429)에 걸렸을 수 있으니 1~2분 후 다시 시도해 주세요. "
                "Render에 TMAP_APP_KEY가 설정되어 있는지도 확인해 주세요."
            ),
        )
    if req.force_night is None:
        night = is_nighttime()
    else:
        night = bool(req.force_night)
    scored = score_candidates(raw_candidates, is_night=night)

    for s in scored:
        n = len(s.raw.navigation_steps)
        safe_print(f"[API /route] 후보 {s.raw.id}: navigation_steps {n}개 (source={s.raw.source})")
        if n == 0 and s.raw.source == "TMAP_PEDESTRIAN_API":
            safe_print(
                f"[API /route] 경고: {s.raw.id} Tmap 좌표는 {len(s.raw.coordinates)}개인데 "
                "상세 안내 0개 - 백엔드를 --reload로 재시작했는지 확인하세요"
            )

    candidates: list[RouteCandidate] = []
    origin_pt = (origin.lat, origin.lng)
    dest_pt = (destination.lat, destination.lng)
    for s in scored:
        raw_steps = s.raw.navigation_steps
        if not raw_steps and len(s.raw.coordinates) >= 2:
            raw_steps = ensure_navigation_steps_for_coords(s.raw.coordinates)
            safe_print(
                f"[API /route] {s.raw.id}: navigation_steps 비어 있음 "
                f"-> 좌표 기반 합성 {len(raw_steps)}단계"
            )

        ratio = round(detour_ratio_for_route(origin_pt, dest_pt, s.raw.distance_m), 2)
        candidates.append(
            RouteCandidate(
                id=s.raw.id,
                coordinates=[LatLng(lat=lat, lng=lng) for lat, lng in s.raw.coordinates],
                distance_m=round(s.raw.distance_m, 1),
                duration_s=round(s.raw.duration_s, 1),
                features=s.features,
                safety_score=s.safety_score,
                is_recommended=s.is_recommended,
                source=s.raw.source,
                stamps=[StampOut(**vars(stamp)) for stamp in gamification.compute_stamps(s.features)],
                star_rating=gamification.compute_star_rating(s.safety_score),
                navigation_steps=[
                    NavigationStep(
                        description=step.description,
                        turn_type=step.turn_type,
                        distance_m=round(step.distance_m, 1),
                        landmark=step.landmark,
                    )
                    for step in raw_steps
                ],
                detour_ratio=ratio,
                access_warning=access_warning_for_ratio(ratio),
            )
        )

    recommended = next(c for c in candidates if c.is_recommended)
    others = [c for c in candidates if c.id != recommended.id]

    # 목적지 실시간 날씨(있으면 Solar 설명에 "비 오는 날 통학로" 맥락으로 반영)
    current_weather = weather.fetch_weather(destination.lat, destination.lng)

    time_ctx_data = build_time_context(recommended.duration_s, force_night=req.force_night)
    time_context = TimeContext(**time_ctx_data)

    reports = solar.generate_reports(
        recommended, others, req.audience_age, weather=current_weather, time_context=time_ctx_data
    )

    return RouteResponse(
        origin=origin,
        destination=destination,
        candidates=candidates,
        recommended_id=recommended.id,
        parent_report=reports["parent_report"],
        parent_report_v2=reports.get("parent_report_v2") or "",
        kid_report=reports["kid_report"],
        used_mock={
            "routing": settings.routing_mock if req.mock is None else req.mock,
            "public_data": settings.public_data_mock,
            "upstage": reports["used_mock"],
        },
        weather=current_weather,
        time_context=time_context,
    )
