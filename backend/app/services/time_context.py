"""현재 시각·낮/밤 판별·도착 예상·시간대별 안내 문구.

서울(위도 ~37.5) 기준 계절별 일몰 근사치를 쓰고, 사용자 기준(오후 7시~오전 6시)과
합쳐 더 이른 시각을 밤 시작으로 본다. 예) 12월 일몰 17:30 → 17:30부터 밤,
6월 일몰 20:00 → 19:00부터 밤.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..config import settings

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
    return "지금은 낮이라 차량이 적고 시야가 트인 길을 추천해요"


def scoring_context_label(is_night: bool) -> str:
    return "밤 시간대 기준 안전도" if is_night else "낮 시간대 기준 안전도"


def scoring_weights(is_night: bool) -> dict[str, float]:
    """주간/야간 절대 가중치 표 (배율 방식이 아님)."""
    return dict(settings.weights_night if is_night else settings.weights)


def apply_time_weights(base_weights: dict[str, float], is_night: bool) -> dict[str, float]:
    """하위 호환 — 새 코드는 scoring_weights() 사용."""
    del base_weights
    return scoring_weights(is_night)


def normalize_time_mode(time_mode: str | None) -> str:
    mode = (time_mode or "auto").strip().lower()
    return mode if mode in ("auto", "day", "night") else "auto"


def resolve_evaluation_now(
    *,
    time_mode: str | None = None,
    now: datetime | None = None,
) -> tuple[datetime, str]:
    """채점·ETA에 쓸 기준 시각.

    - auto: 실제 현재 시각
    - day:  오늘 08:00 KST
    - night: 오늘 21:00 KST
    """
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    else:
        current = current.astimezone(KST)

    mode = normalize_time_mode(time_mode)
    if mode == "day":
        return current.replace(hour=8, minute=0, second=0, microsecond=0), mode
    if mode == "night":
        return current.replace(hour=21, minute=0, second=0, microsecond=0), mode
    return current, mode


def build_time_context(
    duration_s: float | None = None,
    now: datetime | None = None,
    *,
    force_night: bool | None = None,
    time_mode: str | None = None,
) -> dict[str, Any]:
    """API·리포트용 시간 맥락 dict."""
    mode = normalize_time_mode(time_mode)
    current, mode = resolve_evaluation_now(time_mode=mode, now=now)

    # auto + force_night: 기존처럼 시계는 실제 시각, 밤 여부만 덮어씀
    if mode == "auto" and force_night is not None:
        night = bool(force_night)
    else:
        night = is_nighttime(current)

    sh, sm = sunset_time_for(current)
    ns_h = night_start_minutes(current) // 60
    ns_m = night_start_minutes(current) % 60
    is_fixed = mode in ("day", "night")

    ctx: dict[str, Any] = {
        "current_time": format_korean_time(current),
        "current_time_iso": current.isoformat(),
        "is_night": night,
        "period_label": "밤" if night else "낮",
        "period_emoji": "🌙" if night else "☀️",
        "recommendation_message": recommendation_message(night),
        "scoring_context": scoring_context_label(night),
        "sunset_time": f"{sh}:{sm:02d}",
        "night_start_time": format_korean_time(
            current.replace(hour=ns_h, minute=ns_m, second=0, microsecond=0)
        ),
        "night_end_time": f"오전 {NIGHT_END_HOUR}:00",
        "time_mode": mode,
        "is_time_fixed": is_fixed,
        # 자동일 때만: 지금이 낮/밤 중 어느 기준으로 보고 있는지 안내
        # (낮·밤 수동 선택 시에는 토글이 이미 기준이라 라벨 생략)
        "fixed_time_label": (
            ("밤 기준으로 보는 중" if night else "낮 기준으로 보는 중") if not is_fixed else None
        ),
    }

    if duration_s is not None and duration_s > 0:
        arrival = current + timedelta(seconds=duration_s)
        ctx["arrival_time"] = format_korean_time(arrival)
        ctx["arrival_time_iso"] = arrival.isoformat()
        if is_fixed:
            ctx["eta_message"] = (
                f"{format_korean_time(current)} 출발 → {format_korean_time(arrival)} 도착"
            )
        else:
            ctx["eta_message"] = f"지금 출발하면 약 {format_korean_time(arrival)} 도착"
        ctx["duration_minutes"] = round(duration_s / 60)

    return ctx
