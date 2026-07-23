"""Upstage Solar LLM으로 부모용 안전 리포트(JSON)를 생성.

부모가 아이에게 그대로 읽어줄 수 있는 문장만 쓰고, 주어진 수치 밖의
추측·과장을 금지한다. UPSTAGE_API_KEY가 없으면 동일 규칙의 템플릿 JSON으로 대체.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import requests

from ..config import settings
from ..models import RouteCandidate
from .weather import weather_summary_text

CHAT_COMPLETIONS_URL = "https://api.upstage.ai/v1/chat/completions"

GANGNAM_MEDIAN = 60

PARENT_SYSTEM_PROMPT = """당신은 초등학생 통학로 안전 리포트를 쓰는 도우미입니다.
부모가 아이에게 그대로 읽어줄 수 있는 문장을 씁니다.

절대 규칙:
1. 주어진 수치에 없는 내용을 만들지 마세요. 추측 금지.
2. 값이 0인 항목은 "없습니다"라고만 쓰고, 그것을 근거로
   위험하다고 단정하지 마세요.
3. "어린이보호구역 CCTV"는 보호구역이 보유한 개수이며 경로 바로
   위에 있다는 뜻이 아닙니다. "주변 보호구역에 CCTV가 N대 있습니다"
   처럼 쓰고, "아이를 지켜보고 있습니다" 같은 단정은 피하세요.
4. 안전점수는 100점 만점 시험 점수가 아닙니다. 강남구 초등학교
   통학로 87개 실측 기준 중앙값이 60점입니다. 점수를 언급할 때는
   반드시 이 기준을 함께 알려 주세요.
5. 과장하지 마세요. "매우 안전", "완벽하게" 같은 표현 금지.
6. 아이에게 겁을 주지 마세요. 주의사항은 행동 지침으로 바꿔서
   쓰세요. ("위험합니다" → "여기서는 뛰지 말고 좌우를 보세요")"""


def _score_grade_label(score: float) -> str:
    if score >= 70:
        return "안전 (70점 이상)"
    if score >= 55:
        return "보통 (55~70점)"
    return "주의 (55점 미만)"


def _period_label(time_context: Optional[dict[str, Any]]) -> str:
    tc = time_context or {}
    if tc.get("is_night"):
        return "밤"
    if tc.get("period_label") in ("밤", "낮"):
        return str(tc["period_label"])
    return "낮"


def _bell112_count(features) -> int:
    """안심벨·112신고 통합 개수(폴 기준 우선)."""
    pole = int(getattr(features, "emergency_pole_count", 0) or 0)
    if pole > 0:
        return pole
    return int(features.safety_bell_count or 0) + int(features.emergency112_count or 0)


def build_parent_user_prompt(
    candidate: RouteCandidate,
    time_context: Optional[dict[str, Any]] = None,
) -> str:
    """프롬프트용 수치 — 0인 항목도 그대로 전달 (문장 반영은 모델 규칙)."""
    f = candidate.features
    km = round(f.distance_km if f.distance_km else candidate.distance_m / 1000.0, 2)
    mins = max(1, round(candidate.duration_s / 60))
    score = candidate.safety_score
    period = _period_label(time_context)
    bell112 = _bell112_count(f)
    doc_n = int(f.doc_risk_count or 0)
    if not doc_n and f.matched_documents:
        doc_n = sum(1 for d in f.matched_documents if d.is_risk)

    return f"""아래 수치로 안전 리포트를 작성하세요.

경로 정보
- 거리: {km}km, 소요: {mins}분
- 안전점수: {score}점 (강남 초등 통학로 중앙값 {GANGNAM_MEDIAN}점)
- 등급: {_score_grade_label(score)}
- 시간대: {period}

안전 시설 (경로 40m 이내)
- 안심귀갓길 CCTV: {f.safety_facility_cctv_count}대
- 안심귀갓길 보안등: {f.safety_facility_streetlight_count}개
- 안심벨·112신고: {bell112}개
- 아동안전지킴이집: {f.guardian_house_count}곳
- 무인단속카메라: {f.speed_camera_count}곳

주변 보호구역
- 보호구역 보유 CCTV: {f.cctv_count}대
- 어린이보호구역 통과 비율: {f.child_zone_coverage_pct}%

주의 요소
- 교통사고다발지역: {f.accident_hotspot_count}곳
- 문서 기반 위험구간: {doc_n}곳

아래 형식 그대로, JSON으로만 출력하세요.

