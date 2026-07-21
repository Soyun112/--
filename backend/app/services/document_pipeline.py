"""Upstage Document Parse + Solar 주소화 파이프라인.

사용자가 원한 흐름:
  1) Document Parse로 텍스트 추출
  2) Solar로 지도가 인식할 수 있는 주소(geocode_query)로 변환
  3) 지오코딩 후 지도에 핀
  4) 안전경로 찾기 때 문서 위험 핀을 우회 고려사항으로 반영
     (routing._append_avoid_point_detours)

UPSTAGE_API_KEY가 없으면 sample_documents 샘플로 동일 다운스트림을 시연한다.
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from .. import db
from ..config import settings
from ..console_safe import safe_print

DOCUMENT_DIGITIZATION_URL = "https://api.upstage.ai/v1/document-digitization"
CHAT_COMPLETIONS_URL = "https://api.upstage.ai/v1/chat/completions"

# 확신도는 자동 표시를 막지 않는다(MVP: 결과가 보여야 함).
# 이 값 미만으로 찍힌 지점만 "추정" 마커로 표시하고,
# 지오코딩이 실패해도 지역 힌트/데모 중심으로라도 일단 찍는다.
ESTIMATED_CONFIDENCE_THRESHOLD = 0.85


def _pipeline_stage(name: str, status: str, detail: str = "") -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


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


def risk_points_from_filename(filename: str) -> list[dict[str, Any]]:
    """본문 추출이 비어도 파일명에서 도로명·번지를 건진다."""
    from pathlib import Path

    stem = Path(filename or "").stem
    if not stem:
        return []

    # 괄호 안(예: 선릉로 305 외 3개소)을 우선 검색 — '도로정비'의 '도로' 오탐 방지
    paren = re.search(r"\(([^)]+)\)", stem)
    search_blobs = []
    if paren:
        search_blobs.append(paren.group(1))
    search_blobs.append(stem)

    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    false_positives = {"도로", "길", "대로", "위치도", "공사"}

    for blob in search_blobs:
        for match in re.finditer(r"([가-힣A-Za-z0-9]+(?:로|길|대로))\s*(\d+)?", blob):
            road = match.group(1)
            num = match.group(2)
            if road in false_positives:
                continue
            loc = f"{road} {num}".strip() if num else road
            if loc in seen:
                continue
            if not num and paren and blob == stem:
                continue
            seen.add(loc)
            points.append(
                {
                    "location_text": loc,
                    "geocode_query": loc,
                    "confidence": 0.6,
                    "normalize_note": "파일명에서 추출",
                    "risk_type": "공사/정비 구간",
                    "is_risk": True,
                    "snippet": f"파일명에서 위치를 읽음: {stem}",
                    "recommendation": "통행 시 주의",
                }
            )
        if points:
            break

    extra = re.search(r"외\s*(\d+)\s*개소", stem)
    if extra and points:
        try:
            n_extra = min(int(extra.group(1)), 3)
        except ValueError:
            n_extra = 0
        base = points[0]["location_text"]
        for i in range(1, n_extra + 1):
            loc = f"{base} 인근 {i}"
            if loc in seen:
                continue
            seen.add(loc)
            points.append(
                {
                    "location_text": loc,
                    "geocode_query": base,
                    "confidence": 0.35,
                    "normalize_note": "파일명 '외 N개소' 추정",
                    "risk_type": "공사/정비 구간(인근)",
                    "is_risk": True,
                    "snippet": f"파일명 '외 {n_extra}개소' 표시에 따른 추정 지점",
                    "recommendation": "통행 시 주의",
                }
            )

    if not points and any(k in stem for k in ("공사", "위치도", "정비", "통학", "안전")):
        loc = paren.group(1).strip() if paren else stem
        points.append(
            {
                "location_text": loc,
                "geocode_query": loc,
                "confidence": 0.4,
                "normalize_note": "파일명 단서",
                "risk_type": "문서 위험/공사 구간",
                "is_risk": True,
                "snippet": f"파일명 전체를 위치 단서로 사용: {stem}",
                "recommendation": "검색어를 다듬어 주세요",
            }
        )
    return points


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


def _resolve_plot_coordinates(
    *,
    geocode_query: str,
    location_text: str,
    region_hint: str,
    point_index: int,
) -> tuple[float, float, str, float]:
    """좌표를 최대한 찾아 반환. (lat, lng, note, confidence_cap)"""
    candidates: list[str] = []
    for raw in (geocode_query, location_text):
        q = (raw or "").strip()
        if q and q not in candidates:
            candidates.append(q)

    hint = (region_hint or "").strip()
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
            if q == primary_hint or (primary_hint and q.startswith(primary_hint)):
                return geocoded[0], geocoded[1], f"검색어 보정 후 표시: {q}", 0.5
            return geocoded[0], geocoded[1], f"검색 성공: {q}", 1.0

    jitter = ((point_index % 5) - 2) * 0.00035
    lat = settings.demo_center_lat + jitter
    lng = settings.demo_center_lng + jitter * 0.8
    return lat, lng, "검색 실패 → 경로 지역 근처에 추정 표시", 0.25


def _region_prefix(region_hint: str) -> str:
    hint = (region_hint or "").strip()
    if "강남" in hint or "역삼" in hint or "도곡" in hint or "대치" in hint or "선릉" in hint:
        return "서울 강남구"
    if "서울" in hint:
        return "서울"
    return "서울 강남구"


def _to_map_query(road_addr: str, region_hint: str = "") -> str:
    """지도(Tmap 지오코딩/POI)가 읽기 쉬운 검색어로 정리."""
    q = re.sub(r"\s+", " ", (road_addr or "").strip())
    q = q.replace("～", "~").replace("〜", "~")
    if not q:
        return ""
    if q.startswith("서울"):
        return q
    prefix = _region_prefix(region_hint)
    if q.startswith(prefix):
        return q
    return f"{prefix} {q}"


def risk_points_from_location_map_text(
    text: str,
    *,
    region_hint: str = "",
) -> list[dict[str, Any]]:
    """위치도 형식 구간 추출. 예) ① 선릉로 … 역삼로314 ~ 선릉로305"""
    raw = text or ""
    if not raw.strip():
        return []

    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    section_re = re.compile(
        r"[①②③④⑤⑥⑦⑧⑨⑩]?\s*"
        r"([가-힣A-Za-z0-9]+(?:로|길|대로))"
        r"(?:\s*\(([^)]*)\))?"
        r"[^\n①②③④⑤⑥⑦⑧⑨⑩]{0,120}?"
        r"([가-힣A-Za-z0-9]+(?:로|길|대로)\s*\d+)"
        r"\s*[~～〜\-–—]\s*"
        r"([가-힣A-Za-z0-9]+(?:로|길|대로)\s*\d+)",
        re.MULTILINE,
    )
    for match in section_re.finditer(raw):
        road_title = match.group(1).strip()
        dong = (match.group(2) or "").strip()
        start_addr = re.sub(r"\s+", " ", match.group(3).strip())
        end_addr = re.sub(r"\s+", " ", match.group(4).strip())
        preferred = end_addr if road_title in end_addr else start_addr
        if preferred in seen:
            continue
        seen.add(preferred)
        loc = f"{road_title}"
        if dong:
            loc += f"({dong})"
        loc += f" {start_addr}~{end_addr}"
        points.append(
            {
                "location_text": loc,
                "geocode_query": _to_map_query(preferred, region_hint),
                "confidence": 0.85,
                "normalize_note": "위치도 구간 규칙 추출",
                "risk_type": "공사/정비 구간",
                "is_risk": True,
                "snippet": match.group(0).strip()[:200],
                "recommendation": "공사 구간 통행 시 주의",
            }
        )
    return points


def _merge_risk_points(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            key = re.sub(r"\s+", "", (item.get("geocode_query") or item.get("location_text") or "").strip().lower())
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def solar_extract_map_points_from_text(
    markdown: str,
    *,
    filename: str,
    region_hint: str = "",
) -> list[dict[str, Any]]:
    """Document Parse 본문 → Solar: 지점 추출 + 지도 검색용 주소 변환.

    이미 검색 가능한 주소/도로명·번지면 geocode_query에 그대로 둔다(패스).
    """
    text = (markdown or "").strip()
    if not text:
        return []
    if settings.upstage_mock or not settings.upstage_api_key:
        return []

    system = (
        "당신은 한국 도로 공사·위치도·통학로 문서에서 "
        "지도(Tmap 지오코딩/POI)에 핀을 찍을 주소를 만드는 도우미입니다. "
        "원문에 없는 주소·가상 학교명(OO초등학교 등)을 만들지 마세요. JSON만 출력하세요."
    )
    user = (
        f"문서명: {filename}\n"
        f"지역 힌트: {region_hint or '(없음)'}\n\n"
        "할 일:\n"
        "1) 본문/위치도에서 공사·위험 구간을 모두 뽑으세요 (①②③④ 등).\n"
        "2) location_text: 원문 표현에 가깝게\n"
        "3) geocode_query: 지도가 바로 검색할 수 있는 형식만\n\n"
        "【geocode_query 좋은 예시 — 이 형식을 따르세요】\n"
        '- "서울 강남구 선릉로 305"\n'
        '- "서울 강남구 논현로76길 21"\n'
        '- "서울 강남구 도곡로 168"\n'
        '- "서울 강남구 테헤란로108길 42"\n'
        '- "서울 강남구 역삼로 314"\n\n'
        "【위치도 원문 → 변환 예시】\n"
        '원문: "① 선릉로 (역삼2동) 역삼로314 ~ 선릉로305"\n'
        '→ location_text: "선릉로(역삼2동) 역삼로314~선릉로305"\n'
        '→ geocode_query: "서울 강남구 선릉로 305"\n\n'
        '원문: "② 논현로76길 (역삼2동) 논현로412 ~ 논현로76길21"\n'
        '→ geocode_query: "서울 강남구 논현로76길 21"\n\n'
        "【나쁜 예 — 쓰지 마세요】\n"
        '- "OO초등학교 서측 골목" / "정문 앞"만 단독 / 샘플·가상 지명\n\n'
        "구간(A ~ B)이면 지도 검색되는 도로명+번지 하나를 geocode_query로 넣으세요.\n"
        "구·동이 없으면 '서울 강남구'를 앞에 붙이세요.\n"
        "confidence, risk_type, is_risk=true(공사/위험), snippet, recommendation\n"
        "위치가 없으면 risk_points=[]\n"
        "출력 JSON만:\n"
        '{"risk_points":[{"location_text":"...","geocode_query":"...","confidence":0.0,'
        '"risk_type":"...","is_risk":true,"snippet":"...","recommendation":"..."}]}\n\n'
        f"본문:\n{text[:8000]}"
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
                "max_tokens": 2000,
            },
            timeout=90,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content) or {}
        items = parsed.get("risk_points") if isinstance(parsed.get("risk_points"), list) else []
        out: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            loc = str(raw.get("location_text") or "").strip()
            query = str(raw.get("geocode_query") or loc).strip()
            if not loc and not query:
                continue
            if not loc:
                loc = query
            if not query:
                query = loc
            if "OO초등" in loc or "OO초등" in query or "샘플" in loc:
                continue
            query = _to_map_query(query, region_hint)
            try:
                conf = float(raw.get("confidence", 0.6))
            except (TypeError, ValueError):
                conf = 0.6
            conf = max(0.0, min(1.0, conf))
            out.append(
                {
                    "location_text": loc,
                    "geocode_query": query,
                    "confidence": conf,
                    "normalize_note": "Document Parse → Solar 주소화",
                    "risk_type": str(raw.get("risk_type") or "공사/정비 구간"),
                    "is_risk": bool(raw.get("is_risk", True)),
                    "snippet": str(raw.get("snippet") or "")[:300],
                    "recommendation": str(raw.get("recommendation") or ""),
                    "report_date": raw.get("report_date"),
                    "page": raw.get("page"),
                }
            )
        return out
    except Exception as exc:
        safe_print(f"[문서] Solar 주소화 실패: {exc}")
        return []


def ingest_document(
    file_bytes: bytes,
    filename: str,
    *,
    region_hint: str = "",
    replace_existing: bool = True,
) -> dict[str, Any]:
    """1) 텍스트 추출 → 2) Solar/규칙 주소화 → 3) 핀 → (4는 안전경로 찾기에서 반영)."""
    stages: list[dict[str, str]] = []

    if replace_existing:
        db.init_db()
        db.clear_doc_risk_points()
        safe_print("[문서] 기존 문서 위험 핀 삭제 후 재분석")
        stages.append(_pipeline_stage("0_clear_old_pins", "ok", "이전 핀 삭제"))

    # --- 1) Document Parse ---
    parsed = parse_document(file_bytes, filename)
    markdown = parsed.get("markdown", "") or ""
    stages.append(
        _pipeline_stage(
            "1_text_extract",
            "ok" if markdown.strip() else "empty",
            f"Document Parse · {len(markdown)}자" + (" (MOCK)" if parsed.get("mock") else ""),
        )
    )
    safe_print(f"[문서] 1) 텍스트 추출: {len(markdown)}자 ({filename})")

    # --- 2) Solar + 위치도 규칙 → 지도용 주소 ---
    if settings.upstage_mock:
        sample = _load_sample_extract()
        normalized = []
        for rp in sample.get("risk_points") or []:
            item = dict(rp)
            item.setdefault("geocode_query", rp.get("location_text") or "")
            item.setdefault("confidence", 1.0)
            item.setdefault("normalize_note", "MOCK 샘플 · Solar 주소화 시연")
            normalized.append(item)
        extracted: dict[str, Any] = {
            "risk_points": normalized,
            "mock": True,
            "already_geocoded": True,
            "extract_source": "mock-sample",
        }
        stages.append(
            _pipeline_stage("2_solar_address", "ok", f"MOCK Solar 주소화 · {len(normalized)}곳")
        )
    else:
        from_solar = solar_extract_map_points_from_text(
            markdown,
            filename=filename,
            region_hint=region_hint,
        )
        from_rules = risk_points_from_location_map_text(markdown, region_hint=region_hint)
        normalized = _merge_risk_points(from_solar, from_rules)
        source = "document-parse+solar+rules"
        if not normalized:
            normalized = risk_points_from_filename(filename)
            source = "filename" if normalized else "empty"
            stages.append(
                _pipeline_stage(
                    "2_solar_address",
                    "fallback" if normalized else "empty",
                    "Solar/규칙 없음 → 파일명 폴백" if normalized else "주소화할 지점 없음",
                )
            )
        else:
            stages.append(
                _pipeline_stage(
                    "2_solar_address",
                    "ok",
                    f"Solar {len(from_solar)} + 규칙 {len(from_rules)} → 합 {len(normalized)}곳",
                )
            )
        extracted = {
            "risk_points": normalized,
            "mock": False,
            "already_geocoded": False,
            "extract_source": source,
        }
    safe_print(
        f"[문서] 2) 주소화: {len(normalized)}곳 "
        f"(source={extracted.get('extract_source')})"
    )

    # --- 3) 지오코딩 → DB 핀 ---
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
            if used_fallback_plot:
                pending = _pending_point_payload(
                    {**rp, "geocode_query": geocode_query or location_text or region_hint},
                    filename=filename,
                    reason="추정 위치로 표시됨 — 검색어를 고치면 더 정확해져요",
                )
                pending["lat"] = lat
                pending["lng"] = lng
                skipped_points.append(pending)

    stages.append(
        _pipeline_stage(
            "3_map_pins",
            "ok" if created else "empty",
            f"지도 핀 {created}개 · 추정/보류 {len(skipped_points)}개",
        )
    )
    stages.append(
        _pipeline_stage(
            "4_route_avoid",
            "ready",
            "「안전 경로 찾기」 시 사고다발·문서위험 우회 후보에 반영",
        )
    )
    safe_print(f"[문서] 3) 핀: {created}개 (추정 {len(skipped_points)}) → 4) 경로 우회 대기")

    extracted = dict(extracted)
    extracted["risk_points"] = normalized
    extracted["created_points"] = created_points
    extracted["skipped_points"] = skipped_points
    extracted["pipeline_stages"] = stages

    return {
        "document_name": filename,
        "extracted": extracted,
        "risk_points_created": created,
        "risk_points_skipped": len(skipped_points),
        "used_mock": settings.upstage_mock,
        "parsed_preview": markdown[:500],
        "pipeline_stages": stages,
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
