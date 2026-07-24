"""Liner Search API 프록시 — 주변 안전문서 웹 검색.

프론트엔드에 API 키를 노출하지 않기 위해 백엔드에서만 호출한다.
기존 경로·점수·문서 업로드·Solar 파이프라인과 무관하다.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .config import settings

LINER_SEARCH_URL = "https://platform.liner.com/api/v1/tools/search/web"
REQUEST_TIMEOUT_S = 8

# Liner date_range는 past_day|past_week|past_month|past_year 만 지원 → 3개월 요청은 past_year + 쿼리 문구로 제한
PRIMARY_DATE_RANGE = "past_year"

# 블로그·커뮤니티·SNS·뉴스 요약성 도메인 제외
_BLOCKED_HOST_PARTS = (
    "instagram.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
    "blog.naver.com",
    "m.blog.naver.com",
    "tistory.com",
    "brunch.co.kr",
    "medium.com",
    "cafe.naver.com",
    "cafe.daum.net",
    "dcinside.com",
    "reddit.com",
    "namu.wiki",
    "theqoo.net",
    "clien.net",
    "fmkorea.com",
    "news.nate.com",
    "news.daum.net",
    "news.naver.com",
    "n.news.naver.com",
    "news.google.com",
    "msn.com",
    "yahoo.com",
)

# 공식 출처 가산 (정렬 시 앞쪽 우선)
_OFFICIAL_HOST_PARTS = (
    "go.kr",
    "seoul.go.kr",
    "gangnam.go.kr",
    "koroad.or.kr",
    "molit.go.kr",
    "mois.go.kr",
    "police.go.kr",
)

router = APIRouter(prefix="/api/liner", tags=["liner"])


class SafetyDocsRequest(BaseModel):
    region: str = Field(..., min_length=1)


def _build_query(region: str) -> str:
    r = region.strip()
    return (
        f"{r} 도로공사 통행제한 보행자 안전 관련 최근 3개월 공고를 찾아줘.\n"
        "\n"
        "조건:\n"
        "- 해당 자치구청 고시·공고, 서울시, 도로교통공단 등 공식 출처 우선\n"
        "- 블로그·커뮤니티·뉴스 요약 사이트 제외\n"
        "- 각 항목마다: 제목 / 발행일 / 기관명 / 원문 URL\n"
        "- 공사 구간의 도로명 주소가 본문에 있으면 함께 표기\n"
        "- 발행일 최신순 정렬\n"
        "- 요약이나 해설 없이 목록만"
    )


def _hostname_of(item: dict[str, Any]) -> str:
    host = str(item.get("hostname") or "").strip().lower()
    if host:
        return host.lstrip(".")
    url = str(item.get("url") or "")
    try:
        return (urlparse(url).hostname or "").lower().lstrip(".")
    except Exception:
        return ""


def _is_blocked(hostname: str) -> bool:
    if not hostname:
        return False
    return any(part in hostname for part in _BLOCKED_HOST_PARTS)


def _is_official(hostname: str) -> bool:
    if not hostname:
        return False
    return any(part in hostname for part in _OFFICIAL_HOST_PARTS)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y.%m.%d", 10), ("%Y/%m/%d", 10)):
        try:
            return datetime.strptime(text[:n], fmt)
        except ValueError:
            pass
    if "T" in text:
        try:
            return datetime.strptime(text[:19].rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
    m = re.search(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _normalize_results(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "hostname": str(item.get("hostname") or ""),
            "favicon_url": str(item.get("favicon_url") or "") or None,
            "description": str(item.get("description") or ""),
            "date": str(item.get("date") or "") or None,
        }
        if not row["hostname"]:
            row["hostname"] = _hostname_of(row)
        out.append(row)
    return out


def _filter_and_sort(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = [r for r in results if not _is_blocked(_hostname_of(r))]
    cleaned.sort(
        key=lambda r: (
            0 if _is_official(_hostname_of(r)) else 1,
            # 최신순: 날짜 없는 항목은 뒤로
            -(_parse_date(r.get("date")).timestamp() if _parse_date(r.get("date")) else 0.0),
        )
    )
    return cleaned


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
        "max_results": 15,
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
    return _filter_and_sort(results), None


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
    results, err = _call_liner(query, date_range=PRIMARY_DATE_RANGE)
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
