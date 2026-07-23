"""짧은 공유 ID 발급·조회 테스트."""
from __future__ import annotations

from app.routers.share import KidGuideShareCreate
from app.services.kid_guide_share import create_share, get_share


def test_create_share_returns_short_id():
    result = create_share(
        {
            "title": "도곡렉슬아파트 → 도곡초등학교",
            "origin": "도곡렉슬아파트",
            "destination": "도곡초등학교",
            "steps": [{"keyword": "직진", "friendly": "약 10걸음 걸어가요", "is_arrive": False}],
        }
    )
    assert "id" in result
    assert 6 <= len(result["id"]) <= 10
    assert result["id"].isalnum()
    assert result["id"].islower() or any(ch.isdigit() for ch in result["id"])

    payload = get_share(result["id"])
    assert payload is not None
    assert payload["title"] == "도곡렉슬아파트 → 도곡초등학교"
    assert len(payload["steps"]) == 1


def test_get_share_missing_returns_none():
    assert get_share("zzzzzz99") is None


def test_share_schema_accepts_fractional_safety_score():
    body = KidGuideShareCreate(
        title="도곡렉슬아파트 → 도곡초등학교",
        origin="도곡렉슬아파트",
        destination="도곡초등학교",
        safety_score=51.6,
        duration_min=12.0,
        steps=[
            {
                "keyword": "직진",
                "friendly": "약 20걸음 걸어가요",
                "distance_m": 10.5,
                "is_arrive": False,
            }
        ],
    )
    dumped = body.model_dump()
    assert dumped["safety_score"] == 51.6
    assert dumped["steps"][0]["distance_m"] == 10.5


def test_create_share_preserves_fractional_score():
    stored = create_share(
        KidGuideShareCreate(
            title="도곡초등학교 → 게이트대치어학원",
            origin="도곡초등학교",
            destination="게이트대치어학원",
            safety_score=74.4,
            duration_min=8,
            steps=[
                {
                    "keyword": "왼쪽으로 가기",
                    "friendly": "약 40걸음 걸어가요",
                    "distance_m": 20.2,
                    "is_arrive": False,
                },
                {"keyword": "도착! 잘했어요", "is_arrive": True},
            ],
        ).model_dump()
    )
    payload = get_share(stored["id"])
    assert payload is not None
    assert payload["safety_score"] == 74.4
    assert payload["steps"][0]["distance_m"] == 20.2


def test_demo_scenario_share_payloads_accepted():
    """발표용 4개 OD — 소수 점수로 링크 저장·조회가 깨지지 않는지."""
    demos = [
        ("도곡렉슬아파트", "도곡초등학교", 51.6),
        ("도곡초등학교", "게이트대치어학원", 74.4),
        ("게이트대치어학원", "도곡렉슬아파트", 48.2),
        ("깊은생각수학학원", "도곡초등학교", 62.8),
    ]
    for origin, destination, score in demos:
        body = KidGuideShareCreate(
            title=f"{origin} → {destination}",
            origin=origin,
            destination=destination,
            safety_score=score,
            duration_min=10,
            steps=[
                {"keyword": "직진", "distance_m": 15.5, "is_arrive": False},
                {"keyword": "도착! 잘했어요", "is_arrive": True},
            ],
        )
        result = create_share(body.model_dump())
        payload = get_share(result["id"])
        assert payload is not None
        assert payload["safety_score"] == score
        assert payload["title"] == f"{origin} → {destination}"
