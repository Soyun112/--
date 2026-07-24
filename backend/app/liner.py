"""Liner Search API 프록시 — 주변 안전문서 웹 검색.

프론트엔드에 API 키를 노출하지 않기 위해 백엔드에서만 호출한다.
기존 경로·점수·문서 업로드·Solar 파이프라인과 무관하다.
"""
from __future__ import annotations

from typing import Any

import requests
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .config import settings

LINER_SEARCH_URL = "https://platform.liner.com/api/v1/tools/search/web"
REQUEST_TIMEOUT_S = 8

router = APIRouter(prefix="/api/liner", tags=["liner"])


class SafetyDocsRequest(BaseModel):
    region: str = Field(..., min_length=1)


def _build_query(region: str) -> str:
    return f"{region.strip()} 도로공사 통행제한 공사 안내 공고 안전"


def _normalize_results(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "hostname": str(item.get("hostname") or ""),
                "favicon_url": str(item.get("favicon_url") or "") or None,
                "description": str(item.get("description") or ""),
                "date": str(item.get("date") or "") or None,
            }
        )
    return out


def _error_message(status_code: int | None) -> str:
    if status_code == 401:
        return "API 키가 유효하지 않습니다"
    if status_code == 402:
        return "크레딧이 부족합니다"
    if status_code == 429:
        return "요청이 많습니다. 잠시 후 다시 시도해주세요"
    return "검색에 실패했습니다"


def _call_liner(query: str, *, date_range: str | None) -> tuple[list[dict[str, Any]] | None, str | None]:
    """성공 시 (results, None), 실패 시 (None, error_message)."""
    api_key = settings.liner_api_key
    if not api_key:
        return None, "API 키가 유효하지 않습니다"

    body: dict[str, Any] = {
        "query": query,
        "max_results": 10,
        "country_code": "kr",
        "lang": "ko",
    }
    if date_range:
        body["date_range"] = date_range

    try:
        res = requests.post(
            LINER_SEARCH_URL,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=REQUEST_TIMEOUT_S,
        )
    except (requests.Timeout, requests.RequestException):
        return None, "검색에 실패했습니다"

    if res.status_code != 200:
        return None, _error_message(res.status_code)

    try:
        data = res.json()
    except ValueError:
        return None, "검색에 실패했습니다"

    results = _normalize_results(data.get("results") if isinstance(data, dict) else None)
    return results, None


@router.post("/safety-docs")
def search_safety_docs(payload: SafetyDocsRequest) -> dict[str, Any]:
    region = payload.region.strip()
    if not region:
        return {
            "region": payload.region,
            "results": [],
            "fallback_used": False,
            "error": "검색에 실패했습니다",
        }

    query = _build_query(region)
    results, err = _call_liner(query, date_range="past_month")
    if err is not None:
        return {
            "region": region,
            "results": [],
            "fallback_used": False,
            "error": err,
        }

    fallback_used = False
    if len(results) < 2:
        fallback_used = True
        fb_results, fb_err = _call_liner(query, date_range=None)
        if fb_err is not None:
            return {
                "region": region,
                "results": [],
                "fallback_used": True,
                "error": fb_err,
            }
        results = fb_results

    return {
        "region": region,
        "results": results,
        "fallback_used": fallback_used,
    }
