"""Solar 부모 리포트 프롬프트 — 0 포함 수치 전달·JSON 파싱."""

from app.models import LatLng, RouteCandidate, SafetyFeatures
from app.services.solar import (
    PARENT_SYSTEM_PROMPT,
    build_parent_user_prompt,
    _extract_json_object,
    _mock_parent_structured,
)


def _cand(**feat_kw):
    base = dict(
        distance_km=0.8,
        cctv_count=15,
        cctv_density=0.0,
        streetlight_count=0,
        accident_hotspot_count=0,
        crime_risk_proxy=0,
        child_zone_coverage_pct=49.4,
        doc_risk_count=0,
        doc_safety_count=0,
        matched_documents=[],
        guardian_house_count=0,
        speed_camera_count=0,
        safety_facility_cctv_count=0,
        safety_facility_streetlight_count=0,
        safety_bell_count=0,
        emergency112_count=0,
        emergency_pole_count=0,
    )
    base.update(feat_kw)
    f = SafetyFeatures(**base)
    return RouteCandidate(
        id="main",
        coordinates=[LatLng(lat=37.5, lng=127.0), LatLng(lat=37.501, lng=127.001)],
        distance_m=800,
        duration_s=600,
        features=f,
        safety_score=55.3,
        is_recommended=True,
        source="test",
    )


def test_parent_system_prompt_has_core_rules():
    assert "추측 금지" in PARENT_SYSTEM_PROMPT
    assert "중앙값이 60점" in PARENT_SYSTEM_PROMPT
    assert "뛰어" in PARENT_SYSTEM_PROMPT or "좌우" in PARENT_SYSTEM_PROMPT


def test_user_prompt_includes_zeros():
    prompt = build_parent_user_prompt(_cand(), {"is_night": False, "period_label": "낮"})
    assert "안심귀갓길 CCTV: 0대" in prompt
    assert "안심귀갓길 보안등: 0개" in prompt
    assert "보호구역 보유 CCTV: 15대" in prompt
    assert "교통사고다발지역: 0곳" in prompt
    assert "55.3점" in prompt
    assert "중앙값 60점" in prompt
    assert "시간대: 낮" in prompt


def test_mock_structured_skips_zero_good_points():
    data = _mock_parent_structured(_cand(), {"is_night": False})
    assert data["summary"]
    assert "60" in data["summary"]
    joined = " ".join(data["good_points"])
    assert "15" in joined or "보호구역" in joined
    assert "안심귀갓길 CCTV가 0" not in joined
    assert data["caution_points"] == []
    assert data["night_note"] == ""


def test_extract_json_from_fenced():
    raw = '```json\n{"summary": "ok", "good_points": [], "caution_points": [], "night_note": ""}\n```'
    parsed = _extract_json_object(raw)
    assert parsed["summary"] == "ok"
