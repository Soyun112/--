"""위치도 정규식·주소 재조립 단위 테스트."""
from app.services.doc_address import (
    build_geocode_query,
    normalize_road_address,
    parse_location_map_segments,
)


SAMPLE = """
① 위 치  선릉로(역삼로 314 ~ 선릉로 305, 역삼2동)
② 위 치  논현로 76길(논현로 412 ~ 논현로 76길 21, 역삼2동)
③ 위 치  논현로 57길(도곡로 168 ~ 도곡로194, 도곡1동)
④ 위 치  테헤란로 108길(테헤란로 624 ~ 테헤란로 108길 42, 대치2동)
"""


def test_normalize_glued_and_spaced():
    assert normalize_road_address("도곡로194") == "도곡로 194"
    assert normalize_road_address("논현로76길21") == "논현로 76길 21"
    assert normalize_road_address("논현로 76길 21") == "논현로 76길 21"
    assert normalize_road_address("테헤란로 108길 42") == "테헤란로 108길 42"


def test_prefix_from_dong():
    q = build_geocode_query("논현로 76길 21", dong="역삼2동")
    assert q.startswith("서울특별시 강남구")
    assert "논현로 76길 21" in q


def test_parse_four_gangnam_segments():
    pts = parse_location_map_segments(SAMPLE)
    assert len(pts) == 4
    assert pts[0]["header_road"] == "선릉로"
    assert pts[0]["start_geocode_query"] == "서울특별시 강남구 역삼로 314"
    assert pts[0]["end_geocode_query"] == "서울특별시 강남구 선릉로 305"
    assert pts[0]["dong"] == "역삼2동"

    assert pts[1]["header_road"] == "논현로 76길"
    assert "논현로 412" in pts[1]["start_geocode_query"]
    assert "논현로 76길 21" in pts[1]["end_geocode_query"]

    assert pts[2]["header_road"] == "논현로 57길"
    assert "도곡로 168" in pts[2]["start_geocode_query"]
    assert "도곡로 194" in pts[2]["end_geocode_query"]
    # 헤더와 끝점 도로가 다름 — 절대 헤더+번호 합치지 않음
    assert "논현로 57길 168" not in pts[2]["start_geocode_query"]

    assert pts[3]["header_road"] == "테헤란로 108길"
    assert "테헤란로 624" in pts[3]["start_geocode_query"]
    assert "테헤란로 108길 42" in pts[3]["end_geocode_query"]
