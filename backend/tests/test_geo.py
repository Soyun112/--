import numpy as np

from app.services.geo import buffer_match, haversine_m, resample_route, route_length_m


def test_haversine_known_distance():
    # 서울시청(37.5663,126.9779) - 서울역(37.5547,126.9707) 약 1.3~1.4km
    d = haversine_m(np.array([37.5663]), np.array([126.9779]), np.array([37.5547]), np.array([126.9707]))[0]
    assert 1000 < d < 1700


def test_haversine_zero_distance():
    d = haversine_m(np.array([37.5]), np.array([127.0]), np.array([37.5]), np.array([127.0]))[0]
    assert d == 0


def test_resample_route_preserves_endpoints():
    coords = [(37.4995, 127.0370), (37.5035, 127.0410)]
    resampled = resample_route(coords, interval_m=20)
    assert resampled[0] == coords[0]
    assert resampled[-1] == coords[-1]
    assert len(resampled) > 2


def test_resample_route_length_matches_original():
    coords = [(37.4995, 127.0370), (37.4995, 127.0410), (37.5035, 127.0410)]
    original_len = route_length_m(coords)
    resampled = resample_route(coords, interval_m=20)
    resampled_len = route_length_m(resampled)
    assert abs(original_len - resampled_len) < 5  # 재샘플링으로 인한 오차는 미미해야 함


def test_buffer_match_finds_nearby_point():
    # buffer_match는 주어진 점 목록에 대해서만 최소 거리를 계산하므로,
    # 실제 사용처(scoring.py)와 동일하게 먼저 리샘플링해 선분 위 점들을 촘촘히 확보한다.
    route_points = resample_route([(37.4995, 127.0370), (37.4995, 127.0410)], interval_m=20)
    data_points = [(37.4995, 127.0390), (37.6, 127.2)]  # 첫 번째는 경로 위, 두 번째는 매우 멀리
    matched = buffer_match(route_points, data_points, radius_m=40)
    assert matched == [0]


def test_buffer_match_empty_inputs():
    assert buffer_match([], [(1, 1)], 40) == []
    assert buffer_match([(1, 1)], [], 40) == []
