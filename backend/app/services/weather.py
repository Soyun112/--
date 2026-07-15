"""기상청 초단기실황(단기예보 조회서비스) 연동.

목적지 좌표의 실시간 강수/기온/습도를 받아, 안전점수 설명에 "비 오는 날 통학로"
같은 맥락을 추가한다. 위경도를 기상청 격자(nx, ny)로 바꾸는 Lambert 변환은 기상청
공식 그대로다. data.go.kr 서비스키(KMA_SERVICE_KEY 또는 DATA_GO_KR_SERVICE_KEY)를
재사용한다. 키가 없거나 호출 실패 시 None을 반환하고 서비스는 정상 동작한다.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from ..config import settings

ULTRA_SRT_NCST_URL = (
    "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
)

# 강수형태(PTY) 코드 -> (설명, 비/눈 여부)
PTY_MAP: dict[int, tuple[str, bool]] = {
    0: ("강수 없음", False),
    1: ("비", True),
    2: ("비/눈", True),
    3: ("눈", True),
    5: ("빗방울", True),
    6: ("빗방울/눈날림", True),
    7: ("눈날림", True),
}


def _dfs_xy_conv(lat: float, lon: float) -> tuple[int, int]:
    """위경도 -> 기상청 격자좌표(nx, ny). 기상청 제공 Lambert Conformal Conic 공식."""
    RE, GRID = 6371.00877, 5.0
    SLAT1, SLAT2, OLON, OLAT, XO, YO = 30.0, 60.0, 126.0, 38.0, 43, 136
    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1, slat2 = SLAT1 * DEGRAD, SLAT2 * DEGRAD
    olon, olat = OLON * DEGRAD, OLAT * DEGRAD
    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf**sn * math.cos(slat1)) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = (re * sf) / ro**sn
    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = (re * sf) / ra**sn
    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    nx = int(math.floor(ra * math.sin(theta) + XO + 0.5))
    ny = int(math.floor(ro - ra * math.cos(theta) + YO + 0.5))
    return nx, ny


def _base_date_time() -> tuple[str, str]:
    """초단기실황은 매시 정시 발표·40분 이후 제공 → 40분 빼서 직전 정시 사용."""
    now = datetime.now() - timedelta(minutes=40)
    return now.strftime("%Y%m%d"), now.strftime("%H00")


def fetch_weather(lat: float, lon: float) -> Optional[dict[str, Any]]:
    key = settings.kma_service_key
    if not key or settings.force_mock:
        return None

    nx, ny = _dfs_xy_conv(lat, lon)
    base_date, base_time = _base_date_time()
    try:
        resp = requests.get(
            ULTRA_SRT_NCST_URL,
            params={
                "serviceKey": key,
                "dataType": "JSON",
                "numOfRows": 100,
                "pageNo": 1,
                "base_date": base_date,
                "base_time": base_time,
                "nx": nx,
                "ny": ny,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = (
            resp.json()
            .get("response", {})
            .get("body", {})
            .get("items", {})
            .get("item", [])
        )
        if not items:
            return None
        obs = {it["category"]: it["obsrValue"] for it in items}
    except Exception:
        return None

    pty = int(float(obs.get("PTY", 0) or 0))
    desc, is_rain = PTY_MAP.get(pty, ("정보없음", False))
    rn1 = obs.get("RN1")  # 1시간 강수량(mm)
    return {
        "pty": pty,
        "description": desc,
        "is_rain": is_rain,
        "rain_mm": rn1,
        "temperature_c": obs.get("T1H"),
        "humidity_pct": obs.get("REH"),
    }


def weather_summary_text(weather: Optional[dict[str, Any]]) -> str:
    """Solar 프롬프트/화면용 한 줄 요약."""
    if not weather:
        return "(날씨 정보 없음)"
    parts = [weather.get("description", "")]
    if weather.get("temperature_c") not in (None, ""):
        parts.append(f"기온 {weather['temperature_c']}도")
    if weather.get("humidity_pct") not in (None, ""):
        parts.append(f"습도 {weather['humidity_pct']}%")
    rn = weather.get("rain_mm")
    if weather.get("is_rain") and rn not in (None, "", "0", "강수없음"):
        parts.append(f"강수 {rn}mm")
    return " · ".join([p for p in parts if p])
