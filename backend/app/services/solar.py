"""Upstage Solar LLM(OpenAI 호환 /v1/chat/completions)로 부모용/아이용 설명을 생성.

일반 LLM과의 차별점: 안전점수 수치뿐 아니라 매칭된 문서 스니펫(근거 원문)을 프롬프트에
grounding 컨텍스트로 함께 주입해, 출처를 밝힐 수 있는 설명을 생성한다(PROJECT_PLAN.md 6장).
UPSTAGE_API_KEY가 없으면 동일한 데이터를 이용한 템플릿 기반 MOCK 설명으로 대체한다.
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from ..config import settings
from ..models import RouteCandidate
from . import gamification
from .weather import weather_summary_text

CHAT_COMPLETIONS_URL = "https://api.upstage.ai/v1/chat/completions"


def _grounding_context(candidate: RouteCandidate) -> str:
    if not candidate.features.matched_documents:
        return "(이 경로 주변에서 매칭된 문서 근거 없음)"
    lines = []
    for doc in candidate.features.matched_documents:
        tag = "위험지적" if doc.is_risk else "안전조치완료"
        lines.append(f"- [{tag}/{doc.risk_type}] 출처: {doc.source_doc} (경로에서 약 {doc.distance_m:.0f}m) — \"{doc.snippet}\"")
    return "\n".join(lines)


def _build_messages(
    candidate: RouteCandidate,
    other_candidates: list[RouteCandidate],
    audience_age: int,
    weather: Optional[dict[str, Any]] = None,
    time_context: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    f = candidate.features
    others_summary = ", ".join(
        f"{c.id}(점수 {c.safety_score}, {c.distance_m/1000:.1f}km)" for c in other_candidates if c.id != candidate.id
    ) or "없음"

    stamps_text = gamification.stamps_summary_text(
        [gamification.Stamp(s.id, s.emoji, s.label, s.description, s.count) for s in candidate.stamps]
    )

    time_ctx = time_context or {}
    time_block = ""
    if time_ctx:
        time_block = (
            f"\n[현재 시각·시간대 맥락]\n"
            f"- 현재 시각: {time_ctx.get('current_time', '알 수 없음')}\n"
            f"- 시간대: {time_ctx.get('period_label', '낮')} ({time_ctx.get('scoring_context', '')})\n"
            f"- 일몰: {time_ctx.get('sunset_time', '')} / 밤 시작: {time_ctx.get('night_start_time', '')}\n"
            f"- 도착 예상: {time_ctx.get('eta_message', '알 수 없음')}\n"
        )

    shared_facts = (
        f"[추천 경로 데이터]\n"
        f"- 거리: {f.distance_km}km / 예상 소요시간: 약 {round(candidate.duration_s/60)}분\n"
        f"- CCTV: {f.cctv_count}개 + 안심귀갓길 CCTV {f.safety_facility_cctv_count}대\n"
        f"- 보안등: {f.streetlight_count}개 + 안심귀갓길 보안등 {f.safety_facility_streetlight_count}개\n"
        f"- 안심벨: {f.safety_bell_count} · 112신고: {f.emergency112_count}\n"
        f"- 어린이보호구역 통과 비율: {f.child_zone_coverage_pct}%\n"
        f"- 사고다발지역: {f.accident_hotspot_count}곳\n"
        f"- 범죄위험 근사지수(0~100, 낮을수록 안전): {f.crime_risk_proxy}\n"
        f"- 아동안전지킴이집(위험 시 대피 가능): {f.guardian_house_count}곳\n"
        f"- 무인 교통단속카메라(과속 감시): {f.speed_camera_count}곳\n"
        f"- 안전점수: {candidate.safety_score}/100 ({time_ctx.get('scoring_context', '시간대 기준')}, 별점 {candidate.star_rating}/3)\n"
        f"- 획득한 안전 스탬프: {stamps_text}\n"
        f"- 다른 후보 경로: {others_summary}\n"
        f"- 현재 목적지 날씨: {weather_summary_text(weather)}\n"
        f"{time_block}\n"
        f"[문서 근거(통학로 안전진단 보고서 등에서 추출)]\n{_grounding_context(candidate)}"
    )

    parent_system = (
        "당신은 어린이 통학로 안전을 분석해 부모에게 브리핑하는 안전 전문가입니다. "
        "반드시 아래 제공된 데이터와 문서 근거'만' 사용해 사실에 기반한 설명을 작성하세요. "
        "제공되지 않은 수치나 시설을 지어내지 말고, 근거 없는 일반론도 쓰지 마세요.\n"
        "다음 구조로, 각 항목을 구체적인 수치와 함께 상세히 작성하세요(마크다운 소제목 사용):\n"
        "### ✅ 한줄 결론\n왜 이 경로를 추천하는지 1~2문장.\n"
        "### 📊 안전 근거\nCCTV·어린이보호구역·안전지킴이집·보안등·단속카메라 수치를 다른 후보 경로와 비교해 "
        "구체적으로 설명(예: 'CCTV가 1km당 N개로 ~').\n"
        "### ⚠️ 주의 구간\n사고다발지역·범죄위험·문서상 위험지적이 있으면 어디를 조심해야 하는지, "
        "문서 근거가 있으면 출처(보고서명)를 인용해 설명. 없으면 '특별한 위험 지적 없음'이라고 명시.\n"
        "### 🕒 시간·날씨 팁\n현재 시각·낮/밤 시간대에 맞는 안전 조언(밤이면 조명·CCTV, 낮이면 교통·횡단보도), "
        "도착 예상 시각, 그리고 현재 날씨를 고려한 등하교 팁을 덧붙이세요.\n"
        "전문적이되 부모가 이해하기 쉬운 존댓말로, 전체 8~12문장 분량으로 충실하게 작성하세요."
    )
    kid_system = (
        f"당신은 {audience_age}세 어린이에게 등하굣길을 설명하는 아주 친절하고 다정한 도우미입니다. "
        "반드시 아래 데이터에 기반해서 설명하되, 숫자나 어려운 용어(예: '안전점수', 'CCTV 밀도', "
        "'범죄위험지수')는 그대로 쓰지 말고 아이가 이해할 수 있는 쉬운 말로 바꿔서 설명하세요.\n"
        "쉬운 낱말과 짧은 문장으로 4~6문장 정도, 다음 내용을 담아 이야기하듯 말해주세요:\n"
        "1) 이 길이 왜 안전하고 좋은지 (CCTV·밝은 가로등·안전지킴이집 등을 아이 눈높이로),\n"
        "2) 걸을 때 무엇을 조심해야 하는지 (횡단보도, 차 조심 등),\n"
        "3) 현재 날씨에 맞는 한마디(비 오면 우산·미끄럼 조심 등),\n"
        "4) 마지막 문장에는 이 길에서 모은 '안전 스탬프'를 자랑하듯 신나게 언급해 뿌듯함을 주세요"
        "(예: 'CCTV 지킴이 스탬프도 모았어! 대단하지?'). 밝고 다정한 말투(반말)로 격려해 주세요."
    )

    return {
        "shared_facts": shared_facts,
        "parent_system": parent_system,
        "kid_system": kid_system,
    }


def _call_solar(system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
    resp = requests.post(
        CHAT_COMPLETIONS_URL,
        headers={"Authorization": f"Bearer {settings.upstage_api_key}", "Content-Type": "application/json"},
        json={
            "model": "solar-pro",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.5,
            "max_tokens": max_tokens,
        },
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _weather_parent_note(weather: Optional[dict[str, Any]]) -> str:
    if not weather:
        return ""
    if weather.get("is_rain"):
        return f" 현재 목적지 날씨는 '{weather.get('description')}'이라, 미끄럼과 시야 확보에 유의하고 우산·우비를 챙기세요."
    return f" 현재 목적지 날씨는 '{weather.get('description')}'입니다."


def _mock_parent_report(
    candidate: RouteCandidate,
    other_candidates: list[RouteCandidate],
    weather: Optional[dict[str, Any]] = None,
    time_context: Optional[dict[str, Any]] = None,
) -> str:
    f = candidate.features
    tc = time_context or {}
    slower = [c for c in other_candidates if c.distance_m < candidate.distance_m]
    time_note = ""
    if slower:
        fastest = min(other_candidates, key=lambda c: c.distance_m)
        delta_min = round((candidate.duration_s - fastest.duration_s) / 60, 1)
        if delta_min > 0:
            time_note = f"최단 경로보다 약 {delta_min}분 더 걸리지만, "
    doc_note = ""
    safe_docs = [d for d in f.matched_documents if not d.is_risk]
    risk_docs = [d for d in f.matched_documents if d.is_risk]
    if safe_docs:
        doc_note += f" 실제로 '{safe_docs[0].source_doc}'에 따르면 이 구간은 안전조치가 완료된 곳입니다."
    if risk_docs:
        doc_note += f" 다만 '{risk_docs[0].source_doc}'에서 '{risk_docs[0].risk_type}'이 지적된 구간이 있어 해당 지점은 주의가 필요합니다."
    extra_note = ""
    if f.guardian_house_count > 0:
        extra_note += f" 아동안전지킴이집도 {f.guardian_house_count}곳 있어 위험 시 대피할 수 있습니다."
    if f.speed_camera_count > 0:
        extra_note += f" 무인단속카메라({f.speed_camera_count}곳)로 차량 감속도 유도됩니다."
    stars = "⭐" * candidate.star_rating
    period_note = tc.get("recommendation_message", "")
    scoring_ctx = tc.get("scoring_context", "시간대 기준 안전도")
    eta = tc.get("eta_message", "")
    current = tc.get("current_time", "")
    night_tip = ""
    if tc.get("is_night"):
        night_tip = (
            f" 현재 {current}({scoring_ctx})이므로 보안등 {f.safety_facility_streetlight_count}개·"
            f"안심귀갓길 CCTV {f.safety_facility_cctv_count}대·안심벨 {f.safety_bell_count}개를 "
            f"우선 반영해 추천했습니다."
        )
    else:
        night_tip = (
            f" 현재 {current}({scoring_ctx})이므로 사고다발지역 {f.accident_hotspot_count}곳 회피와 "
            f"교통 안전(단속카메라 {f.speed_camera_count}곳)을 우선 반영했습니다."
        )
    return (
        f"### ✅ 한줄 결론\n{period_note}. {time_note}CCTV·어린이보호구역이 잘 갖춰져 다른 후보보다 안전한 추천 경로입니다.\n\n"
        f"### 📊 안전 근거 ({scoring_ctx})\n"
        f"CCTV {f.cctv_count}개 + 안심귀갓길 CCTV {f.safety_facility_cctv_count}대, "
        f"보안등 {f.streetlight_count}개 + 안심귀갓길 보안등 {f.safety_facility_streetlight_count}개, "
        f"안심벨 {f.safety_bell_count}개, 어린이보호구역 통과 {f.child_zone_coverage_pct}%, "
        f"안전지킴이집 {f.guardian_house_count}곳.\n\n"
        f"### ⚠️ 주의 구간\n사고다발지역 {f.accident_hotspot_count}곳, 범죄위험 근사지수 {f.crime_risk_proxy}.{doc_note}\n\n"
        f"### 🕒 시간·날씨 팁\n{eta}.{night_tip}{extra_note}{_weather_parent_note(weather)} "
        f"(종합 안전점수 {candidate.safety_score}/100, 안전등급 {stars})"
    )


def _mock_kid_report(
    candidate: RouteCandidate,
    audience_age: int,
    weather: Optional[dict[str, Any]] = None,
    time_context: Optional[dict[str, Any]] = None,
) -> str:
    f = candidate.features
    tc = time_context or {}
    crossing_note = "횡단보도를 조심해서 건너면" if f.accident_hotspot_count == 0 else "위험한 곳을 지날 때는 손을 들고 조심해서 건너면"
    weather_note = ""
    if weather and weather.get("is_rain"):
        weather_note = " 오늘은 비가 오니까 우산 꼭 챙기고, 바닥이 미끄러우니 뛰지 말고 천천히 걷자!"
    stamp_note = ""
    if candidate.stamps:
        stamp_labels = " ".join(f"{s.emoji}{s.label}" for s in candidate.stamps)
        stamp_note = f" 오늘은 {stamp_labels} 스탬프도 모았어요!"
    time_note = ""
    if tc.get("is_night"):
        time_note = " 지금은 밤이라 밝은 가로등이랑 CCTV 많은 길로 골랐어!"
    elif tc.get("period_label"):
        time_note = " 지금은 낮이라 차 조심하는 길로 골랐어!"
    if tc.get("eta_message"):
        time_note += f" {tc['eta_message']}!"
    return (
        f"이 길은 큰 도로를 따라가서 안전해요! CCTV 카메라가 {f.cctv_count + f.safety_facility_cctv_count}개나 있어서 지켜봐 주고, "
        f"밝은 가로등도 있어요. {crossing_note} 학교까지 안전하게 갈 수 있어요.{time_note}{weather_note}"
        f"{stamp_note}"
    )


def generate_reports(
    candidate: RouteCandidate,
    other_candidates: list[RouteCandidate],
    audience_age: int,
    weather: Optional[dict[str, Any]] = None,
    time_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if settings.upstage_mock:
        return {
            "parent_report": _mock_parent_report(candidate, other_candidates, weather, time_context),
            "kid_report": _mock_kid_report(candidate, audience_age, weather, time_context),
            "used_mock": True,
        }

    prompts = _build_messages(candidate, other_candidates, audience_age, weather, time_context)
    try:
        parent_report = _call_solar(prompts["parent_system"], prompts["shared_facts"], max_tokens=1100)
        kid_report = _call_solar(prompts["kid_system"], prompts["shared_facts"], max_tokens=700)
        return {"parent_report": parent_report, "kid_report": kid_report, "used_mock": False}
    except Exception as exc:  # 데모 안정성을 위해 API 실패 시 MOCK으로 폴백
        fallback = {
            "parent_report": _mock_parent_report(candidate, other_candidates, weather, time_context)
            + f"\n\n(Solar 호출 실패로 템플릿 대체: {exc})",
            "kid_report": _mock_kid_report(candidate, audience_age, weather, time_context),
            "used_mock": True,
        }
        return fallback
