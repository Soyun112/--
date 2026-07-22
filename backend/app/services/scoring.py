"""경로 후보 안전점수 — 절대 스케일(포화 함수) + 주/야 가중치.

- 선형 인프라(CCTV·보안등·비상·지킴이집): per-km
- 점 사건(사고다발·문서위험·단속카메라): raw count
- min-max 상대 정규화 없음 (후보 1개여도 의미 있음)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from ..config import settings
from ..models import DocMatch, SafetyFeatures
from . import public_data
from .geo import buffer_match, min_distance_to_route, resample_route, route_length_m
from ..console_safe import safe_print
from .routing import RouteCandidateRaw
from .safety_facilities import (
    count_poles_near_route,
    facilities_in_bbox,
    get_safety_facilities,
    nearest_facility_distance_m,
)
from .time_context import is_nighttime, scoring_context_label, scoring_weights


@dataclass
class ScoredRoute:
    raw: RouteCandidateRaw
    features: SafetyFeatures
    safety_score: float = 0.0
    is_recommended: bool = False
    data_coverage: bool = True


def saturate(x: float, k: float) -> float:
    """s(x,k)=x/(x+k). k는 '절반 만족' 밀도/개수."""
    if k <= 0:
        return 1.0 if x > 0 else 0.0
    if x <= 0:
        return 0.0
    return float(x / (x + k))


def _child_zone_coverage_pct(resampled_points, child_zones: list[dict], radius_m: float) -> float:
    """거리 감쇠 커버리지: mean(max(0, 1 - dist/R)) × 100.

    교문 바로 앞(~1.0)과 300m 경계(~0)를 구분. 이진 통과율보다 변별력 있음.
    """
    if not resampled_points or not child_zones:
        return 0.0
    zone_points = [(z["lat"], z["lng"]) for z in child_zones]
    weights: list[float] = []
    for pt in resampled_points:
        dist = min(float(min_distance_to_route([pt], zp)) for zp in zone_points)
        weights.append(max(0.0, 1.0 - dist / radius_m))
    return 100.0 * float(np.mean(weights))


def _bbox_for_route(coords: list[tuple[float, float]], margin_deg: float = 0.004) -> tuple[float, float, float, float]:
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    return min(lats) - margin_deg, max(lats) + margin_deg, min(lngs) - margin_deg, max(lngs) + margin_deg


def _count_safety_facilities_near_route(
    resampled: list[tuple[float, float]],
    coords: list[tuple[float, float]],
) -> dict[str, int]:
    all_facilities = get_safety_facilities()
    empty = {
        "safety_facility_cctv_count": 0,
        "safety_facility_streetlight_count": 0,
        "safety_bell_count": 0,
        "emergency112_count": 0,
        "emergency_pole_count": 0,
    }
    if not all_facilities or not resampled:
        return empty
    min_lat, max_lat, min_lng, max_lng = _bbox_for_route(coords)
    nearby = facilities_in_bbox(all_facilities, min_lat, max_lat, min_lng, max_lng)
    if not nearby:
        return empty
    return count_poles_near_route(resampled, nearby, settings.safety_facility_buffer_m)


def compute_features(raw: RouteCandidateRaw) -> SafetyFeatures:
    coords = raw.coordinates
    resampled = resample_route(coords, interval_m=settings.resample_interval_m)
    distance_km = route_length_m(coords) / 1000.0

    child_zones = public_data.get_child_zones()
    hotspots = public_data.get_accident_hotspots()
    doc_points = public_data.get_doc_risk_points()
    guardian_houses = public_data.get_guardian_houses()
    speed_cameras = public_data.get_speed_cameras()

    zone_points = [(z["lat"], z["lng"]) for z in child_zones]
    hotspot_points = [(h["lat"], h["lng"]) for h in hotspots]
    doc_coord_points = [(d["lat"], d["lng"]) for d in doc_points]
    guardian_points = [(g["lat"], g["lng"]) for g in guardian_houses]
    speed_camera_points = [(c["lat"], c["lng"]) for c in speed_cameras]

    zone_r = settings.child_zone_radius_m
    buf = settings.buffer_radius_m

    matched_zone_idx = buffer_match(resampled, zone_points, zone_r)
    matched_hotspot_idx = buffer_match(resampled, hotspot_points, buf)
    matched_doc_idx = buffer_match(resampled, doc_coord_points, buf)
    matched_guardian_idx = buffer_match(resampled, guardian_points, buf)
    matched_speed_camera_idx = buffer_match(resampled, speed_camera_points, buf)

    zone_cctv_count = sum(int(child_zones[i].get("cctv_count") or 0) for i in matched_zone_idx)
    child_zone_coverage_pct = _child_zone_coverage_pct(resampled, child_zones, zone_r)
    guardian_house_count = len(matched_guardian_idx)
    speed_camera_count = len(matched_speed_camera_idx)

    crime_samples = [
        public_data.crime_risk_for_point(lat, lng)
        for (lat, lng) in resampled[:: max(1, len(resampled) // 10 or 1)]
    ]
    crime_risk_proxy = float(np.mean(crime_samples)) if crime_samples else 0.0

    matched_docs: List[DocMatch] = []
    doc_risk_count = 0
    doc_safety_count = 0
    for i in matched_doc_idx:
        rec = doc_points[i]
        dist = min_distance_to_route(resampled, (rec["lat"], rec["lng"]))
        is_risk = bool(rec.get("is_risk"))
        if is_risk:
            doc_risk_count += 1
        else:
            doc_safety_count += 1
        matched_docs.append(
            DocMatch(
                source_doc=rec.get("source_doc", "unknown"),
                page=rec.get("page"),
                snippet=rec.get("snippet", ""),
                risk_type=rec.get("risk_type", ""),
                is_risk=is_risk,
                distance_m=round(dist, 1),
                lat=rec["lat"],
                lng=rec["lng"],
            )
        )

    facility_counts = _count_safety_facilities_near_route(resampled, coords)
    streetlight_count = int(facility_counts.get("safety_facility_streetlight_count") or 0)
    ansim_cctv = int(facility_counts.get("safety_facility_cctv_count") or 0)
    combined_cctv = zone_cctv_count + ansim_cctv

    return SafetyFeatures(
        distance_km=round(distance_km, 3),
        cctv_count=combined_cctv,
        # 점수용 밀도는 안심 302만 (/km). 보호구역 CCTV는 zone_cctv_count로 분리.
        cctv_density=round(ansim_cctv / distance_km, 2) if distance_km > 0 else 0.0,
        child_zone_coverage_pct=round(child_zone_coverage_pct, 1),
        accident_hotspot_count=len(matched_hotspot_idx),
        crime_risk_proxy=round(crime_risk_proxy, 1),
        guardian_house_count=guardian_house_count,
        streetlight_count=streetlight_count,
        streetlight_density=round(streetlight_count / distance_km, 2) if distance_km > 0 else 0.0,
        speed_camera_count=speed_camera_count,
        doc_risk_count=doc_risk_count,
        doc_safety_count=doc_safety_count,
        matched_documents=matched_docs,
        safety_facility_cctv_count=ansim_cctv,
        safety_facility_streetlight_count=streetlight_count,
        safety_bell_count=int(facility_counts.get("safety_bell_count") or 0),
        emergency112_count=int(facility_counts.get("emergency112_count") or 0),
        emergency_pole_count=int(facility_counts.get("emergency_pole_count") or 0),
        zone_cctv_count=zone_cctv_count,
    )


def _eff_km(distance_km: float) -> float:
    return max(float(distance_km), float(settings.score_length_floor_km))


def _walk_overtime_penalty(walk_minutes: float) -> float:
    over = walk_minutes - settings.walk_soft_cap_minutes
    if over <= 0:
        return 0.0
    return min(over * settings.walk_overtime_penalty_per_min, settings.walk_overtime_penalty_max)


def _detour_penalty(distance_km: float, L_min: float) -> float:
    """최단 대비 초과 거리에 페널티. 짧은 통학로에서 우회가 구조적으로 지도록 두지 않기 위해
    grace(기본 200m ≈ 도보 3분)까지는 무료, 그 초과분만 비율 페널티.
    """
    if L_min <= 0:
        return 0.0
    extra_km = max(0.0, float(distance_km) - float(L_min))
    grace = max(0.0, float(settings.detour_penalty_grace_km))
    excess = max(0.0, extra_km - grace)
    if excess <= 0:
        return 0.0
    # 기존과 같은 스케일: 0.5 * L_min 초과 시 최대치
    scale = max(0.5 * float(L_min), 1e-6)
    return settings.detour_penalty_max * min(excess / scale, 1.0)


def _has_data_coverage(f: SafetyFeatures) -> bool:
    return any(
        [
            f.zone_cctv_count > 0,
            f.safety_facility_cctv_count > 0,
            f.safety_facility_streetlight_count > 0,
            f.guardian_house_count > 0,
            f.child_zone_coverage_pct > 0,
            f.speed_camera_count > 0,
            f.accident_hotspot_count > 0,
            f.doc_risk_count > 0,
            f.emergency_pole_count > 0,
        ]
    )


def absolute_score(
    features: SafetyFeatures,
    *,
    is_night: bool,
    detour_penalty: float = 0.0,
    walk_minutes: float | None = None,
) -> float:
    w = scoring_weights(is_night)
    k_table = settings.saturate_k
    bi = set(settings.bidirectional_night_features)
    L = _eff_km(features.distance_km)

    vals = {
        # 안심 302만 /km — 보호구역 CCTV는 zone_cctv(count)로 분리
        "cctv_density": features.safety_facility_cctv_count / L,
        "zone_cctv": float(features.zone_cctv_count),
        "light_density": features.safety_facility_streetlight_count / L,
        "child_zone_coverage": features.child_zone_coverage_pct / 100.0,
        "guardian_density": features.guardian_house_count / L,
        "emergency_density": features.emergency_pole_count / L,
        "speed_camera": float(features.speed_camera_count),
        "accident_hotspot": float(features.accident_hotspot_count),
        "doc_risk": float(features.doc_risk_count),
    }

    score = 50.0
    for key, raw in vals.items():
        weight = float(w.get(key, 0.0))
        if weight == 0:
            continue
        if key == "child_zone_coverage":
            term = weight * raw
        else:
            s = saturate(raw, float(k_table.get(key, 1.0)))
            if is_night and key in bi:
                term = weight * (2.0 * s - 1.0)
            elif key in ("accident_hotspot", "doc_risk"):
                term = -weight * s
            else:
                term = weight * s
        score += term

    score -= detour_penalty
    if walk_minutes is None:
        walk_minutes = (features.distance_km / 4.0) * 60.0
    score -= _walk_overtime_penalty(walk_minutes)
    # 상단 소프트 압축 — 안심 복도(삼릉초 등)에서 100 하드클립으로 순위가 뭉개지지 않게
    if score > 90.0:
        score = 90.0 + (score - 90.0) * 0.4
    return float(np.clip(score, 0, 100))


def score_candidates(raw_candidates: List[RouteCandidateRaw], is_night: bool | None = None) -> List[ScoredRoute]:
    if is_night is None:
        is_night = is_nighttime()

    scored = [ScoredRoute(raw=r, features=compute_features(r)) for r in raw_candidates]
    if not scored:
        return scored

    L_min = min(max(s.features.distance_km, 1e-6) for s in scored)

    for s in scored:
        walk_min = s.raw.duration_s / 60.0 if s.raw.duration_s else None
        s.safety_score = round(
            absolute_score(
                s.features,
                is_night=is_night,
                detour_penalty=_detour_penalty(s.features.distance_km, L_min),
                walk_minutes=walk_min,
            ),
            1,
        )
        s.data_coverage = _has_data_coverage(s.features)

    best_idx = max(
        range(len(scored)),
        key=lambda i: (
            scored[i].safety_score,
            scored[i].raw.main_road_distance_m,
            -scored[i].raw.distance_m,
        ),
    )
    scored[best_idx].is_recommended = True

    period = scoring_context_label(is_night)
    buf = settings.safety_facility_buffer_m
    mode_tag = "밤" if is_night else "낮"
    safe_print(
        f"\n=== {period} ({mode_tag}) - 절대스케일 안전점수 "
        f"(시설 {buf:.0f}m / 보호구역 {settings.child_zone_radius_m:.0f}m) ==="
    )
    for s in scored:
        f = s.features
        tag = "★추천" if s.is_recommended else "  "
        cov = "" if s.data_coverage else " · 데이터희소"
        nearest = nearest_facility_distance_m(
            resample_route(s.raw.coordinates, interval_m=settings.resample_interval_m)
        )
        near_txt = f" · 안심귀갓길 {nearest:.0f}m" if nearest is not None else ""
        safe_print(
            f"{tag} [{s.raw.id}] 안전점수 {s.safety_score}점{cov}{near_txt} | "
            f"존CCTV {f.zone_cctv_count} · 안심CCTV {f.safety_facility_cctv_count} · "
            f"보안등 {f.safety_facility_streetlight_count} · 비상폴 {f.emergency_pole_count} | "
            f"보호구역(감쇠) {f.child_zone_coverage_pct:.0f}% · 거리 {f.distance_km:.2f}km"
        )
    safe_print("=" * 60 + "\n")
    return scored
