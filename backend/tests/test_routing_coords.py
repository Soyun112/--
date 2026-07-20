from app.services.routing import _coords_from_tmap_features


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
