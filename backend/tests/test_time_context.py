"""시간대 수동 선택(auto/day/night) — 고정 시각·배너·ETA."""
from datetime import datetime

from app.services.time_context import (
    KST,
    build_time_context,
    is_nighttime,
    recommendation_message,
    resolve_evaluation_now,
)


def test_resolve_day_fixes_0800():
    base = datetime(2026, 7, 24, 15, 30, tzinfo=KST)
    fixed, mode = resolve_evaluation_now(time_mode="day", now=base)
    assert mode == "day"
    assert fixed.hour == 8 and fixed.minute == 0
    assert not is_nighttime(fixed)


def test_resolve_night_fixes_2100():
    base = datetime(2026, 7, 24, 10, 0, tzinfo=KST)
    fixed, mode = resolve_evaluation_now(time_mode="night", now=base)
    assert mode == "night"
    assert fixed.hour == 21 and fixed.minute == 0
    assert is_nighttime(fixed)


def test_resolve_auto_keeps_real_clock():
    base = datetime(2026, 7, 24, 14, 22, tzinfo=KST)
    fixed, mode = resolve_evaluation_now(time_mode="auto", now=base)
    assert mode == "auto"
    assert fixed == base


def test_build_time_context_night_eta_and_label():
    base = datetime(2026, 7, 24, 10, 0, tzinfo=KST)
    ctx = build_time_context(11 * 60, now=base, time_mode="night")
    assert ctx["is_night"] is True
    assert ctx["is_time_fixed"] is True
    assert ctx["time_mode"] == "night"
    assert ctx["fixed_time_label"] == "밤 기준으로 보는 중"
    assert ctx["recommendation_message"] == recommendation_message(True)
    assert "출발" in ctx["eta_message"] and "도착" in ctx["eta_message"]
    assert "지금 출발하면" not in ctx["eta_message"]


def test_build_time_context_auto_eta_unchanged_style():
    base = datetime(2026, 7, 24, 14, 0, tzinfo=KST)
    ctx = build_time_context(600, now=base, time_mode="auto")
    assert ctx["is_time_fixed"] is False
    assert ctx["fixed_time_label"] is None
    assert ctx["eta_message"].startswith("지금 출발하면")
    assert ctx["recommendation_message"] == recommendation_message(False)


def test_auto_force_night_keeps_clock_overrides_flag():
    base = datetime(2026, 7, 24, 14, 0, tzinfo=KST)
    ctx = build_time_context(600, now=base, force_night=True, time_mode="auto")
    assert ctx["is_night"] is True
    assert ctx["current_time"]  # real afternoon clock string
    assert ctx["is_time_fixed"] is False
