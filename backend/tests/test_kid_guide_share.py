"""짧은 공유 ID 발급·조회 테스트."""
from __future__ import annotations

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
