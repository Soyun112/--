import pytest

from app import db
from app.config import settings
from app.services import public_data
from app.services.document_pipeline import ingest_document
from app.services.routing import RouteCandidateRaw, _deduplicate_candidates, get_route_candidates
from app.services.scoring import score_candidates

ORIGIN = (37.4995, 127.0370)
DESTINATION = (37.5035, 127.0410)


@pytest.fixture(autouse=True, scope="module")
def seeded_db():
    db.init_db()
    public_data.ingest_all()
    if not public_data.get_doc_risk_points():
        sample_path = settings.data_dir / "sample_documents" / "sample_report.md"
        try:
            ingest_document(sample_path.read_bytes(), "OO구_2024_통학로_안전진단_보고서(SAMPLE).pdf")
        except Exception:
            # 오프라인/Upstage 실패 시에도 점수 테스트는 공공데이터만으로 진행
            pass
    yield


def test_force_mock_override_always_uses_mock_routing():
    # .env에 실제 키가 있는 개발 환경에서도, force_mock=True 요청은 항상 MOCK 경로를 사용해야 한다
    # (데모 중 네트워크 문제와 무관하게 오프라인 시연이 가능함을 보장).
    raw_candidates = get_route_candidates(ORIGIN, DESTINATION, force_mock=True)
    assert all(c.source == "MOCK_ROUTING" for c in raw_candidates)


def test_duplicate_detour_keeps_only_base_route_and_orders_alternatives():
    shared_coordinates = [ORIGIN, DESTINATION]
    direct = RouteCandidateRaw(
        id="route-direct",
        label="기본 경로",
        coordinates=shared_coordinates,
        distance_m=600,
        duration_s=540,
        source="TEST",
    )
    duplicate_detour = RouteCandidateRaw(
        id="route-via-a",
        label="우회 경로 A",
        coordinates=[ORIGIN, (37.5010, 127.0370), DESTINATION],
        distance_m=600,
        duration_s=540,
        source="TEST",
    )
    detour_b = RouteCandidateRaw(
        id="route-via-b",
        label="우회 경로 B",
        coordinates=[ORIGIN, (ORIGIN[0], DESTINATION[1]), DESTINATION],
        distance_m=900,
        duration_s=810,
        source="TEST",
    )

    candidates = _deduplicate_candidates([detour_b, duplicate_detour, direct])

    assert [candidate.id for candidate in candidates] == ["route-direct", "route-via-b"]


def test_hotspot_and_zone_move_absolute_score():
    """점 사건(사고다발)은 count 감점, 보호구역 비율은 가점."""
    from app.models import SafetyFeatures
    from app.services.scoring import absolute_score

    base = SafetyFeatures(
        distance_km=0.5,
        cctv_count=0,
        cctv_density=0.0,
        child_zone_coverage_pct=0.0,
        accident_hotspot_count=0,
        crime_risk_proxy=0.0,
        guardian_house_count=0,
        streetlight_count=0,
        streetlight_density=0.0,
        speed_camera_count=0,
        doc_risk_count=0,
        doc_safety_count=0,
    )
    safe = absolute_score(base, is_night=False, walk_minutes=8.0)
    risky = absolute_score(
        base.model_copy(update={"accident_hotspot_count": 1}),
        is_night=False,
        walk_minutes=8.0,
    )
    zoned = absolute_score(
        base.model_copy(update={"child_zone_coverage_pct": 50.0}),
        is_night=False,
        walk_minutes=8.0,
    )
    assert risky < safe
    assert zoned > safe


def test_recommended_route_is_unique():
    raw_candidates = get_route_candidates(ORIGIN, DESTINATION, force_mock=True)
    scored = score_candidates(raw_candidates)
    recommended = [s for s in scored if s.is_recommended]
    assert len(recommended) == 1


def test_saturate_and_demo_od_score_shape():
    from app.models import SafetyFeatures
    from app.services.scoring import absolute_score, saturate

    assert abs(saturate(0, 1.5) - 0.0) < 1e-9
    assert abs(saturate(1.5, 1.5) - 0.5) < 1e-9

    # zone_cctv는 count(나누지 않음), coverage는 감쇠 비율
    f = SafetyFeatures(
        distance_km=0.43,
        cctv_count=7,
        cctv_density=0.0,
        child_zone_coverage_pct=35.0,
        accident_hotspot_count=1,
        crime_risk_proxy=0.0,
        guardian_house_count=1,
        streetlight_count=0,
        streetlight_density=0.0,
        speed_camera_count=1,
        doc_risk_count=0,
        doc_safety_count=0,
        zone_cctv_count=7,
        safety_facility_cctv_count=0,
    )
    score = absolute_score(f, is_night=False, detour_penalty=0.0, walk_minutes=10.0)
    # 확정 k 기준 ≈ zone_cctv + coverage + guardian + camera - accident
    assert 55.0 <= score <= 70.0


def test_safety_score_within_bounds():
    raw_candidates = get_route_candidates(ORIGIN, DESTINATION, force_mock=True)
    scored = score_candidates(raw_candidates)
    for s in scored:
        assert 0 <= s.safety_score <= 100


def test_soft_clip_preserves_rank_above_90():
    from app.models import SafetyFeatures
    from app.services.scoring import absolute_score

    # 가점이 과도하게 쌓여도 100으로 뭉개지지 않고 상단 압축
    rich = SafetyFeatures(
        distance_km=0.5,
        cctv_count=0,
        cctv_density=0.0,
        child_zone_coverage_pct=80.0,
        accident_hotspot_count=0,
        crime_risk_proxy=0.0,
        guardian_house_count=5,
        streetlight_count=0,
        streetlight_density=0.0,
        speed_camera_count=8,
        doc_risk_count=0,
        doc_safety_count=0,
        zone_cctv_count=20,
        safety_facility_cctv_count=10,
        safety_facility_streetlight_count=15,
        emergency_pole_count=5,
    )
    lean = SafetyFeatures(
        distance_km=0.5,
        cctv_count=0,
        cctv_density=0.0,
        child_zone_coverage_pct=80.0,
        accident_hotspot_count=0,
        crime_risk_proxy=0.0,
        guardian_house_count=4,
        streetlight_count=0,
        streetlight_density=0.0,
        speed_camera_count=7,
        doc_risk_count=0,
        doc_safety_count=0,
        zone_cctv_count=18,
        safety_facility_cctv_count=8,
        safety_facility_streetlight_count=12,
        emergency_pole_count=4,
    )
    a = absolute_score(rich, is_night=False, walk_minutes=8.0)
    b = absolute_score(lean, is_night=False, walk_minutes=8.0)
    assert a <= 100.0
    assert b <= 100.0
    assert a > b
    assert a < 100.0 or b < a  # 둘 다 100으로 뭉개지지 않음
