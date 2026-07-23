"""bbox 사전 필터로 buffer_match가 전체 시설을 스캔하지 않는지 확인."""
from app.services.geo import buffer_match, route_bbox_with_margin


def test_buffer_match_bbox_skips_far_points():
    route = [(37.50, 127.04), (37.501, 127.041)]
    # 경로 근처 1개 + 멀리(수 km) 998개
    near = (37.5002, 127.0402)
    data = [near] + [(37.0 + i * 0.001, 126.0) for i in range(200)]
    matched = buffer_match(route, data, radius_m=40.0)
    assert matched == [0]


def test_route_bbox_margin_50m():
    route = [(37.5, 127.0), (37.501, 127.001)]
    min_lat, max_lat, min_lng, max_lng = route_bbox_with_margin(route, 50.0)
    assert min_lat < 37.5
    assert max_lat > 37.501
    assert (max_lat - min_lat) < 0.01  # ~50m*2 + route span, not 0.004deg*2 old style gone
