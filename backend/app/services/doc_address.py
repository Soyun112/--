"""문서 위치도 주소: 정규식 파싱 · 재조립 · 자치구 prefix · 동→구 매핑.

헤더 도로명과 시점/종점 도로명은 절대 합치지 않는다.
시점·종점은 그 자체로 완전한 도로명주소다.
"""
from __future__ import annotations

import re
from typing import Any

# 강남구 법정동 (행정동 숫자 제거 후 매칭)
_GANGNAM_LEGAL_DONGS = {
    "역삼동",
    "도곡동",
    "대치동",
    "삼성동",
    "청담동",
    "신사동",
    "논현동",
    "압구정동",
    "개포동",
    "일원동",
    "수서동",
    "세곡동",
    "자곡동",
    "율현동",
    "논현동",
    "포이동",
}

# 도로명 제목: 논현로 76길 / 테헤란로108길 / 선릉로
_ROAD_TITLE = (
    r"(?:"
    r"[가-힣A-Za-z0-9]+(?:로|대로)\s*\d+\s*번?길|"
    r"[가-힣A-Za-z0-9]+\d+\s*번?길|"
    r"[가-힣A-Za-z0-9]+(?:로|길|대로)"
    r")"
)
# 도로명+번지: 도곡로194 / 논현로 76길 21 / 선릉로 305
_ROAD_ADDR = rf"(?:{_ROAD_TITLE})\s*\d+(?:\s*-\s*\d+)?"

_ROAD_PARTS = re.compile(
    r"^(?P<base>.+?로)\s*(?P<gil>\d+\s*번?길)?\s*(?P<num>\d+(?:\s*-\s*\d+)?)$"
)

_SECTION_RE = re.compile(
    rf"[①②③④⑤⑥⑦⑧⑨⑩]?\s*"
    rf"(?:위\s*치\s*)?"
    rf"(?P<header>{_ROAD_TITLE})\s*"
    rf"\(\s*(?P<body>[^)]+?)\s*\)",
    re.MULTILINE,
)

_BODY_RE = re.compile(
    rf"(?P<start>{_ROAD_ADDR})\s*[~～〜\-–—]\s*(?P<end>{_ROAD_ADDR})"
    rf"(?:\s*,\s*(?P<dong>[가-힣0-9]+동))?",
)


def legal_dong(dong: str) -> str:
    """행정동 역삼2동 → 법정동 역삼동."""
    s = (dong or "").strip()
    return re.sub(r"\d+동$", "동", s)


def gu_prefix_from_dong(dong: str) -> str:
    """동에서 자치구를 코드로 확정. Solar/사용자 입력에 맡기지 않음."""
    legal = legal_dong(dong)
    if legal in _GANGNAM_LEGAL_DONGS:
        return "서울특별시 강남구"
    # 문서 기본 범위가 강남 공사 고시
    if legal.endswith("동") and legal:
        return "서울특별시 강남구"
    return "서울특별시 강남구"


def normalize_road_title(title: str) -> str:
    """논현로  76길 → 논현로 76길."""
    s = re.sub(r"\s+", " ", (title or "").strip())
    s = re.sub(r"(.+?로)\s*(\d+)\s*(번?길)", r"\1 \2\3", s)
    return s


def normalize_road_address(addr: str) -> str:
    """도곡로194 → 도곡로 194, 논현로76길21 → 논현로 76길 21."""
    raw = re.sub(r"\s+", "", (addr or "").strip())
    if not raw:
        return ""
    m = _ROAD_PARTS.match(raw)
    if not m:
        # 느슨: 길/로 뒤 숫자만 분리
        loose = re.match(rf"^({_ROAD_TITLE})(\d+(?:-\d+)?)$", raw)
        if loose:
            return f"{normalize_road_title(loose.group(1))} {loose.group(2)}"
        return (addr or "").strip()
    base = m.group("base")
    gil = m.group("gil")
    num = m.group("num")
    if gil:
        gil_n = re.sub(r"\s+", "", gil)
        return f"{base} {gil_n} {num}".strip()
    return f"{base} {num}".strip()


def build_geocode_query(road_addr: str, *, dong: str = "") -> str:
    """재조립된 도로명주소 + 자치구 prefix (코드 주입)."""
    body = normalize_road_address(road_addr)
    if not body:
        return ""
    prefix = gu_prefix_from_dong(dong) if dong else "서울특별시 강남구"
    # 이미 prefix 있으면 body만 정규화
    if body.startswith("서울"):
        rest = re.sub(r"^서울(?:특별시)?\s*(?:강남구)?\s*", "", body).strip()
        body = normalize_road_address(rest) if rest else body
    return f"{prefix} {body}".strip()


def parse_location_map_segments(text: str) -> list[dict[str, Any]]:
    """위치도 줄 파싱 → {header_road, start, end, dong, queries}.

    예) ① 위 치  선릉로(역삼로 314 ~ 선릉로 305, 역삼2동)
    """
    raw = text or ""
    if not raw.strip():
        return []

    points: list[dict[str, Any]] = []
    seen: set[str] = set()

    for match in _SECTION_RE.finditer(raw):
        header = normalize_road_title(match.group("header"))
        body = match.group("body") or ""
        bm = _BODY_RE.search(body)
        if not bm:
            continue
        start_raw = bm.group("start").strip()
        end_raw = bm.group("end").strip()
        dong = (bm.group("dong") or "").strip()
        # body에 동이 없으면 헤더 옆 구식 형식 대비 — 없음
        start_n = normalize_road_address(start_raw)
        end_n = normalize_road_address(end_raw)
        start_q = build_geocode_query(start_n, dong=dong)
        end_q = build_geocode_query(end_n, dong=dong)
        key = re.sub(r"\s+", "", f"{start_q}~{end_q}".lower())
        if not key or key in seen:
            continue
        seen.add(key)
        loc = f"{header}({start_n} ~ {end_n}" + (f", {dong})" if dong else ")")
        points.append(
            {
                "location_text": loc,
                "header_road": header,
                "dong": dong,
                "legal_dong": legal_dong(dong) if dong else "",
                "start_raw": start_raw,
                "end_raw": end_raw,
                "geocode_query": start_q,
                "start_geocode_query": start_q,
                "end_geocode_query": end_q,
                "confidence": 0.95,
                "normalize_note": "위치도 규칙(헤더≠끝점, 재조립, 동→구)",
                "risk_type": "공사/정비 구간",
                "is_risk": True,
                "snippet": match.group(0).strip()[:200],
                "recommendation": "공사 구간 통행 시 주의",
            }
        )
    return points
