from app.services.routing import (
    _clean_route_polyline,
    _coords_from_tmap_features,
    _densify_route_coordinates,
    _remove_polyline_spikes,
)


def test_coords_sorted_by_index_and_deduped():
    features = [
        {
            "geometry": {
                "type": "LineString",
                "coordinates": [[127.05, 37.501], [127.051, 37.501]],
            },
            "properties": {"index": 3, "distance": 90, "time": 80, "description": "역삼로, 90m"},
        },
        {
            "geometry": {"type": "Point", "coordinates": [127.049, 37.5]},
            "properties": {"index": 0, "pointType": "SP"},
        },
        {
            "geometry": {
                "type": "LineString",
                # 끝점이 다음 구간의 시작점과 동일 → 이어붙일 때 한 번만 유지
                "coordinates": [[127.049, 37.5], [127.05, 37.501], [127.05, 37.501]],
            },
            "properties": {"index": 1, "distance": 100, "time": 90, "description": "선릉로, 100m"},
        },
    ]

    coords, distance, time, main_road = _coords_from_tmap_features(features)

    assert coords[0] == (37.5, 127.049)
    assert coords[-1] == (37.501, 127.051)
    assert len(coords) >= 2
    assert distance == 190
    assert time == 170
    assert main_road == 190


def test_remove_polyline_spikes_drops_intersection_spur():
    # 남하 경로 중 사거리에서 서쪽으로 잠깐 튀었다 돌아오는 꼭짓점
    coords = [
        (37.5012, 127.0500),
        (37.5008, 127.0500),
        (37.5006, 127.0497),  # spike tip
        (37.5004, 127.0500),
        (37.5000, 127.0500),
    ]
    cleaned = _remove_polyline_spikes(coords)
    assert (37.5006, 127.0497) not in cleaned
    assert cleaned[0] == coords[0]
    assert cleaned[-1] == coords[-1]


def test_remove_polyline_spikes_keeps_real_corner():
    # 정상적인 직각 회전은 유지
    coords = [
        (37.5010, 127.0500),
        (37.5000, 127.0500),
        (37.5000, 127.0515),
    ]
    assert _remove_polyline_spikes(coords) == coords


def test_clean_route_collapses_alley_and_keeps_main_corridor():
    # 남하 중 동쪽 골목으로 나갔다가 같은 길로 되돌아와 계속 남하
    coords = [
        (37.5015, 127.0500),  # main
        (37.5010, 127.0500),  # junction
        (37.5010, 127.0504),
        (37.5010, 127.0508),
        (37.5010, 127.0512),  # tip (U-turn)
        (37.5010, 127.0508),
        (37.5010, 127.0504),
        (37.5010, 127.0500),  # back to junction
        (37.5005, 127.0500),  # continue south
        (37.5000, 127.0500),
    ]
    cleaned = _clean_route_polyline(coords)
    assert (37.5010, 127.0512) not in cleaned
    assert (37.5010, 127.0508) not in cleaned
    assert cleaned[0] == coords[0]
    assert cleaned[-1] == coords[-1]
    # 골목이 접히면 남북 본선 위주로 짧아진다
    assert len(cleaned) <= 5


def test_densify_expands_sparse_two_point_route(monkeypatch):
    from app.services import routing

    sparse = [(37.5012, 127.0499), (37.4989686, 127.0525688)]
    dense = [
        (37.5012, 127.0499),
        (37.5009, 127.0503),
        (37.5004, 127.0510),
        (37.4995, 127.0520),
        (37.4989686, 127.0525688),
    ]

    monkeypatch.setattr(routing.settings, "tmap_route_densify_enabled", True)
    monkeypatch.setattr(routing.settings, "tmap_route_densify_min_leg_m", 25.0)
    monkeypatch.setattr(
        routing,
        "_fetch_tmap_pedestrian_data",
        lambda *args, **kwargs: {
            "features": [
                {
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lng, lat] for lat, lng in dense],
                    },
                    "properties": {"index": 1, "distance": 400, "time": 360},
                }
            ]
        },
    )

    result = _densify_route_coordinates(sparse, "4")
    assert len(result) > len(sparse)


def test_night_academy_commute_uses_tmap_pedestrian_not_fixed_demo():
    from app.services.routing import get_route_candidates

    candidates = get_route_candidates(
        (37.4989686, 127.0525688),
        (37.5012, 127.0499),
        force_mock=True,
        origin_name="필수학학원",
        destination_name="개나리SK뷰5차아파트",
    )
    assert candidates
    assert candidates[0].source == "MOCK_ROUTING"


