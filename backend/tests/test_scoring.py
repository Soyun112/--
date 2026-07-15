import pytest

from app import db
from app.config import settings
from app.services import public_data
from app.services.document_pipeline import ingest_document
from app.services.routing import get_route_candidates
from app.services.scoring import score_candidates

ORIGIN = (37.4995, 127.0370)
DESTINATION = (37.5035, 127.0410)


@pytest.fixture(autouse=True, scope="module")
def seeded_db():
    db.init_db()
    public_data.ingest_all()
    if not public_data.get_doc_risk_points():
        sample_path = settings.data_dir / "sample_documents" / "sample_report.md"
        ingest_document(sample_path.read_bytes(), "OO구_2024_통학로_안전진단_보고서(SAMPLE).pdf")
    yield


def test_force_mock_override_always_uses_mock_routing():
    # .env에 실제 키가 있는 개발 환경에서도, force_mock=True 요청은 항상 MOCK 경로를 사용해야 한다
    # (데모 중 네트워크 문제와 무관하게 오프라인 시연이 가능함을 보장).
    raw_candidates = get_route_candidates(ORIGIN, DESTINATION, force_mock=True)
    assert all(c.source == "MOCK_ROUTING" for c in raw_candidates)


def test_grid_route_scores_higher_than_diagonal_route():
    """샘플 데이터 시나리오(PROJECT_PLAN.md 데모 좌표): CCTV/보호구역 밀집 큰길 경로가
    사고다발지역·문서상 위험지적구간을 지나는 직선(골목) 경로보다 안전점수가 높아야 한다."""
    raw_candidates = get_route_candidates(ORIGIN, DESTINATION, force_mock=True)
    scored = score_candidates(raw_candidates)

    by_id = {s.raw.id: s for s in scored}
    direct = by_id["route-direct"]
    grid_a = by_id["route-grid-a"]

    assert grid_a.safety_score > direct.safety_score
    assert grid_a.is_recommended is True
    assert direct.features.accident_hotspot_count >= 1
    assert grid_a.features.accident_hotspot_count == 0


def test_recommended_route_is_unique():
    raw_candidates = get_route_candidates(ORIGIN, DESTINATION, force_mock=True)
    scored = score_candidates(raw_candidates)
    recommended = [s for s in scored if s.is_recommended]
    assert len(recommended) == 1


def test_safety_score_within_bounds():
    raw_candidates = get_route_candidates(ORIGIN, DESTINATION, force_mock=True)
    scored = score_candidates(raw_candidates)
    for s in scored:
        assert 0 <= s.safety_score <= 100
