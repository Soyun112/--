from app.services.routing import _coords_from_tmap_features, _remove_polyline_spikes


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

    assert coords == [
        (37.5, 127.049),
        (37.501, 127.05),
        (37.501, 127.051),
    ]
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