def test_academy_home_names_do_not_trigger_special_demo_route():
    from app.services.routing import get_route_candidates

    candidates = get_route_candidates(
        (37.4995, 127.0530),
        (37.5015, 127.0495),
        force_mock=True,
        origin_name="필수학학원",
        destination_name="개나리SK뷰5차아파트",
    )
    assert all(c.id != "route-demo-night-main" for c in candidates)
    assert all(c.source == "MOCK_ROUTING" for c in candidates)


def test_has_backtrack_detects_meaningful_waste():
    from app.services.routing import _has_backtrack, _max_backtrack_waste_m

    # ~150m 나갔다가 같은 점으로 되돌아오는 via 아티팩트
    coords = [(37.5000, 127.0500)]
    for i in range(1, 16):
        coords.append((37.5000 + i * 0.0001, 127.0500))  # ~11m steps north
    for i in range(14, -1, -1):
        coords.append((37.5000 + i * 0.0001, 127.0500))
    assert _max_backtrack_waste_m(coords) > 100
    assert _has_backtrack(coords) is True


def test_has_backtrack_ignores_short_snap_loop():
    from app.services.routing import _has_backtrack, _max_backtrack_waste_m

    # 본선 남하 중 ~20m 튀었다 돌아오는 스냅급 스파이크
    coords = [
        (37.5020, 127.0500),
        (37.5015, 127.0500),
        (37.5010, 127.0500),  # junction
        (37.5010, 127.05018),  # ~16m east
        (37.5010, 127.0500),  # back
        (37.5005, 127.0500),
        (37.5000, 127.0500),
    ]
    assert _max_backtrack_waste_m(coords) < 60
    assert _has_backtrack(coords) is False


def test_has_backtrack_clean_path():
    from app.services.routing import _has_backtrack

    coords = [
        (37.5012, 127.0499),
        (37.5008, 127.0502),
        (37.5004, 127.0505),
        (37.5000, 127.0508),
        (37.4995, 127.0512),
    ]
    assert _has_backtrack(coords) is False


def test_drop_backtrack_keeps_main_drops_detour():
    from app.services.routing import RouteCandidateRaw, _drop_backtracking_candidates

    # 긴 왕복 스파이크 (낭비 > 임계)
    spike = [(37.5000, 127.0500)]
    for i in range(1, 16):
        spike.append((37.5000 + i * 0.0001, 127.0500))
    for i in range(14, -1, -1):
        spike.append((37.5000 + i * 0.0001, 127.0500))
    clean = [
        (37.5012, 127.0499),
        (37.5008, 127.0502),
        (37.5004, 127.0505),
        (37.4995, 127.0512),
    ]
    main = RouteCandidateRaw(
        id="route-tmap-pedestrian-main",
        label="main",
        coordinates=spike,
        distance_m=100,
        duration_s=90,
        source="TEST",
    )
    detour = RouteCandidateRaw(
        id="route-tmap-pedestrian-avoid-hotspot-1-via",
        label="detour",
        coordinates=spike,
        distance_m=120,
        duration_s=100,
        source="TEST",
    )
    alt = RouteCandidateRaw(
        id="route-tmap-pedestrian-alt",
        label="alt",
        coordinates=clean,
        distance_m=110,
        duration_s=95,
        source="TEST",
    )
    kept = _drop_backtracking_candidates([main, detour, alt])
    ids = [c.id for c in kept]
    assert "route-tmap-pedestrian-main" in ids
    assert "route-tmap-pedestrian-alt" in ids
    assert "route-tmap-pedestrian-avoid-hotspot-1-via" not in ids


def test_polyline_hash_dedupes_identical_search_options():
    from app.services.routing import RouteCandidateRaw, _deduplicate_candidates

    coords = [
        (37.5012, 127.0499),
        (37.5008, 127.0502),
        (37.5004, 127.0505),
        (37.4995, 127.0512),
    ]
    main = RouteCandidateRaw(
        id="route-tmap-pedestrian-main",
        label="main",
        coordinates=coords,
        distance_m=400,
        duration_s=360,
        source="TEST",
    )
    opt0 = RouteCandidateRaw(
        id="route-tmap-pedestrian-opt0",
        label="opt0",
        coordinates=list(coords),
        distance_m=402,
        duration_s=365,
        source="TEST",
    )
    different = RouteCandidateRaw(
        id="route-tmap-pedestrian-opt10",
        label="opt10",
        coordinates=[
            (37.5012, 127.0499),
            (37.5010, 127.0510),
            (37.4995, 127.0512),
        ],
        distance_m=480,
        duration_s=420,
        source="TEST",
    )
    kept = _deduplicate_candidates([main, opt0, different])
    ids = [c.id for c in kept]
    assert ids[0] == "route-tmap-pedestrian-main"
    assert "route-tmap-pedestrian-opt0" not in ids
    assert "route-tmap-pedestrian-opt10" in ids


