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
from ..console_safe import safe_print
from .routing import RouteCandidateRaw
from .safety_facilities import get_safety_facilities
from .time_context import is_nighttime, scoring_context_label


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


def _dim(count: float | int | None, per: float, cap: float) -> float:
    """개수×점수, 상한(cap)으로 포화 방지."""
    n = max(0.0, float(count or 0))
    return min(cap, n * per)


def _absolute_raw_score(features: SafetyFeatures, is_night: bool) -> float:
    """시설·위험 개수 기반 절대 점수. 상대 정규화만 쓰면 전부 100으로 붙는 문제 방지."""
    score = 60.0

    cctv_per = 1.6 if is_night else 1.1
    light_per = 1.3 if is_night else 0.8
    hotspot_per = 5.0 if is_night else 7.0
    doc_risk_per = 6.0 if is_night else 8.0

    # 가점 (상한으로 만점 도달 불가하게)
    score += _dim(features.safety_facility_cctv_count, cctv_per, 14.0)
    score += _dim(features.safety_facility_streetlight_count, light_per, 10.0)
    score += _dim(features.safety_bell_count, 1.0, 4.0)
    score += _dim(features.emergency112_count, 0.8, 3.0)
    score += _dim(features.guardian_house_count, 2.0, 8.0)
    score += _dim(features.speed_camera_count, 1.0, 4.0)
    score += _dim(features.doc_safety_count, 1.5, 5.0)
    score += min(8.0, float(features.child_zone_coverage_pct or 0) * 0.08)
    # 어린이보호구역 CCTV 밀도(보조)
    score += min(6.0, float(features.cctv_density or 0) * 0.15)

    # 감점
    score -= _dim(features.accident_hotspot_count, hotspot_per, 22.0)
    score -= _dim(features.doc_risk_count, doc_risk_per, 22.0)
    score -= min(10.0, float(features.crime_risk_proxy or 0) * 0.08)

    return score


def _force_distinct_scores(raw_scores: List[float], scored: List[ScoredRoute]) -> List[float]:
    """점수가 전부 같으면 시설·위험·거리로 순위를 갈라 표시 점수를 다르게 만든다."""
    if len(raw_scores) <= 1:
        return [round(float(np.clip(raw_scores[0], 38.0, 92.0)), 1)] if raw_scores else []

    rounded = [round(r, 2) for r in raw_scores]
    if len(set(rounded)) > 1:
        lo, hi = min(raw_scores), max(raw_scores)
        return [
            round(float(np.clip(40.0 + 50.0 * (r - lo) / (hi - lo + 1e-9), 40.0, 92.0)), 1)
            for r in raw_scores
        ]

    # 완전 동점 → 보조 키로 강제 분산 (추천이 항상 더 높은 점수)
    rank_keys = []
    for s in scored:
        f = s.features
        safety_stock = (
            f.safety_facility_cctv_count
            + f.safety_facility_streetlight_count
            + f.guardian_house_count * 2
            + f.child_zone_coverage_pct * 0.05
        )
        risk_stock = f.accident_hotspot_count * 3 + f.doc_risk_count * 4 + f.crime_risk_proxy * 0.05
        rank_keys.append(
            (
                safety_stock - risk_stock,
                s.raw.main_road_distance_m,
                -s.raw.distance_m,
            )
        )
    order = sorted(range(len(scored)), key=lambda i: rank_keys[i], reverse=True)
    # 1등 88, 2등 76, 3등 64 … (최소 12점 간격)
    assigned = [0.0] * len(scored)
    top = 88.0
    for rank, idx in enumerate(order):
        assigned[idx] = round(max(40.0, top - rank * 12.0), 1)
    return assigned


def score_candidates(raw_candidates: List[RouteCandidateRaw], is_night: bool | None = None) -> List[ScoredRoute]:
    if is_night is None:
        is_night = is_nighttime()

    scored = [ScoredRoute(raw=r, features=compute_features(r)) for r in raw_candidates]
    period = scoring_context_label(is_night)

    raw_scores = [_absolute_raw_score(s.features, is_night) for s in scored]
    display_scores = _force_distinct_scores(raw_scores, scored)

    for s, display in zip(scored, display_scores):
        # 하드 캡: 어떤 경우에도 전원 100점 불가 (최대 92)
        s.safety_score = round(float(np.clip(display, 38.0, 92.0)), 1)

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

    buf = settings.safety_facility_buffer_m
    mode_tag = "밤" if is_night else "낮"
    safe_print(
        f"\n=== {period} ({mode_tag}) - 절대점수 absolute_v2 "
        f"(경로 주변 {buf:.0f}m, 표시 최대 92점) ==="
    )
    for s, raw in zip(scored, raw_scores):
        f = s.features
        tag = "★추천" if s.is_recommended else "  "
        safe_print(
            f"{tag} [{s.raw.id}] 안전점수 {s.safety_score}점 (원시 {raw:.1f}) | "
            f"CCTV {f.safety_facility_cctv_count} · 보안등 {f.safety_facility_streetlight_count} · "
            f"안심벨 {f.safety_bell_count} · 112 {f.emergency112_count} | "
            f"사고다발 {f.accident_hotspot_count} · 문서위험 {f.doc_risk_count} | "
            f"거리 {f.distance_km:.2f}km"
        )
    safe_print("=" * 60 + "\n")

    return scored
