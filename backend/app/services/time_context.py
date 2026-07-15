"""현재 시각·낮/밤 판별·도착 예상·시간대별 안내 문구.

서울(위도 ~37.5) 기준 계절별 일몰 근사치를 쓰고, 사용자 기준(오후 7시~오전 6시)과
합쳐 더 이른 시각을 밤 시작으로 본다. 예) 12월 일몰 17:30 → 17:30부터 밤,
6월 일몰 20:00 → 19:00부터 밤.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 서울 월별 일몰 시각 근사 (시, 분)
_SUNSET_BY_MONTH: dict[int, tuple[int, int]] = {
    1: (17, 20),
    2: (17, 50),
    3: (18, 20),
    4: (19, 0),
    5: (19, 30),
    6: (19, 50),
    7: (19, 45),
    8: (19, 15),
    9: (18, 35),
    10: (18, 0),
    11: (17, 30),
    12: (17, 15),
}

NIGHT_END_HOUR = 6  # 오전 6시까지 밤
DEFAULT_NIGHT_START_HOUR = 19  # 오후 7시 (일몰이 더 늦으면 이 시각부터)


def _minutes_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def sunset_time_for(dt: datetime) -> tuple[int, int]:
    """해당 날짜(월)의 일몰 시각 (시, 분)."""
    return _SUNSET_BY_MONTH.get(dt.month, (18, 30))


def night_start_minutes(dt: datetime) -> int:
    """밤 시작 시각(분). 일몰과 19:00 중 더 이른 시각."""
    sh, sm = sunset_time_for(dt)
    sunset_min = sh * 60 + sm
    default_min = DEFAULT_NIGHT_START_HOUR * 60
    return min(sunset_min, default_min)


def is_nighttime(dt: datetime | None = None) -> bool:
    now = dt or datetime.now(KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)

    mins = _minutes_of_day(now)
    if mins < NIGHT_END_HOUR * 60:
        return True
    return mins >= night_start_minutes(now)


def format_korean_time(dt: datetime) -> str:
    """예: '오후 6:30', '오전 7:05'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    else:
        dt = dt.astimezone(KST)
    hour = dt.hour
    minute = dt.minute
    if hour < 12:
        period = "오전"
        display_hour = 12 if hour == 0 else hour
    elif hour == 12:
        period = "오후"
        display_hour = 12
    else:
        period = "오후"
        display_hour = hour - 12
    return f"{period} {display_hour}:{minute:02d}"


def recommendation_message(is_night: bool) -> str:
    if is_night:
        return "지금은 밤이라 밝고 CCTV 많은 길을 추천해요"
    return "지금은 낮이라 사고 위험 적은 길을 추천해요"


def scoring_context_label(is_night: bool) -> str:
    return "밤 시간대 기준 안전도" if is_night else "낮 시간대 기준 안전도"


def apply_time_weights(base_weights: dict[str, float], is_night: bool) -> dict[str, float]:
    """낮/밤에 따라 가중치 배율 적용."""
    w = dict(base_weights)
    if is_night:
        # 밤: 보안등·CCTV·안심벨·112 가점 크게
        multipliers = {
            "safety_facility_cctv": 2.0,
            "safety_facility_streetlight": 2.0,
            "safety_bell": 1.6,
            "emergency112": 1.4,
            "streetlight_density": 1.5,
            "cctv_density": 1.3,
            "guardian_house": 1.2,
            "crime_risk": 1.3,
            "accident_hotspot": 0.75,
            "speed_camera": 0.85,
            "doc_risk": 0.9,
        }
    else:
        # 낮: 사고다발·교통(단속카메라)·범죄·문서 위험 회피 강조
        multipliers = {
            "accident_hotspot": 1.7,
            "crime_risk": 1.4,
            "speed_camera": 1.5,
            "doc_risk": 1.3,
            "child_zone_coverage": 1.15,
            "safety_facility_cctv": 0.9,
            "safety_facility_streetlight": 0.85,
            "safety_bell": 0.9,
            "streetlight_density": 0.85,
        }
    for key, mult in multipliers.items():
        if key in w:
            w[key] *= mult
    return w


def build_time_context(duration_s: float | None = None, now: datetime | None = None) -> dict[str, Any]:
    """API·리포트용 시간 맥락 dict."""
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    else:
        current = current.astimezone(KST)

    night = is_nighttime(current)
    sh, sm = sunset_time_for(current)
    ns_h = night_start_minutes(current) // 60
    ns_m = night_start_minutes(current) % 60

    ctx: dict[str, Any] = {
        "current_time": format_korean_time(current),
        "current_time_iso": current.isoformat(),
        "is_night": night,
        "period_label": "밤" if night else "낮",
        "period_emoji": "🌙" if night else "☀️",
        "recommendation_message": recommendation_message(night),
        "scoring_context": scoring_context_label(night),
        "sunset_time": f"{sh}:{sm:02d}",
        "night_start_time": format_korean_time(current.replace(hour=ns_h, minute=ns_m, second=0, microsecond=0)),
        "night_end_time": f"오전 {NIGHT_END_HOUR}:00",
    }

    if duration_s is not None and duration_s > 0:
        arrival = current + timedelta(seconds=duration_s)
        ctx["arrival_time"] = format_korean_time(arrival)
        ctx["arrival_time_iso"] = arrival.isoformat()
        ctx["eta_message"] = f"지금 출발하면 약 {format_korean_time(arrival)} 도착"
        ctx["duration_minutes"] = round(duration_s / 60)

    return ctx