def test_access_warning_threshold():
    from app.services.routing import access_warning_for_ratio

    assert access_warning_for_ratio(2.4) is None
    assert access_warning_for_ratio(2.6) is not None


def test_geometric_overlap_drops_near_duplicate():
    from app.services.routing import RouteCandidateRaw, _deduplicate_candidates

    base_coords = [
        (37.5012, 127.0499),
        (37.5008, 127.0502),
        (37.5004, 127.0505),
        (37.5000, 127.0508),
        (37.4995, 127.0512),
    ]
    # 한 점만 살짝 비켜 — 거리·시간은 다르지만 기하적으로 거의 동일
    near_coords = [
        (37.5012, 127.0499),
        (37.50081, 127.05021),
        (37.50041, 127.05051),
        (37.50001, 127.05081),
        (37.4995, 127.0512),
    ]
    far_coords = [
        (37.5012, 127.0499),
        (37.5010, 127.0515),
        (37.5000, 127.0520),
        (37.4995, 127.0512),
    ]
    # 우회: 기본과 상당 부분 겹치지만 via 후보는 유지해야 함
    detour_coords = [
        (37.5012, 127.0499),
        (37.5008, 127.0502),
        (37.5006, 127.0508),
        (37.5004, 127.0505),
        (37.5000, 127.0508),
        (37.4995, 127.0512),
    ]
    main = RouteCandidateRaw(
        id="route-tmap-pedestrian-main",
        label="main",
        coordinates=base_coords,
        distance_m=400,
        duration_s=360,
        source="TEST",
    )
    twin = RouteCandidateRaw(
        id="route-tmap-pedestrian-opt0",
        label="opt0",
        coordinates=near_coords,
        distance_m=420,
        duration_s=380,
        source="TEST",
    )
    other = RouteCandidateRaw(
        id="route-tmap-pedestrian-opt10",
        label="opt10",
        coordinates=far_coords,
        distance_m=500,
        duration_s=450,
        source="TEST",
    )
    detour = RouteCandidateRaw(
        id="route-tmap-pedestrian-avoid-hotspot-1",
        label="안전 우회",
        coordinates=detour_coords,
        distance_m=480,
        duration_s=430,
        source="TEST",
    )
    kept = _deduplicate_candidates([main, twin, other, detour])
    ids = [c.id for c in kept]
    assert "route-tmap-pedestrian-main" in ids
    assert "route-tmap-pedestrian-opt0" not in ids
    assert "route-tmap-pedestrian-opt10" in ids
    assert "route-tmap-pedestrian-avoid-hotspot-1" in ids


def test_compare_note_for_single_candidate():
    from app.services.routing import RouteBuildMeta, compare_note_for_candidates

    assert compare_note_for_candidates(2) is None
    assert "1개만 표시" in (compare_note_for_candidates(1, RouteBuildMeta()) or "")
    assert "되돌아" in (
        compare_note_for_candidates(1, RouteBuildMeta(detour_rejected_backtrack=True)) or ""
    )
    assert "위험을 줄이지" in (
        compare_note_for_candidates(1, RouteBuildMeta(detour_rejected_ineffective=True)) or ""
    )
    assert "다른 길이 없습니다" in (
        compare_note_for_candidates(1, RouteBuildMeta(option_paths=3, unique_after_dedupe=1)) or ""
    )


def test_force_densify_waypoints_fills_from_tmap(monkeypatch):
    from app.services import routing

    waypoints = [
        (37.5012, 127.0499),
        (37.5000, 127.0502),
        (37.4989686, 127.0525688),
    ]
    dense_leg = [
        (37.5012, 127.0499),
        (37.5008, 127.0500),
        (37.5004, 127.0501),
        (37.5000, 127.0502),
    ]

    def fake_fetch(origin, destination, *, search_option, pass_list=None):
        return {
            "features": [
                {
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lng, lat] for lat, lng in dense_leg],
                    },
                    "properties": {"index": 1, "distance": 120, "time": 100},
                }
            ]
        }

    monkeypatch.setattr(routing, "_fetch_tmap_pedestrian_data", fake_fetch)
    result = routing._force_densify_waypoints(waypoints[:2], "4")
    assert len(result) >= 3
    assert result[0] == waypoints[0]
