"""Tmap 보행자 길찾기 연동.

Tmap 보행자 API(POST https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1)는
alternatives 파라미터가 없으므로, 경유지(passList)를 살짝 다르게 주어 2~3개의 경로
후보를 확보한다(PROJECT_PLAN.md 3장 방침). appKey가 없으면 동일한 인터페이스로
동작하는 MOCK 경로 생성기를 사용해 오프라인 데모가 가능하도록 한다.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, List, Tuple

import numpy as np
import requests

from ..config import settings
from ..console_safe import console_safe as _console_safe, safe_print
from .geo import haversine_m, min_distance_to_route, route_length_m
from .landmarks import landmark_for

TMAP_PEDESTRIAN_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
WALK_SPEED_MPS = 4000 / 3600  # 어린이 평균 도보 속도 근사치 (약 4km/h)


@dataclass
class NavigationStepRaw:
    """Tmap 보행자 경로가 제공하는 실제 안내 한 단계."""

    description: str
    turn_type: int | None = None
    distance_m: float = 0.0
    landmark: str | None = None


@dataclass
class RouteCandidateRaw:
    id: str
    label: str
    coordinates: List[Tuple[float, float]]  # (lat, lng)
    distance_m: float
    duration_s: float
    source: str
    navigation_steps: List[NavigationStepRaw] = field(default_factory=list)
    main_road_distance_m: float = 0.0


def _perpendicular_offset(origin: Tuple[float, float], destination: Tuple[float, float], offset_m: float) -> Tuple[float, float]:
    """origin-destination 중간점에서 수직 방향으로 offset_m만큼 떨어진 좌표를 근사 계산."""
    mid_lat = (origin[0] + destination[0]) / 2
    mid_lng = (origin[1] + destination[1]) / 2

    dlat = destination[0] - origin[0]
    dlng = destination[1] - origin[1]
    length = math.hypot(dlat, dlng) or 1e-9
    # 위경도 평면상 수직 벡터 (정확한 지오데식은 아니지만 국지적 근사로 충분)
    perp_lat = -dlng / length
    perp_lng = dlat / length

    meters_per_deg_lat = 111_320.0
    meters_per_deg_lng = 111_320.0 * math.cos(math.radians(mid_lat))
    offset_lat = perp_lat * (offset_m / meters_per_deg_lat)
    offset_lng = perp_lng * (offset_m / meters_per_deg_lng)
    return (mid_lat + offset_lat, mid_lng + offset_lng)


def _bearing(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """두 좌표 사이의 진행 방위각(0~360도)."""
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlng = lng2 - lng1
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


# 한 구간을 여러 스텝으로 쪼갤 때 사용하는 거리 패턴(m).
# 고정 간격 대신 반복 패턴을 써서 "직진 58m · 왼쪽 84m ..."처럼 자연스러운
# 턴바이턴 느낌을 낸다. (MOCK 데모 전용, 결정적이라 새로고침해도 동일)
_MOCK_CHUNK_PATTERN = [58.0, 84.0, 43.0, 71.0, 96.0, 52.0]

# Tmap turnType 중 좌/우회전 계열(랜드마크를 붙일 결정 지점).
_LANDMARK_TURN_TYPES = {12, 13, 14, 16, 17}

# Tmap 보행자 turnType → 짧은 방향 라벨 (description이 비어 있을 때 합성용).
_TURN_TYPE_LABELS: dict[int, str] = {
    11: "직진",
    12: "좌회전",
    13: "우회전",
    14: "유턴",
    16: "좌측길",
    17: "우측길",
    18: "로터리",
    19: "로터리",
    200: "출발",
    201: "도착",
    211: "횡단보도",
    212: "육교",
    213: "지하보도",
    214: "계단",
    215: "경사로",
    216: "엘리베이터",
    217: "에스컬레이터",
}

_METER_IN_TEXT = re.compile(r"(\d+(?:\.\d+)?)\s*m\b", re.IGNORECASE)


def _tmap_feature_sort_key(feature: dict[str, Any]) -> tuple[int, int, str]:
    """features를 index(기본) 순으로 정렬해 Point·LineString 짝을 맞춘다."""
    props = feature.get("properties") or {}
    index = int(props.get("index", props.get("pointIndex", props.get("lineIndex", 0))) or 0)
    gtype = (feature.get("geometry") or {}).get("type", "")
    # 같은 index면 Point를 LineString보다 먼저 (SP 안내 → 해당 구간)
    type_order = 0 if gtype == "Point" else 1
    return (index, type_order, gtype)


def _append_unique_coord(
    coords: List[Tuple[float, float]],
    lat: float,
    lng: float,
    *,
    min_gap_m: float = 0.5,
) -> None:
    """연속 중복·초근접 좌표를 건너뛰어 폴리라인 이음새 스파이크를 줄인다."""
    if not coords:
        coords.append((lat, lng))
        return
    prev_lat, prev_lng = coords[-1]
    if prev_lat == lat and prev_lng == lng:
        return
    gap = float(
        haversine_m(
            np.array([prev_lat]),
            np.array([prev_lng]),
            np.array([lat]),
            np.array([lng]),
        )[0]
    )
    if gap < min_gap_m:
        return
    coords.append((lat, lng))


def _segment_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return float(
        haversine_m(
            np.array([a[0]]),
            np.array([a[1]]),
            np.array([b[0]]),
            np.array([b[1]]),
        )[0]
    )


def _bearing_deg(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlng = lng2 - lng1
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _heading_change_deg(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> float:
    """B에서의 진행방향 변화(0=직진, 180=유턴에 가까움)."""
    delta = abs(_bearing_deg(a, b) - _bearing_deg(b, c))
    return min(delta, 360.0 - delta)


def _remove_polyline_spikes(
    coords: List[Tuple[float, float]],
    *,
    max_leg_m: float = 40.0,
    min_turn_deg: float = 95.0,
    min_detour_m: float = 6.0,
) -> List[Tuple[float, float]]:
    """사거리 횡단 등으로 잠깐 삐져나갔다 돌아오는 꼭짓점을 제거한다."""
    if len(coords) < 3:
        return list(coords)

    result = list(coords)
    changed = True
    while changed:
        changed = False
        i = 1
        while i < len(result) - 1:
            a, b, c = result[i - 1], result[i], result[i + 1]
            ab = _segment_m(a, b)
            bc = _segment_m(b, c)
            ac = _segment_m(a, c)
            detour = ab + bc - ac
            turn = _heading_change_deg(a, b, c)
            if (
                turn >= min_turn_deg
                and ab <= max_leg_m
                and bc <= max_leg_m
                and detour >= min_detour_m
                and (ab + bc) > ac * 1.12
            ):
                del result[i]
                changed = True
                continue
            i += 1
    return result


def _remove_out_and_back_spurs(
    coords: List[Tuple[float, float]],
    *,
    tip_turn_min: float = 150.0,
    match_tol_m: float = 14.0,
    max_half_spur_m: float = 180.0,
) -> List[Tuple[float, float]]:
    """골목으로 나갔다가 같은 길로 되돌아오는 긴 왕복(스파이크) 구간을 접는다."""
    if len(coords) < 4:
        return list(coords)

    result = list(coords)
    changed = True
    while changed:
        changed = False
        for tip in range(1, len(result) - 1):
            turn = _heading_change_deg(result[tip - 1], result[tip], result[tip + 1])
            if turn < tip_turn_min:
                continue

            best_k = 0
            outbound = 0.0
            for k in range(1, min(tip, len(result) - 1 - tip) + 1):
                outbound += _segment_m(result[tip - k + 1], result[tip - k])
                if outbound > max_half_spur_m:
                    break
                if _segment_m(result[tip - k], result[tip + k]) > match_tol_m:
                    break
                best_k = k

            if best_k < 1:
                # 샘플이 비대칭이어도 tip 양옆이 가까우면 유턴 꼭짓점만 제거
                ab = _segment_m(result[tip - 1], result[tip])
                bc = _segment_m(result[tip], result[tip + 1])
                ac = _segment_m(result[tip - 1], result[tip + 1])
                if ab <= max_half_spur_m and bc <= max_half_spur_m and ac < max(ab, bc) * 0.55:
                    del result[tip]
                    changed = True
                    break
                continue

            left = tip - best_k
            right = tip + best_k
            result = result[: left + 1] + result[right + 1 :]
            changed = True
            break
    return result


def _clean_route_polyline(coords: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """긴 왕복 골목을 먼저 접고, 남은 짧은 스파이크를 제거한다."""
    cleaned = _remove_out_and_back_spurs(coords)
    cleaned = _remove_polyline_spikes(cleaned)
    return cleaned


def _coords_from_tmap_features(
    features: list[dict[str, Any]],
) -> tuple[List[Tuple[float, float]], float, float, float]:
    """LineString을 index 순으로 이어 붙여 (좌표, 거리, 시간, 대로거리)를 만든다."""
    coords: List[Tuple[float, float]] = []
    main_road_distance_m = 0.0
    total_distance = 0.0
    total_time = 0.0

    line_features = [
        feature
        for feature in features
        if (feature.get("geometry") or {}).get("type") == "LineString"
    ]
    for feature in sorted(line_features, key=_tmap_feature_sort_key):
        props = feature.get("properties", {}) or {}
        geometry = feature.get("geometry", {}) or {}
        distance_m = float(props.get("distance", 0) or 0)
        total_distance += distance_m
        total_time += float(props.get("time", 0) or 0)
        road_name = str(props.get("description", "")).split(",", 1)[0].strip()
        if road_name.endswith("대로"):
            main_road_distance_m += distance_m * 2
        elif road_name.endswith("로"):
            main_road_distance_m += distance_m
        for lng, lat in geometry.get("coordinates", []):
            _append_unique_coord(coords, float(lat), float(lng))

    coords = _clean_route_polyline(coords)
    return coords, total_distance, total_time, main_road_distance_m


def _parse_meters_from_text(text: str) -> float | None:
    match = _METER_IN_TEXT.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_turn_type(raw: Any) -> int | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _build_step_description(props: dict[str, Any], distance_m: float) -> str:
    """Tmap Point properties에서 안내 문구를 만든다. description이 없어도 turnType·거리로 합성."""
    description = str(props.get("description") or "").strip()
    if description:
        return description

    turn_type = _parse_turn_type(props.get("turnType"))
    parts: list[str] = []
    if turn_type is not None:
        label = _TURN_TYPE_LABELS.get(turn_type)
        if label:
            parts.append(label)

    for key in ("intersectionName", "name", "facilityName", "nearPoiName"):
        value = str(props.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
            break

    if distance_m > 0:
        parts.append(f"{distance_m:.0f}m 이동")
    elif props.get("direction") is not None:
        parts.append(f"방향 {props['direction']}°")

    return " · ".join(parts) if parts else "이동"


def _infer_turn_type_from_text(text: str) -> int | None:
    if "좌회전" in text or "좌측" in text:
        return 12
    if "우회전" in text or "우측" in text:
        return 13
    if "횡단보도" in text:
        return 211
    if "육교" in text:
        return 212
    if "도착" in text:
        return 201
    if "직진" in text:
        return 11
    return None


def _parse_tmap_navigation_steps(features: list[dict[str, Any]]) -> list[NavigationStepRaw]:
    """Tmap GeoJSON features에서 Point(안내) + LineString(거리)를 짝지어 턴바이턴 스텝을 만든다."""
    sorted_features = sorted(features, key=_tmap_feature_sort_key)
    steps: list[NavigationStepRaw] = []
    pending_distance = 0.0

    for i, feature in enumerate(sorted_features):
        geometry = feature.get("geometry") or {}
        gtype = geometry.get("type")
        props = feature.get("properties") or {}

        if gtype == "LineString":
            pending_distance = float(props.get("distance", 0) or 0)
            continue

        if gtype != "Point":
            continue

        # SP(출발) Point는 바로 뒤 LineString 거리를 미리 읽는다.
        next_line_distance = 0.0
        for later in sorted_features[i + 1 :]:
            if (later.get("geometry") or {}).get("type") == "LineString":
                next_line_distance = float((later.get("properties") or {}).get("distance", 0) or 0)
                break

        description_raw = str(props.get("description") or "")
        distance_m = (
            _parse_meters_from_text(description_raw)
            or (pending_distance if pending_distance > 0 else None)
            or (next_line_distance if next_line_distance > 0 else None)
            or 0.0
        )
        description = _build_step_description(props, distance_m)
        turn_type = _parse_turn_type(props.get("turnType")) or _infer_turn_type_from_text(description)

        landmark = None
        point = geometry.get("coordinates")
        if point and turn_type is not None and (
            turn_type in _LANDMARK_TURN_TYPES or 211 <= turn_type <= 217
        ):
            try:
                landmark = landmark_for(float(point[1]), float(point[0]))
            except (TypeError, ValueError, IndexError):
                landmark = None

        steps.append(
            NavigationStepRaw(
                description=description,
                turn_type=turn_type,
                distance_m=round(distance_m, 1),
                landmark=landmark,
            )
        )
        pending_distance = 0.0

    return steps


def _steps_from_linestrings(features: list[dict[str, Any]]) -> list[NavigationStepRaw]:
    """Point 안내가 없을 때 LineString 구간만으로 턴바이턴을 합성한다."""
    steps: list[NavigationStepRaw] = []
    for feature in sorted(features, key=_tmap_feature_sort_key):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        props = feature.get("properties") or {}
        distance_m = float(props.get("distance", 0) or 0)
        road = str(props.get("description") or props.get("name") or "길").split(",", 1)[0].strip()
        turn_type = _infer_turn_type_from_text(road) or 11
        steps.append(
            NavigationStepRaw(
                description=f"{road} 따라 {distance_m:.0f}m 이동" if distance_m > 0 else road,
                turn_type=turn_type,
                distance_m=round(distance_m, 1),
            )
        )
    if steps and not any(s.turn_type == 201 for s in steps):
        steps.append(NavigationStepRaw(description="목적지 도착", turn_type=201, distance_m=0.0))
    return steps


def _log_tmap_response(data: dict[str, Any], *, label: str = "direct") -> None:
    """Tmap 보행자 API 응답 전체를 백엔드 콘솔에 출력 (TMAP_DEBUG_LOGGING=true 일 때만)."""
    if not settings.tmap_debug_logging:
        return
    print(f"\n[Tmap] ===== 보행자 API 응답 전체 ({label}) =====")
    try:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        payload = str(data)
    max_len = 20_000
    if len(payload) > max_len:
        print(payload[:max_len])
        print(f"... (총 {len(payload)}자, {max_len}자까지만 출력)")
    else:
        print(payload)
    print("[Tmap] ===== 응답 끝 =====\n")


def _interp(a: Tuple[float, float], b: Tuple[float, float], frac: float) -> Tuple[float, float]:
    """구간 a→b에서 frac(0~1) 위치의 좌표를 선형 보간(짧은 구간이라 왜곡 미미)."""
    frac = max(0.0, min(1.0, frac))
    return (a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac)


def _mock_navigation_steps(coords: List[Tuple[float, float]]) -> List[NavigationStepRaw]:
    """MOCK 경로 좌표로부터 어린이용 턴바이턴 안내 스텝을 합성한다.

    실제 Tmap 안내가 없는 오프라인/데모 환경에서도 '오늘은 이렇게 걸어요' 목록과
    아이 카드 모드가 동작하도록, 각 구간의 실제 거리·방향(직진/좌회전/우회전)을
    계산하고 교차로마다 횡단보도 건너기 안내를 끼워 넣는다. 방향이 바뀌는 결정
    지점(회전·횡단보도)에는 좌표 주변 랜드마크(편의점 등)를 함께 붙여준다.
    """
    if len(coords) < 2:
        return []

    steps: List[NavigationStepRaw] = []
    prev_bearing: float | None = None
    chunk_i = 0
    since_crosswalk = 0.0

    for i in range(len(coords) - 1):
        start, end = coords[i], coords[i + 1]
        leg_dist = route_length_m([start, end])
        if leg_dist < 1.0:
            continue
        bearing = _bearing(start, end)

        if prev_bearing is None:
            turn_desc, turn_tt = "직진", 11
        else:
            diff = (bearing - prev_bearing + 540.0) % 360.0 - 180.0
            if diff < -25.0:
                turn_desc, turn_tt = "좌회전", 12
            elif diff > 25.0:
                turn_desc, turn_tt = "우회전", 13
            else:
                turn_desc, turn_tt = "직진", 11
        prev_bearing = bearing

        remaining = leg_dist
        walked = 0.0
        first_chunk = True
        while remaining > 1.0:
            d = min(_MOCK_CHUNK_PATTERN[chunk_i % len(_MOCK_CHUNK_PATTERN)], remaining)
            chunk_i += 1
            walked += d
            remaining -= d
            desc, tt = (turn_desc, turn_tt) if first_chunk else ("직진", 11)
            mid = _interp(start, end, (walked - d / 2) / leg_dist)
            # 회전 시작 지점에만 랜드마크를 붙여 목록이 너무 지저분해지지 않게 한다.
            landmark = landmark_for(*mid) if first_chunk else None
            first_chunk = False
            steps.append(NavigationStepRaw(description=desc, turn_type=tt, distance_m=round(d, 1), landmark=landmark))
            since_crosswalk += d
            # 긴 직진 구간 중간중간에도 횡단보도를 넣어 실제 통학로처럼 보이게 한다.
            if since_crosswalk >= 220.0 and remaining > 30.0:
                cw = _interp(start, end, walked / leg_dist)
                steps.append(NavigationStepRaw(description="횡단보도 건너기", turn_type=211, distance_m=0.0, landmark=landmark_for(*cw)))
                since_crosswalk = 0.0

        # 방향이 꺾이는 교차로에는 횡단보도 건너기 안내를 추가한다.
        if i < len(coords) - 2:
            steps.append(NavigationStepRaw(description="횡단보도 건너기", turn_type=211, distance_m=0.0, landmark=landmark_for(*end)))
            since_crosswalk = 0.0

    steps.append(NavigationStepRaw(description="목적지 도착", turn_type=201, distance_m=0.0))
    return steps


def _demo_sample_steps() -> List[NavigationStepRaw]:
    """좌표가 부족할 때 카드 모드 시연용 고정 샘플."""
    return [
        NavigationStepRaw(description="직진", turn_type=11, distance_m=58.0, landmark="편의점"),
        NavigationStepRaw(description="좌회전", turn_type=12, distance_m=84.0, landmark="문구점"),
        NavigationStepRaw(description="횡단보도 건너기", turn_type=211, distance_m=0.0),
        NavigationStepRaw(description="직진", turn_type=11, distance_m=43.0),
        NavigationStepRaw(description="우회전", turn_type=13, distance_m=71.0, landmark="빵집"),
        NavigationStepRaw(description="목적지 도착", turn_type=201, distance_m=0.0),
    ]


def ensure_navigation_steps_for_coords(
    coordinates: List[Tuple[float, float]],
) -> List[NavigationStepRaw]:
    """API 응답 직전 등 어디서든 호출 가능한 상세 안내 보장 함수."""
    if len(coordinates) >= 2:
        return _mock_navigation_steps(coordinates)
    return _demo_sample_steps()


def _ensure_navigation_steps(candidate: RouteCandidateRaw) -> RouteCandidateRaw:
    """상세 안내가 없으면 좌표 기반 합성(또는 샘플)으로 채워 카드 모드가 항상 동작하게 한다."""
    if candidate.navigation_steps:
        if not any(s.turn_type == 201 or "도착" in (s.description or "") for s in candidate.navigation_steps):
            candidate.navigation_steps.append(
                NavigationStepRaw(description="목적지 도착", turn_type=201, distance_m=0.0)
            )
        return candidate

    if len(candidate.coordinates) >= 2:
        candidate.navigation_steps = ensure_navigation_steps_for_coords(candidate.coordinates)
        print(
            f"[경로안내] {candidate.id} ({candidate.source}): "
            f"Tmap Point 안내 없음 → 좌표 기반 합성 {len(candidate.navigation_steps)}단계"
        )
    else:
        candidate.navigation_steps = _demo_sample_steps()
        print(
            f"[경로안내] {candidate.id} ({candidate.source}): "
            f"좌표 부족 → 데모 샘플 {len(candidate.navigation_steps)}단계"
        )
    return candidate


def _log_navigation_steps(candidate: RouteCandidateRaw) -> None:
    """Tmap/MOCK 상세 안내 수신 여부를 콘솔에 출력."""
    steps = candidate.navigation_steps
    safe_print(f"\n=== Tmap/경로 상세 안내 [{candidate.id}] source={candidate.source} · {len(steps)}단계 ===")
    if not steps:
        safe_print("  (안내 없음)")
    else:
        for i, s in enumerate(steps, start=1):
            tt = s.turn_type if s.turn_type is not None else "-"
            dist = f"{s.distance_m:.0f}m" if s.distance_m else "-"
            lm = f" · landmark={s.landmark}" if s.landmark else ""
            line = f"  {i:2d}. turnType={tt} · {dist} · {s.description}{lm}"
            safe_print(line)
    safe_print("=" * 56)


def _mock_candidates(origin: Tuple[float, float], destination: Tuple[float, float]) -> List[RouteCandidateRaw]:
    o_lat, o_lng = origin
    d_lat, d_lng = destination

    diagonal = [origin, destination]
    grid_lat_first = [origin, (o_lat, d_lng), destination]
    grid_lng_first = [origin, (d_lat, o_lng), destination]

    candidates_raw = [
        ("route-direct", "직선 경로 (최단거리 우선)", diagonal),
        ("route-grid-a", "큰길 경로 A (위도 우선 이동)", grid_lat_first),
        ("route-grid-b", "큰길 경로 B (경도 우선 이동)", grid_lng_first),
    ]

    results: List[RouteCandidateRaw] = []
    for cid, label, coords in candidates_raw:
        dist = route_length_m(coords)
        results.append(
            RouteCandidateRaw(
                id=cid,
                label=label,
                coordinates=coords,
                distance_m=dist,
                duration_s=dist / WALK_SPEED_MPS,
                source="MOCK_ROUTING",
                navigation_steps=_mock_navigation_steps(coords),
            )
        )
    return results


def _call_tmap(origin: Tuple[float, float], destination: Tuple[float, float], pass_point: Tuple[float, float] | None = None) -> RouteCandidateRaw | None:
    route_label = "direct" if pass_point is None else "via"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "appKey": settings.tmap_app_key,
    }
    body = {
        "startX": origin[1],
        "startY": origin[0],
        "endX": destination[1],
        "endY": destination[0],
        "startName": "출발지",
        "endName": "목적지",
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "searchOption": "0",
        "sort": "index",
    }
    if pass_point is not None:
        body["passList"] = f"{pass_point[1]},{pass_point[0]}"

    if settings.tmap_debug_logging:
        print(f"[Tmap] 보행자 API 요청 ({route_label}): POST {TMAP_PEDESTRIAN_URL}")
        print(f"[Tmap] 요청 body: {json.dumps(body, ensure_ascii=False)}")

    resp: requests.Response | None = None
    try:
        resp = requests.post(
            TMAP_PEDESTRIAN_URL,
            params={"version": "1", "format": "json"},
            headers=headers,
            json=body,
            timeout=10,
        )
        print(f"[Tmap] HTTP 상태: {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as exc:
        body_text = resp.text[:2000] if resp is not None else "(응답 없음)"
        print(f"[Tmap] HTTP 오류 ({route_label}): {exc}")
        print(f"[Tmap] 응답 본문: {body_text}")
        if resp is not None and resp.status_code == 401:
            print("[Tmap] 원인 추정: appKey(TMAP_APP_KEY)가 잘못되었거나 만료됨")
        elif resp is not None and resp.status_code == 400:
            print("[Tmap] 원인 추정: 좌표/파라미터 오류 (출발·도착이 같거나 범위 밖)")
        return None
    except requests.RequestException as exc:
        print(f"[Tmap] 네트워크 오류 ({route_label}): {exc}")
        print("[Tmap] 원인 추정: 서버에서 Tmap API 접근 불가 (방화벽·DNS·타임아웃). CORS는 서버→Tmap 호출이라 해당 없음")
        return None
    except ValueError as exc:
        print(f"[Tmap] JSON 파싱 실패 ({route_label}): {exc}")
        return None

    if isinstance(data, dict) and data.get("error"):
        print(f"[Tmap] API error 필드 ({route_label}): {json.dumps(data['error'], ensure_ascii=False)}")
        return None

    _log_tmap_response(data, label=route_label)

    features = data.get("features", [])
    if not isinstance(features, list):
        print(f"[Tmap] features 필드가 없거나 배열이 아님: {type(features)}")
        return None

    coords, total_distance, total_time, main_road_distance_m = _coords_from_tmap_features(features)

    navigation_steps = _parse_tmap_navigation_steps(features)
    if not navigation_steps:
        print(f"[Tmap] Point 안내 0개 → LineString 구간으로 합성 시도 ({route_label})")
        navigation_steps = _steps_from_linestrings(features)

    point_count = sum(1 for f in features if (f.get("geometry") or {}).get("type") == "Point")
    line_count = sum(1 for f in features if (f.get("geometry") or {}).get("type") == "LineString")
    print(
        f"[Tmap] features Point={point_count} LineString={line_count} "
        f"→ 파싱된 안내 {len(navigation_steps)}단계, 좌표 {len(coords)}개 ({route_label})"
    )
    if point_count > 0 and len(navigation_steps) == 0:
        sample = next(
            (f.get("properties") for f in features if (f.get("geometry") or {}).get("type") == "Point"),
            {},
        )
        print(f"[Tmap] Point properties 샘플 keys={list(sample.keys())} desc={sample.get('description')!r}")

    if not coords:
        print(f"[Tmap] 좌표 없음 — 경로 생성 실패 ({route_label})")
        return None
    if total_distance <= 0:
        total_distance = route_length_m(coords)
    if total_time <= 0:
        total_time = total_distance / WALK_SPEED_MPS

    return RouteCandidateRaw(
        id=f"route-tmap-{'direct' if pass_point is None else 'via'}",
        label="Tmap 추천 경로" if pass_point is None else "Tmap 대안 경로 (경유지 포함)",
        coordinates=coords,
        distance_m=total_distance,
        duration_s=total_time,
        source="TMAP_PEDESTRIAN_API",
        navigation_steps=navigation_steps,
        main_road_distance_m=main_road_distance_m,
    )


def _finalize_candidates(candidates: List[RouteCandidateRaw]) -> List[RouteCandidateRaw]:
    """모든 후보에 상세 안내를 보장하고 콘솔에 출력."""
    finalized: List[RouteCandidateRaw] = []
    for c in candidates:
        c = _ensure_navigation_steps(c)
        _log_navigation_steps(c)
        finalized.append(c)
    return finalized


def _candidate_sort_key(candidate: RouteCandidateRaw) -> tuple[int, str]:
    """기본 경로를 먼저, 우회 경로는 식별자 끝 문자 순으로 정렬한다."""
    if "direct" in candidate.id:
        return (0, "")
    return (1, candidate.id)


def _routes_are_equivalent(first: RouteCandidateRaw, second: RouteCandidateRaw, tolerance_m: float = 25.0) -> bool:
    """Tmap 응답 수치 또는 좌표 밀도를 비교해 같은 길인지 확인한다."""
    if not first.coordinates or not second.coordinates:
        return False
    distance_delta = abs(first.distance_m - second.distance_m)
    duration_delta = abs(first.duration_s - second.duration_s)
    # Tmap이 서로 다른 좌표 샘플링으로 같은 경로를 반환하는 경우가 있어,
    # 거리·시간이 사실상 같으면 지도 좌표의 미세한 차이와 무관하게 중복으로 처리한다.
    if distance_delta <= 10.0 and duration_delta <= 20.0:
        return True
    if distance_delta > max(20.0, max(first.distance_m, second.distance_m) * 0.03):
        return False

    first_to_second = max(min_distance_to_route(second.coordinates, point) for point in first.coordinates)
    second_to_first = max(min_distance_to_route(first.coordinates, point) for point in second.coordinates)
    return first_to_second <= tolerance_m and second_to_first <= tolerance_m


def _deduplicate_candidates(candidates: List[RouteCandidateRaw]) -> List[RouteCandidateRaw]:
    """동일 경로는 기본 경로를 우선 보존하고 우회 경로는 A, B 순으로 반환한다."""
    unique: List[RouteCandidateRaw] = []
    for candidate in sorted(candidates, key=_candidate_sort_key):
        matching = next((existing for existing in unique if _routes_are_equivalent(existing, candidate)), None)
        if matching:
            print(f"[경로] 중복 후보 제외: {candidate.id} (기존 {matching.id}와 동일)")
            continue
        unique.append(candidate)
    return unique


def get_route_candidates(origin: Tuple[float, float], destination: Tuple[float, float], force_mock: bool | None = None) -> List[RouteCandidateRaw]:
    use_mock = settings.routing_mock if force_mock is None else force_mock
    mode_label = "MOCK" if use_mock else "LIVE (Tmap)"
    print(f"\n[경로] === 경로 후보 계산 시작 ({mode_label}) ===")
    print(f"[경로] 출발 (lat,lng)=({origin[0]:.6f}, {origin[1]:.6f}) → 도착 ({destination[0]:.6f}, {destination[1]:.6f})")
    if use_mock:
        print("[경로] MOCK 모드 — 합성 턴바이턴 안내 사용 (route-direct 등)")
        return _finalize_candidates(_deduplicate_candidates(_mock_candidates(origin, destination)))

    candidates: List[RouteCandidateRaw] = []

    direct = _call_tmap(origin, destination)
    if direct:
        candidates.append(direct)

    for offset in (120.0, -120.0):
        via_point = _perpendicular_offset(origin, destination, offset)
        via = _call_tmap(origin, destination, pass_point=via_point)
        if via:
            via.id = f"{via.id}-{'a' if offset > 0 else 'b'}"
            candidates.append(via)

    if not candidates:
        print("[경로] Tmap 전부 실패 → MOCK 폴백 (route-direct 직선 등)")
        return _finalize_candidates(_deduplicate_candidates(_mock_candidates(origin, destination)))
    print(f"[경로] === Tmap 성공: 후보 {len(candidates)}개 ===")
    return _finalize_candidates(_deduplicate_candidates(candidates))
