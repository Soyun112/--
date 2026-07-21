"""Upstage Document Parse + Information Extract 파이프라인.

흐름: 문서(PDF/HWP/이미지) 업로드
      -> Document Parse(/v1/document-digitization, model=document-parse)로 구조화 텍스트 확보
      -> Information Extract(/v1/information-extraction, model=information-extract)로
         {location_text, risk_type, is_risk, report_date, recommendation, snippet} 스키마 추출
      -> Solar LLM으로 location_text를 지오코딩용 검색어로 정규화
      -> 정규화된 검색어를 위경도로 지오코딩
      -> SQLite doc_risk_points 테이블에 출처(source_doc)와 함께 적재

UPSTAGE_API_KEY가 없으면 backend/app/data/sample_documents/의 샘플 파싱·추출 결과를
그대로 사용해 동일한 다운스트림(지오코딩 -> DB 적재 -> 안전점수 반영)을 시연한다.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from typing import Any

import requests

from .. import db
from ..config import settings

DOCUMENT_DIGITIZATION_URL = "https://api.upstage.ai/v1/document-digitization"
INFORMATION_EXTRACTION_URL = "https://api.upstage.ai/v1/information-extraction"
CHAT_COMPLETIONS_URL = "https://api.upstage.ai/v1/chat/completions"

# 확신도는 자동 표시를 막지 않는다(MVP: 결과가 보여야 함).
# 이 값 미만으로 찍힌 지점만 "추정" 마커로 표시하고,
# 지오코딩이 실패해도 지역 힌트/데모 중심으로라도 일단 찍는다.
ESTIMATED_CONFIDENCE_THRESHOLD = 0.85


def _pending_point_payload(rp: dict[str, Any], *, filename: str, reason: str) -> dict[str, Any]:
    return {
        "location_text": (rp.get("location_text") or "").strip(),
        "geocode_query": (rp.get("geocode_query") or rp.get("location_text") or "").strip(),
        "confidence": float(rp.get("confidence") or 0),
        "reason": reason,
        "note": rp.get("normalize_note"),
        "risk_type": rp.get("risk_type", ""),
        "is_risk": bool(rp.get("is_risk", True)),
        "snippet": rp.get("snippet", ""),
        "report_date": rp.get("report_date"),
        "recommendation": rp.get("recommendation"),
        "page": rp.get("page"),
        "source_doc": filename,
    }


def _resolve_plot_coordinates(
    *,
    geocode_query: str,
    location_text: str,
    region_hint: str,
    point_index: int,
) -> tuple[float, float, str, float]:
    """좌표를 최대한 찾아 반환. (lat, lng, note, confidence_cap)

    confidence_cap: 이 경로로 찍었을 때 확신도 상한(추정 표시용).
    """
    candidates: list[str] = []
    for raw in (geocode_query, location_text):
        q = (raw or "").strip()
        if q and q not in candidates:
            candidates.append(q)

    hint = (region_hint or "").strip()
    # "출발 / 도착" 형태면 앞쪽(출발)을 우선 지역으로 사용
    hint_parts = [p.strip() for p in re.split(r"[,/|]", hint) if p.strip()]
    primary_hint = hint_parts[0] if hint_parts else hint

    if primary_hint:
        for q in list(candidates):
            combo = f"{primary_hint} {q}".strip()
            if combo not in candidates:
                candidates.append(combo)
        if primary_hint not in candidates:
            candidates.append(primary_hint)

    for q in candidates:
        geocoded = geocode_location_text(q)
        if geocoded is not None:
            # 지역 힌트만으로 찍었거나 조합 검색이면 추정으로 취급
            if q == primary_hint or (primary_hint and q.startswith(primary_hint)):
                return geocoded[0], geocoded[1], f"검색어 보정 후 표시: {q}", 0.5
            return geocoded[0], geocoded[1], f"검색 성공: {q}", 1.0

    # 최후: 데모/서비스 중심 근처에 흩어져 찍기 (겹침 방지)
    jitter = ((point_index % 5) - 2) * 0.00035
    lat = settings.demo_center_lat + jitter
    lng = settings.demo_center_lng + jitter * 0.8
    return lat, lng, "검색 실패 → 경로 지역 근처에 추정 표시", 0.25

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
                            "location_text": {
                                "type": "string",
                                "description": "위험/안전 지점의 주소 또는 위치 설명 (예: 'OO초등학교 서측 골목 교차로')",
                            },
                            "risk_type": {
                                "type": "string",
                                "description": "위험 유형 또는 안전조치 유형 (예: '무단횡단 위험', 'CCTV 추가설치 완료')",
                            },
                            "is_risk": {
                                "type": "boolean",
                                "description": "위험 지적 사항이면 true, 완료된 안전조치/개선사항이면 false",
                            },
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


_MANUAL_GEOCODE_FALLBACK = {
    "OO초등학교 서측 골목 교차로": (37.502, 127.0399),
    "OO초등학교 동측 통학로": (37.5012, 127.0410),
}


def geocode_location_text(location_text: str) -> tuple[float, float] | None:
    if not location_text:
        return None
    if location_text in _MANUAL_GEOCODE_FALLBACK:
        return _MANUAL_GEOCODE_FALLBACK[location_text]

    from .geocoding import geocode

    result = geocode(location_text)
    if result is not None:
        return result.lat, result.lng
    return None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def normalize_locations_with_solar(
    risk_points: list[dict[str, Any]],
    *,
    document_name: str,
    region_hint: str = "",
) -> list[dict[str, Any]]:
    """문서에서 뽑힌 location_text를 지오코딩용 검색어로 정규화한다."""
    if not risk_points:
        return []

    if all(rp.get("lat") is not None and rp.get("lng") is not None for rp in risk_points):
        out = []
        for rp in risk_points:
            item = dict(rp)
            item.setdefault("geocode_query", rp.get("location_text") or "")
            item.setdefault("confidence", 1.0)
            item.setdefault("normalize_note", "이미 좌표가 있어 정규화를 건너뜀")
            out.append(item)
        return out

    fallback = []
    for rp in risk_points:
        item = dict(rp)
        item["geocode_query"] = (rp.get("location_text") or "").strip()
        # 원문 그대로 쓸 때도 지오코딩은 시도한다(이전 0.4는 자동표시 임계값에 걸려 전부 보류됨).
        item["confidence"] = 0.55
        item["normalize_note"] = "원문 위치 표현을 그대로 사용"
        fallback.append(item)

    if settings.upstage_mock or not settings.upstage_api_key:
        return fallback

    payload_points = [
        {
            "i": idx,
            "location_text": rp.get("location_text") or "",
            "risk_type": rp.get("risk_type") or "",
            "snippet": (rp.get("snippet") or "")[:180],
        }
        for idx, rp in enumerate(risk_points)
    ]

    system = (
        "당신은 한국 어린이 통학로 안전 문서의 위치 표현을 지도 검색용 질의로 바꾸는 도우미입니다. "
        "추측으로 존재하지 않는 건물·도로를 만들지 마세요. "
        "확실하지 않으면 confidence를 낮게 주세요. "
        "반드시 JSON만 출력하세요."
    )
    user = (
        f"문서명: {document_name}\n"
        f"지역 힌트: {region_hint or '(없음)'}\n"
        "아래 위치 표현을 카카오/네이버/Tmap 지오코딩에 넣을 수 있는 한국어 검색어로 바꿔 주세요.\n"
        "규칙:\n"
        "1) geocode_query: 시/구/동·학교·건물·교차로 등이 드러나는 짧은 검색어\n"
        "2) confidence: 0~1 (검색 가능하다고 확신할수록 높게)\n"
        "3) note: 한 줄 메모\n"
        "출력 JSON 형식:\n"
        '{"items":[{"i":0,"geocode_query":"...","confidence":0.0,"note":"..."}]}\n\n'
        f"입력:\n{json.dumps(payload_points, ensure_ascii=False)}"
    )

    try:
        resp = requests.post(
            CHAT_COMPLETIONS_URL,
            headers={"Authorization": f"Bearer {settings.upstage_api_key}", "Content-Type": "application/json"},
            json={
                "model": "solar-pro",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "max_tokens": 900,
            },
            timeout=45,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content) or {}
        items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
        by_index: dict[int, dict[str, Any]] = {}
        for raw in items:
            if not isinstance(raw, dict):
                continue
            try:
                idx = int(raw.get("i"))
            except (TypeError, ValueError):
                continue
            by_index[idx] = raw

        out = []
        for idx, rp in enumerate(risk_points):
            item = dict(rp)
            raw = by_index.get(idx, {})
            query = str(raw.get("geocode_query") or rp.get("location_text") or "").strip()
            try:
                conf = float(raw.get("confidence", 0.55))
            except (TypeError, ValueError):
                conf = 0.55
            conf = max(0.0, min(1.0, conf))
            item["geocode_query"] = query
            item["confidence"] = conf
            item["normalize_note"] = str(raw.get("note") or "Solar 정규화")
            out.append(item)
        return out
    except Exception as exc:
        for item in fallback:
            item["normalize_note"] = f"Solar 정규화 실패 → 원문 사용 ({exc})"
        return fallback


def ingest_document(
    file_bytes: bytes,
    filename: str,
    *,
    region_hint: str = "",
) -> dict[str, Any]:
    parsed = parse_document(file_bytes, filename)
    extracted = extract_risk_points(file_bytes, filename)
    normalized = normalize_locations_with_solar(
        extracted.get("risk_points") or [],
        document_name=filename,
        region_hint=region_hint,
    )

    db.init_db()
    created = 0
    created_points: list[dict[str, Any]] = []
    skipped_points: list[dict[str, Any]] = []

    with db.session() as conn:
        for idx, rp in enumerate(normalized):
            location_text = (rp.get("location_text") or "").strip()
            geocode_query = (rp.get("geocode_query") or location_text).strip()
            confidence = float(rp.get("confidence") or 0)
            plot_note = rp.get("normalize_note") or ""
            used_fallback_plot = False

            if extracted.get("already_geocoded") and rp.get("lat") is not None:
                lat, lng = rp["lat"], rp["lng"]
                confidence = max(confidence, 0.9)
            else:
                # 문구가 없어도 일단 지역 근처에 찍는다(MVP).
                lat, lng, resolve_note, conf_cap = _resolve_plot_coordinates(
                    geocode_query=geocode_query,
                    location_text=location_text,
                    region_hint=region_hint,
                    point_index=idx,
                )
                confidence = min(confidence if confidence > 0 else conf_cap, conf_cap)
                plot_note = f"{plot_note} · {resolve_note}".strip(" ·")
                used_fallback_plot = conf_cap <= 0.5

            is_estimated = confidence < ESTIMATED_CONFIDENCE_THRESHOLD
            db.insert_doc_risk_point(
                conn,
                lat=lat,
                lng=lng,
                risk_type=rp.get("risk_type", "") or "문서 위험지점",
                is_risk=rp.get("is_risk", True),
                snippet=rp.get("snippet", ""),
                source_doc=filename,
                page=rp.get("page"),
                report_date=rp.get("report_date"),
                recommendation=rp.get("recommendation"),
                is_estimated=is_estimated,
            )
            created += 1
            created_points.append(
                {
                    "location_text": location_text,
                    "geocode_query": geocode_query,
                    "confidence": confidence,
                    "lat": lat,
                    "lng": lng,
                    "risk_type": rp.get("risk_type", ""),
                    "is_risk": bool(rp.get("is_risk", True)),
                    "is_estimated": is_estimated,
                    "note": plot_note,
                }
            )
            # 폴백/힌트로 찍은 건 확인 목록에 남겨 수정할 수 있게 한다.
            if used_fallback_plot:
                pending = _pending_point_payload(
                    {**rp, "geocode_query": geocode_query or location_text or region_hint},
                    filename=filename,
                    reason="추정 위치로 표시됨 — 검색어를 고치면 더 정확해져요",
                )
                pending["lat"] = lat
                pending["lng"] = lng
                skipped_points.append(pending)

    extracted = dict(extracted)
    extracted["risk_points"] = normalized
    extracted["created_points"] = created_points
    extracted["skipped_points"] = skipped_points

    return {
        "document_name": filename,
        "extracted": extracted,
        "risk_points_created": created,
        "risk_points_skipped": len(skipped_points),
        "used_mock": settings.upstage_mock,
        "parsed_preview": parsed.get("markdown", "")[:500],
    }


def confirm_document_point(
    *,
    location_text: str,
    geocode_query: str,
    risk_type: str = "",
    is_risk: bool = True,
    snippet: str = "",
    source_doc: str = "",
    page: int | None = None,
    report_date: str | None = None,
    recommendation: str | None = None,
) -> dict[str, Any]:
    """사용자가 보류 지점의 검색어를 확인·수정한 뒤 지도에 올린다."""
    query = (geocode_query or location_text or "").strip()
    if not query:
        raise ValueError("검색어(geocode_query)가 비어 있습니다.")

    geocoded = geocode_location_text(query)
    if geocoded is None and location_text and location_text.strip() != query:
        geocoded = geocode_location_text(location_text.strip())
    if geocoded is None:
        raise ValueError(f"위치를 찾지 못했습니다: {query}")

    lat, lng = geocoded
    db.init_db()
    with db.session() as conn:
        db.insert_doc_risk_point(
            conn,
            lat=lat,
            lng=lng,
            risk_type=risk_type or "",
            is_risk=is_risk,
            snippet=snippet or "",
            source_doc=source_doc or "manual-confirm",
            page=page,
            report_date=report_date,
            recommendation=recommendation,
            # 사용자가 검색어를 확인했으므로 추정 배지는 제거
            is_estimated=False,
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return {
        "id": int(row_id),
        "lat": lat,
        "lng": lng,
        "risk_type": risk_type or "",
        "is_estimated": False,
        "source_doc": source_doc or "manual-confirm",
        "geocode_query": query,
    }