{{
  "summary": "2~3문장. 점수와 그 의미(중앙값 60점 대비 위치)를 먼저 말하고, 이 경로의 특징을 한 문장으로.",
  "good_points": [
    "값이 0보다 큰 항목만. 각 1~2문장. 최대 4개. 수치를 반드시 포함. 없으면 빈 배열."
  ],
  "caution_points": [
    "사고다발·문서위험이 있을 때만. 각 1~2문장. 아이에게 말해 줄 구체적 행동 지침을 포함. 없으면 빈 배열."
  ],
  "night_note": "밤일 때만 한 문장. 낮이면 빈 문자열. 조명·CCTV 유무에 따라 실용적인 조언."
}}"""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "summary" in data:
            return data
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict) and "summary" in data:
                return data
        except json.JSONDecodeError:
            return None
    return None


def _normalize_parent_payload(data: dict[str, Any]) -> dict[str, Any]:
    good = data.get("good_points") or []
    caution = data.get("caution_points") or []
    if not isinstance(good, list):
        good = [str(good)] if good else []
    if not isinstance(caution, list):
        caution = [str(caution)] if caution else []
    return {
        "summary": str(data.get("summary") or "").strip(),
        "good_points": [str(x).strip() for x in good if str(x).strip()][:4],
        "caution_points": [str(x).strip() for x in caution if str(x).strip()],
        "night_note": str(data.get("night_note") or "").strip(),
    }


def _mock_parent_structured(
    candidate: RouteCandidate,
    time_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Solar 없을 때 — 동일 규칙으로 JSON 구조 생성."""
    f = candidate.features
    score = float(candidate.safety_score)
    km = round(f.distance_km if f.distance_km else candidate.distance_m / 1000.0, 2)
    mins = max(1, round(candidate.duration_s / 60))
    period = _period_label(time_context)
    vs = score - GANGNAM_MEDIAN
    if abs(vs) < 0.5:
        vs_txt = f"강남 초등 통학로 중앙값({GANGNAM_MEDIAN}점)과 비슷합니다"
    elif vs > 0:
        vs_txt = f"강남 초등 통학로 중앙값({GANGNAM_MEDIAN}점)보다 약 {vs:.1f}점 높습니다"
    else:
        vs_txt = f"강남 초등 통학로 중앙값({GANGNAM_MEDIAN}점)보다 약 {abs(vs):.1f}점 낮습니다"

    summary = (
        f"이 경로의 안전점수는 {score}점입니다. {vs_txt}. "
        f"거리는 약 {km}km, 걸어서 약 {mins}분 걸립니다."
    )

    good: list[str] = []
    if f.child_zone_coverage_pct > 0:
        good.append(
            f"어린이보호구역을 약 {f.child_zone_coverage_pct}% 지납니다. "
            "이 구간에서는 차량 속도가 제한되니 아이가 횡단보도에서 여유 있게 건널 수 있다고 말해 주세요."
        )
    if f.cctv_count > 0:
        good.append(
            f"주변 보호구역에 CCTV가 {f.cctv_count}대 있습니다. "
            "경로 바로 위에 있다는 뜻은 아니며, 근처 보호구역이 보유한 시설 수입니다."
        )
    if f.safety_facility_cctv_count > 0:
        good.append(
            f"경로 40m 안에 안심귀갓길 CCTV가 {f.safety_facility_cctv_count}대 있습니다."
        )
    if f.safety_facility_streetlight_count > 0:
        good.append(
            f"안심귀갓길 보안등이 {f.safety_facility_streetlight_count}개 있습니다. "
            "어두운 시간대에 밝은 구간을 고르는 데 참고할 수 있습니다."
        )
    bell112 = _bell112_count(f)
    if bell112 > 0 and len(good) < 4:
        good.append(f"안심벨·112신고 장치가 {bell112}개 있습니다.")
    if f.guardian_house_count > 0 and len(good) < 4:
        good.append(
            f"아동안전지킴이집이 {f.guardian_house_count}곳 있습니다. "
            "급한 일이 있으면 가까운 가게에 도움을 요청하라고 미리 알려 주세요."
        )
    if f.speed_camera_count > 0 and len(good) < 4:
        good.append(f"무인단속카메라가 {f.speed_camera_count}곳 있습니다.")

    caution: list[str] = []
    if f.accident_hotspot_count > 0:
        caution.append(
            f"교통사고다발지역이 {f.accident_hotspot_count}곳 있습니다. "
            "아이에게 ‘여기서는 뛰지 말고 좌우를 본 뒤 건너자’고 말해 주세요."
        )
    risk_docs = [d for d in (f.matched_documents or []) if d.is_risk]
    doc_n = int(f.doc_risk_count or 0) or len(risk_docs)
    if doc_n > 0:
        kind = (risk_docs[0].risk_type if risk_docs else None) or "주의 구간"
        caution.append(
            f"문서 기반 위험구간이 {doc_n}곳({kind}) 있습니다. "
            "그 앞을 지날 때는 천천히 걷고, 공사·펜스가 있으면 한쪽으로 붙어 가라고 알려 주세요."
        )

    night_note = ""
    if period == "밤":
        lights = f.safety_facility_streetlight_count
        cams = f.safety_facility_cctv_count
        if lights > 0 or cams > 0:
            night_note = (
                f"밤 시간대라 안심귀갓길 보안등 {lights}개·CCTV {cams}대가 있는 구간을 우선 참고해 주세요."
            )
        else:
            night_note = (
                "밤 시간대입니다. 가능하면 밝은 큰길을 걷고, 이어폰은 한쪽만 쓰도록 알려 주세요."
            )

    return _normalize_parent_payload(
        {
            "summary": summary,
            "good_points": good[:4],
            "caution_points": caution,
            "night_note": night_note,
        }
    )


