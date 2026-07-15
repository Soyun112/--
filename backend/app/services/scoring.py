"""경로 후보에 대해 공공데이터/문서기반 데이터를 매칭하고 안전점수를 계산한다.

PROJECT_PLAN.md 5장 수식을 그대로 구현:
- 경로를 20m 간격으로 리샘플링 후 Haversine 버퍼(기본 40m) 매칭
- 절대 가중치보다 "후보 경로 간 상대 정규화"를 우선해 임의의 가중치 논쟁을 줄인다
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from ..config import settings
from ..models import DocMatch, SafetyFeatures
from . import public_data
from .geo import buffer_match, min_distance_to_route, resample_route, route_length_m
from .routing import RouteCandidateRaw
from .safety_facilities import get_safety_facilities
from .time_context import apply_time_weights, is_nighttime, scoring_context_label


@dataclass
class ScoredRoute:
    raw: RouteCandidateRaw
    features: SafetyFeatures
    safety_score: float = 0.0
    is_recommended: bool = False


def _child_zone_coverage_pct(resampled_points, child_zones: list[dict], radius_m: float) -> float:
    if not resampled_points or not child_zones:
        return 0.0
    zone_points = [(z["lat"], z["lng"]) for z in child_zones]
    covered = 0
    for pt in resampled_points:
        dists_ok = any(
            min_distance_to_route([pt], zp) <= radius_m for zp in zone_points
        )
        if dists_ok:
            covered += 1
    return 100.0 * covered / len(resampled_points)


def _bbox_for_route(coords: list[tuple[float, float]], margin_deg: float = 0.004) -> tuple[float, float, float, float]:
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    return min(lats) - margin_deg, max(lats) + margin_deg, min(lngs) - margin_deg, max(lngs) + margin_deg


def _count_safety_facilities_near_route(
    resampled: list[tuple[float, float]],
    coords: list[tuple[float, float]],
) -> dict[str, int]:
    """안심귀갓길 CSV 시설물을 경로 주변 buffer(기본 40m) 안에서 종류별 집계."""
    from .safety_facilities import facilities_in_bbox

    all_facilities = get_safety_facilities()
    if not all_facilities or not resampled:
        return {
            "safety_facility_cctv_count": 0,
            "safety_facility_streetlight_count": 0,
            "safety_bell_count": 0,
            "emergency112_count": 0,
        }

    min_lat, max_lat, min_lng, max_lng = _bbox_for_route(coords)
    nearby = facilities_in_bbox(all_facilities, min_lat, max_lat, min_lng, max_lng)
    if not nearby:
        return {
            "safety_facility_cctv_count": 0,
            "safety_facility_streetlight_count": 0,
            "safety_bell_count": 0,
            "emergency112_count": 0,
        }

    facility_points = [(f["lat"], f["lng"]) for f in nearby]
    radius = settings.safety_facility_buffer_m
    matched_idx = buffer_match(resampled, facility_points, radius)

    counts = {
        "safety_facility_cctv_count": 0,
        "safety_facility_streetlight_count": 0,
        "safety_bell_count": 0,
        "emergency112_count": 0,
    }
    for i in matched_idx:
        f = nearby[i]
        ftype = f["facility_type"]
        qty = int(f.get("install_count") or 1)
        if ftype == "cctv":
            counts["safety_facility_cctv_count"] += qty
        elif ftype == "streetlight":
            counts["safety_facility_streetlight_count"] += qty
        elif ftype == "safety_bell":
            counts["safety_bell_count"] += qty
        elif ftype == "emergency112":
            counts["emergency112_count"] += qty
    return counts


def compute_features(raw: RouteCandidateRaw) -> SafetyFeatures:
    coords = raw.coordinates
    resampled = resample_route(coords, interval_m=settings.resample_interval_m)
    distance_km = route_length_m(coords) / 1000.0

    child_zones = public_data.get_child_zones()
    hotspots = public_data.get_accident_hotspots()
    doc_points = public_data.get_doc_risk_points()
    guardian_houses = public_data.get_guardian_houses()
    streetlights = public_data.get_streetlights()
    speed_cameras = public_data.get_speed_cameras()

    zone_points = [(z["lat"], z["lng"]) for z in child_zones]
    hotspot_points = [(h["lat"], h["lng"]) for h in hotspots]
    doc_coord_points = [(d["lat"], d["lng"]) for d in doc_points]
    guardian_points = [(g["lat"], g["lng"]) for g in guardian_houses]
    streetlight_points = [(s["lat"], s["lng"]) for s in streetlights]
    speed_camera_points = [(c["lat"], c["lng"]) for c in speed_cameras]

    matched_zone_idx = buffer_match(resampled, zone_points, settings.buffer_radius_m)
    matched_hotspot_idx = buffer_match(resampled, hotspot_points, settings.buffer_radius_m)
    matched_doc_idx = buffer_match(resampled, doc_coord_points, settings.buffer_radius_m)
    matched_guardian_idx = buffer_match(resampled, guardian_points, settings.buffer_radius_m)
    matched_streetlight_idx = buffer_match(resampled, streetlight_points, settings.buffer_radius_m)
    matched_speed_camera_idx = buffer_match(resampled, speed_camera_points, settings.buffer_radius_m)

    cctv_count = sum(int(child_zones[i].get("cctv_count") or 0) for i in matched_zone_idx)
    child_zone_coverage_pct = _child_zone_coverage_pct(resampled, child_zones, settings.buffer_radius_m)
    guardian_house_count = len(matched_guardian_idx)
    streetlight_count = len(matched_streetlight_idx)
    speed_camera_count = len(matched_speed_camera_idx)

    crime_samples = [
        public_data.crime_risk_for_point(lat, lng) for (lat, lng) in resampled[:: max(1, len(resampled) // 10 or 1)]
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

    return SafetyFeatures(
        distance_km=round(distance_km, 3),
        cctv_count=cctv_count,
        cctv_density=round(cctv_count / distance_km, 2) if distance_km > 0 else 0.0,
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
        **facility_counts,
    )


def _normalize(values: List[float]) -> List[float]:
    """min-max 정규화 (0~1). 후보가 1개뿐이거나 값이 모두 같으면 0.5로 중립화."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def score_candidates(raw_candidates: List[RouteCandidateRaw], is_night: bool | None = None) -> List[ScoredRoute]:
    if is_night is None:
        is_night = is_nighttime()

    scored = [ScoredRoute(raw=r, features=compute_features(r)) for r in raw_candidates]

    w = apply_time_weights(settings.weights, is_night)
    period = scoring_context_label(is_night)
    cctv_norm = _normalize([s.features.cctv_density for s in scored])
    zone_norm = _normalize([s.features.child_zone_coverage_pct for s in scored])
    doc_safety_norm = _normalize([s.features.doc_safety_count for s in scored])
    guardian_norm = _normalize([s.features.guardian_house_count for s in scored])
    streetlight_norm = _normalize([s.features.streetlight_density for s in scored])
    speed_camera_norm = _normalize([s.features.speed_camera_count for s in scored])
    hotspot_norm = _normalize([s.features.accident_hotspot_count for s in scored])
    crime_norm = _normalize([s.features.crime_risk_proxy for s in scored])
    doc_risk_norm = _normalize([s.features.doc_risk_count for s in scored])
    sf_cctv_norm = _normalize([s.features.safety_facility_cctv_count for s in scored])
    sf_light_norm = _normalize([s.features.safety_facility_streetlight_count for s in scored])
    sf_bell_norm = _normalize([s.features.safety_bell_count for s in scored])
    sf_112_norm = _normalize([s.features.emergency112_count for s in scored])

    for i, s in enumerate(scored):
        score = 50.0
        score += w["cctv_density"] * cctv_norm[i]
        score += w["child_zone_coverage"] * zone_norm[i]
        score += w["doc_safety"] * doc_safety_norm[i]
        score += w["guardian_house"] * guardian_norm[i]
        score += w["streetlight_density"] * streetlight_norm[i]
        score += w["speed_camera"] * speed_camera_norm[i]
        score -= w["accident_hotspot"] * hotspot_norm[i]
        score -= w["crime_risk"] * crime_norm[i]
        score -= w["doc_risk"] * doc_risk_norm[i]
        score += w["safety_facility_cctv"] * sf_cctv_norm[i]
        score += w["safety_facility_streetlight"] * sf_light_norm[i]
        score += w["safety_bell"] * sf_bell_norm[i]
        score += w["emergency112"] * sf_112_norm[i]
        s.safety_score = round(float(np.clip(score, 0, 100)), 1)

    # 동점이면 큰길(대로·로) 구간이 더 긴 경로를 우선하고, 다시 동점이면 짧은 길을 고른다.
    best_idx = (
        max(
            range(len(scored)),
            key=lambda i: (
                scored[i].safety_score,
                scored[i].raw.main_road_distance_m,
                -scored[i].raw.distance_m,
            ),
        )
        if scored
        else None
    )
    if best_idx is not None:
        scored[best_idx].is_recommended = True

    # 경로별 시설 개수·안전점수를 콘솔에 출력 (데모·디버깅용)
    buf = settings.safety_facility_buffer_m
    mode_tag = "🌙 밤" if is_night else "☀️ 낮"
    print(f"\n=== {period} ({mode_tag}) · 안심귀갓길 시설물 기반 안전점수 (경로 주변 {buf:.0f}m) ===")
    for s in scored:
        f = s.features
        tag = "★추천" if s.is_recommended else "  "
        print(
            f"{tag} [{s.raw.id}] 안전점수 {s.safety_score}점 | "
            f"CCTV {f.safety_facility_cctv_count} · 보안등 {f.safety_facility_streetlight_count} · "
            f"안심벨 {f.safety_bell_count} · 112 {f.emergency112_count} | "
            f"거리 {f.distance_km:.2f}km"
        )
    print("=" * 60 + "\n")

    return scored
