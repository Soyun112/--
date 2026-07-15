"""좌표 간 거리 계산(Haversine), 경로 리샘플링, 경로 주변 버퍼 매칭.

PostGIS 없이도 데모 규모(경로 1개당 수십~수백 개 데이터포인트)에서는
numpy 벡터화 연산으로 충분히 빠르게 동작한다. 데이터 규모가 커지면
PostGIS의 ST_DWithin으로 교체하는 것을 향후 로드맵으로 남겨둔다.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

import numpy as np

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: np.ndarray, lng1: np.ndarray, lat2: np.ndarray, lng2: np.ndarray) -> np.ndarray:
    """벡터화된 Haversine 거리(미터). 각 입력은 브로드캐스팅 가능한 배열."""
    lat1r, lng1r, lat2r, lng2r = map(np.radians, (lat1, lng1, lat2, lng2))
    dlat = lat2r - lat1r
    dlng = lng2r - lng1r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlng / 2.0) ** 2
    c = 2 * np.arcsin(np.clip(np.sqrt(a), -1, 1))
    return EARTH_RADIUS_M * c


def route_length_m(coords: Sequence[Tuple[float, float]]) -> float:
    if len(coords) < 2:
        return 0.0
    lats = np.array([c[0] for c in coords])
    lngs = np.array([c[1] for c in coords])
    d = haversine_m(lats[:-1], lngs[:-1], lats[1:], lngs[1:])
    return float(np.sum(d))


def resample_route(coords: Sequence[Tuple[float, float]], interval_m: float = 20.0) -> List[Tuple[float, float]]:
    """폴리라인을 대략 interval_m 간격의 점 시퀀스로 재샘플링한다.

    정밀한 지오데식 보간 대신, 등거리 위경도 근사(구간이 짧아 왜곡이 미미함)를 사용해
    해커톤 일정 내에서 충분히 정확하고 빠른 구현을 우선한다.
    """
    if len(coords) < 2:
        return list(coords)

    resampled: List[Tuple[float, float]] = [coords[0]]
    for (lat1, lng1), (lat2, lng2) in zip(coords[:-1], coords[1:]):
        seg_len = haversine_m(np.array([lat1]), np.array([lng1]), np.array([lat2]), np.array([lng2]))[0]
        if seg_len <= interval_m:
            resampled.append((lat2, lng2))
            continue
        steps = max(1, int(seg_len // interval_m))
        for i in range(1, steps + 1):
            t = i / steps
            resampled.append((lat1 + (lat2 - lat1) * t, lng1 + (lng2 - lng1) * t))
    return resampled


def buffer_match(
    route_points: Sequence[Tuple[float, float]],
    data_points: Sequence[Tuple[float, float]],
    radius_m: float,
) -> List[int]:
    """route_points 중 하나라도 반경 radius_m 이내에 있는 data_points의 인덱스 목록을 반환."""
    if not route_points or not data_points:
        return []

    route_lat = np.array([p[0] for p in route_points])
    route_lng = np.array([p[1] for p in route_points])

    matched_indices: List[int] = []
    for idx, (dlat, dlng) in enumerate(data_points):
        dists = haversine_m(route_lat, route_lng, np.full_like(route_lat, dlat), np.full_like(route_lng, dlng))
        if np.min(dists) <= radius_m:
            matched_indices.append(idx)
    return matched_indices


def min_distance_to_route(route_points: Sequence[Tuple[float, float]], point: Tuple[float, float]) -> float:
    if not route_points:
        return float("inf")
    route_lat = np.array([p[0] for p in route_points])
    route_lng = np.array([p[1] for p in route_points])
    dlat, dlng = point
    dists = haversine_m(route_lat, route_lng, np.full_like(route_lat, dlat), np.full_like(route_lng, dlng))
    return float(np.min(dists))