def _call_solar(system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
    resp = requests.post(
        CHAT_COMPLETIONS_URL,
        headers={
            "Authorization": f"Bearer {settings.upstage_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "solar-pro",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
        },
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _mock_kid_report(
    candidate: RouteCandidate,
    audience_age: int,
    weather: Optional[dict[str, Any]] = None,
    time_context: Optional[dict[str, Any]] = None,
) -> str:
    f = candidate.features
    tc = time_context or {}
    crossing_note = (
        "횡단보도를 조심해서 건너면"
        if f.accident_hotspot_count == 0
        else "차가 많은 곳에서는 손을 들고 좌우를 본 뒤 건너면"
    )
    weather_note = ""
    if weather and weather.get("is_rain"):
        weather_note = " 오늘은 비가 오니까 우산 챙기고, 바닥이 미끄러우니 뛰지 말고 천천히 걷자!"
    time_note = ""
    if tc.get("is_night"):
        time_note = " 지금은 밤이라 밝은 길을 골랐어!"
    elif tc.get("period_label"):
        time_note = " 지금은 낮이라 차 조심하는 길로 골랐어!"
    if tc.get("eta_message"):
        time_note += f" {tc['eta_message']}!"
    ansim = f.safety_facility_cctv_count
    return (
        f"이 길로 가면 돼요. 근처 안심 CCTV가 {ansim}대 있고, "
        f"{crossing_note} 학교까지 갈 수 있어요.{time_note}{weather_note}"
    )


def _mock_parent_report(
    candidate: RouteCandidate,
    other_candidates: list[RouteCandidate] | None = None,
    weather: Optional[dict[str, Any]] = None,
    time_context: Optional[dict[str, Any]] = None,
) -> str:
    """하위 호환 — JSON 문자열로 부모 리포트 반환."""
    del other_candidates, weather
    return json.dumps(
        _mock_parent_structured(candidate, time_context),
        ensure_ascii=False,
    )


def generate_parent_report(
    candidate: RouteCandidate,
    time_context: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], bool]:
    """부모용 리포트 JSON dict와 mock 여부."""
    if settings.upstage_mock:
        return _mock_parent_structured(candidate, time_context), True

    user_prompt = build_parent_user_prompt(candidate, time_context)
    try:
        raw = _call_solar(PARENT_SYSTEM_PROMPT, user_prompt, max_tokens=900)
        parsed = _extract_json_object(raw)
        if parsed:
            return _normalize_parent_payload(parsed), False
        return _mock_parent_structured(candidate, time_context), True
    except Exception:
        return _mock_parent_structured(candidate, time_context), True


def generate_reports(
    candidate: RouteCandidate,
    other_candidates: list[RouteCandidate],
    audience_age: int,
    weather: Optional[dict[str, Any]] = None,
    time_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    del other_candidates  # 새 프롬프트는 추천 경로 수치만 사용
    structured, parent_mock = generate_parent_report(candidate, time_context)
    parent_json = json.dumps(structured, ensure_ascii=False)

    kid_mock = True
    kid_report = _mock_kid_report(candidate, audience_age, weather, time_context)

    return {
        "parent_report": parent_json,
        "parent_report_v2": parent_json,
        "parent_structured": structured,
        "kid_report": kid_report,
        "used_mock": parent_mock and kid_mock,
        "weather_note": weather_summary_text(weather),
    }
