"""Upstage Document Parse + Information Extract 파이프라인.

흐름: 문서(PDF/HWP/이미지) 업로드
      -> Document Parse(/v1/document-digitization, model=document-parse)로 구조화 텍스트 확보
      -> Information Extract(/v1/information-extraction, model=information-extract)로
         {location_text, risk_type, is_risk, report_date, recommendation, snippet} 스키마 추출
      -> location_text를 실제 위경도로 지오코딩(문서 내부 bbox 좌표는 지면 상 상대좌표일 뿐
         실세계 GPS가 아니므로 별도 지오코딩이 필요함)
      -> SQLite doc_risk_points 테이블에 출처(source_doc)와 함께 적재

UPSTAGE_API_KEY가 없으면 backend/app/data/sample_documents/의 샘플 파싱·추출 결과를
그대로 사용해 동일한 다운스트림(지오코딩 -> DB 적재 -> 안전점수 반영)을 시연한다.
"""
from __future__ import annotations

import base64
import json
import mimetypes
from typing import Any

import requests

from .. import db
from ..config import settings

DOCUMENT_DIGITIZATION_URL = "https://api.upstage.ai/v1/document-digitization"
INFORMATION_EXTRACTION_URL = "https://api.upstage.ai/v1/information-extraction"

RISK_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "school_route_safety_report",
        "schema": {
            "type": "object",
            "properties": {
                "risk_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "location_text": {"type": "string", "description": "위험/안전 지점의 주소 또는 위치 설명 (예: 'OO초등학교 서측 골목 교차로')"},
                            "risk_type": {"type": "string", "description": "위험 유형 또는 안전조치 유형 (예: '무단횡단 위험', 'CCTV 추가설치 완료')"},
                            "is_risk": {"type": "boolean", "description": "위험 지적 사항이면 true, 완료된 안전조치/개선사항이면 false"},
                            "report_date": {"type": "string", "description": "지적/보고 일자 (YYYY-MM-DD)"},
                            "recommendation": {"type": "string", "description": "개선권고사항"},
                            "snippet": {"type": "string", "description": "판단 근거가 되는 원문 문장 1~2개"},
                        },
                    },
                }
            },
        },
    },
}


def _load_sample_extract() -> dict[str, Any]:
    path = settings.data_dir / "sample_documents" / "sample_report_extract.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_document(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """Document Parse: 문서를 markdown 구조로 변환."""
    if settings.upstage_mock:
        sample_path = settings.data_dir / "sample_documents" / "sample_report.md"
        return {"markdown": sample_path.read_text(encoding="utf-8"), "mock": True}

    resp = requests.post(
        DOCUMENT_DIGITIZATION_URL,
        headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
        files={"document": (filename, file_bytes)},
        data={"model": "document-parse", "output_formats": json.dumps(["markdown"])},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return {"markdown": data.get("content", {}).get("markdown", ""), "mock": False, "raw": data}


def extract_risk_points(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """Information Extract: RISK_SCHEMA로 구조화된 위험/안전 지점 목록을 추출."""
    if settings.upstage_mock:
        sample = _load_sample_extract()
        return {"risk_points": sample["risk_points"], "mock": True, "already_geocoded": True}

    mime, _ = mimetypes.guess_type(filename)
    mime = mime or "application/octet-stream"
    b64 = base64.b64encode(file_bytes).decode("utf-8")

    resp = requests.post(
        INFORMATION_EXTRACTION_URL,
        headers={"Authorization": f"Bearer {settings.upstage_api_key}", "Content-Type": "application/json"},
        json={
            "model": "information-extract",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}],
                }
            ],
            "response_format": RISK_SCHEMA,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return {"risk_points": parsed.get("risk_points", []), "mock": False, "already_geocoded": False}


# 실제 서비스에서는 Tmap/카카오 POI·주소 검색 API로 대체할 지오코딩 스텁.
# 팀이 지오코딩 API 키를 연동하기 전까지는, 문서에서 자주 등장하는 위치 표현을
# 데모 좌표로 매핑해 파이프라인 전체를 끝까지 시연할 수 있게 한다.
_MANUAL_GEOCODE_FALLBACK = {
    "OO초등학교 서측 골목 교차로": (37.502, 127.0399),
    "OO초등학교 동측 통학로": (37.5012, 127.0410),
}


def geocode_location_text(location_text: str) -> tuple[float, float] | None:
    if location_text in _MANUAL_GEOCODE_FALLBACK:
        return _MANUAL_GEOCODE_FALLBACK[location_text]

    # 통합 지오코딩 서비스(사전 + Kakao/Naver/Tmap)로 위치텍스트를 좌표로 변환
    from .geocoding import geocode

    result = geocode(location_text)
    if result is not None:
        return result.lat, result.lng
    return None


def ingest_document(file_bytes: bytes, filename: str) -> dict[str, Any]:
    parsed = parse_document(file_bytes, filename)
    extracted = extract_risk_points(file_bytes, filename)

    db.init_db()
    created = 0
    with db.session() as conn:
        for rp in extracted["risk_points"]:
            if extracted.get("already_geocoded") and rp.get("lat") is not None:
                lat, lng = rp["lat"], rp["lng"]
            else:
                geocoded = geocode_location_text(rp.get("location_text", ""))
                if geocoded is None:
                    continue
                lat, lng = geocoded

            db.insert_doc_risk_point(
                conn,
                lat=lat,
                lng=lng,
                risk_type=rp.get("risk_type", ""),
                is_risk=rp.get("is_risk", True),
                snippet=rp.get("snippet", ""),
                source_doc=filename,
                page=rp.get("page"),
                report_date=rp.get("report_date"),
                recommendation=rp.get("recommendation"),
            )
            created += 1

    return {
        "document_name": filename,
        "extracted": extracted,
        "risk_points_created": created,
        "used_mock": settings.upstage_mock,
        "parsed_preview": parsed.get("markdown", "")[:500],
    }
