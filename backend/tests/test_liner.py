"""Liner 안전문서 검색 프록시 단위 테스트 — 기존 파이프라인과 무관."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _ok_response(results: list) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"request_id": "t", "results": results, "total_count": len(results)}
    return mock


def test_safety_docs_missing_key_returns_200_with_error():
    with patch("app.liner.settings") as settings:
        settings.liner_api_key = ""
        res = client.post("/api/liner/safety-docs", json={"region": "역삼2동"})
    assert res.status_code == 200
    body = res.json()
    assert body["error"] == "API 키가 유효하지 않습니다"
    assert body["results"] == []
    assert body["fallback_used"] is False


def test_safety_docs_401_mapped():
    mock_res = MagicMock()
    mock_res.status_code = 401
    with patch("app.liner.settings") as settings, patch("app.liner.requests.post", return_value=mock_res):
        settings.liner_api_key = "bad-key"
        res = client.post("/api/liner/safety-docs", json={"region": "역삼2동"})
    assert res.status_code == 200
    assert res.json()["error"] == "API 키가 유효하지 않습니다"


def test_safety_docs_fallback_when_few_results():
    first = _ok_response([{"title": "a", "url": "https://a.example", "hostname": "a.example", "description": "d", "date": "2026-01-01", "favicon_url": ""}])
    second = _ok_response(
        [
            {"title": "a", "url": "https://a.example", "hostname": "a.example", "description": "d", "date": None, "favicon_url": None},
            {"title": "b", "url": "https://b.example", "hostname": "b.example", "description": "d2", "date": None, "favicon_url": None},
            {"title": "c", "url": "https://c.example", "hostname": "c.example", "description": "d3", "date": None, "favicon_url": None},
        ]
    )
    with patch("app.liner.settings") as settings, patch("app.liner.requests.post", side_effect=[first, second]) as post:
        settings.liner_api_key = "ok-key"
        res = client.post("/api/liner/safety-docs", json={"region": "역삼2동"})
    assert res.status_code == 200
    body = res.json()
    assert body["fallback_used"] is True
    assert len(body["results"]) == 3
    assert "error" not in body or body.get("error") is None
    assert post.call_count == 2
    # first call has date_range, second does not
    assert post.call_args_list[0].kwargs["json"]["date_range"] == "past_month"
    assert "date_range" not in post.call_args_list[1].kwargs["json"]
    assert "도로공사" in post.call_args_list[0].kwargs["json"]["query"]


def test_safety_docs_no_fallback_when_enough():
    enough = _ok_response(
        [
            {"title": "a", "url": "https://a.example", "hostname": "a", "description": "", "date": "", "favicon_url": ""},
            {"title": "b", "url": "https://b.example", "hostname": "b", "description": "", "date": "", "favicon_url": ""},
        ]
    )
    with patch("app.liner.settings") as settings, patch("app.liner.requests.post", return_value=enough) as post:
        settings.liner_api_key = "ok-key"
        res = client.post("/api/liner/safety-docs", json={"region": "도곡동"})
    assert res.status_code == 200
    body = res.json()
    assert body["fallback_used"] is False
    assert len(body["results"]) == 2
    assert post.call_count == 1


def test_existing_health_still_ok():
    res = client.get("/api/health")
    assert res.status_code == 200
