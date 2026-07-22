"""안전 스탬프/배지 계산 — 새로운 외부 데이터나 API 없이, 이미 계산된 SafetyFeatures와
safety_score에서 파생시키는 가벼운 게이미피케이션 레이어.

목표: 아이가 "이 길이 왜 안전한지"를 숫자(안전점수 81점)가 아니라 눈에 보이는 스탬프로
이해하고, 더 안전한 경로를 재미있게 선택하도록 유도한다. 부모에게는 별점으로
경로 품질을 한눈에 보여준다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import SafetyFeatures

CHILD_ZONE_COVERAGE_THRESHOLD = 30.0
STREETLIGHT_DENSITY_THRESHOLD = 5.0  # 1km당 보안등 개수


@dataclass
class Stamp:
    id: str
    emoji: str
    label: str
    description: str
    count: int = 1


def compute_stamps(features: SafetyFeatures) -> list[Stamp]:
    stamps: list[Stamp] = []

    if features.cctv_count > 0 or features.safety_facility_cctv_count > 0:
        total_cctv = features.cctv_count + features.safety_facility_cctv_count
        stamps.append(
            Stamp(
                id="cctv_guardian",
                emoji="📸",
                label="CCTV 지킴이",
                description=f"CCTV가 지켜봐주는 구간을 {total_cctv}번 지났어요!",
                count=total_cctv,
            )
        )

    if features.child_zone_coverage_pct >= CHILD_ZONE_COVERAGE_THRESHOLD:
        stamps.append(
            Stamp(
                id="safe_zone_hero",
                emoji="🛡️",
                label="안전구역 히어로",
                description=f"어린이보호구역을 길의 {features.child_zone_coverage_pct:.0f}%나 씩씩하게 통과했어요!",
            )
        )

    if features.accident_hotspot_count == 0:
        stamps.append(
            Stamp(
                id="hazard_dodger",
                emoji="✅",
                label="위험 회피왕",
                description="사고 걱정 없는 길로만 다녔어요!",
            )
        )

    if features.guardian_house_count > 0:
        stamps.append(
            Stamp(
                id="guardian_house_ally",
                emoji="🏪",
                label="안전지킴이집 친구",
                description=f"위험할 때 뛰어갈 수 있는 아동안전지킴이집이 {features.guardian_house_count}곳 있어요!",
                count=features.guardian_house_count,
            )
        )

    if features.streetlight_density >= STREETLIGHT_DENSITY_THRESHOLD or features.safety_facility_streetlight_count >= 3:
        stamps.append(
            Stamp(
                id="bright_road",
                emoji="💡",
                label="밝은 가로등 길",
                description="가로등이 촘촘히 있어서 어두워져도 밝고 안전해요!",
            )
        )

    if features.safety_bell_count > 0:
        stamps.append(
            Stamp(
                id="safety_bell",
                emoji="🔔",
                label="안심벨 길",
                description=f"길가 안심벨이 {features.safety_bell_count}개 있어서 위험할 때 누를 수 있어요!",
                count=features.safety_bell_count,
            )
        )

    if features.speed_camera_count > 0:
        stamps.append(
            Stamp(
                id="speed_watch",
                emoji="📷",
                label="과속 감시 구간",
                description="무인 단속카메라가 있어서 자동차들이 속도를 줄이는 길이에요!",
                count=features.speed_camera_count,
            )
        )

    if features.doc_safety_count > 0:
        stamps.append(
            Stamp(
                id="report_verified",
                emoji="📋",
                label="안전 확인 배지",
                description="실제 안전점검 보고서로 안전이 확인된 길이에요!",
                count=features.doc_safety_count,
            )
        )

    if features.doc_risk_count == 0 and features.accident_hotspot_count == 0:
        stamps.append(
            Stamp(
                id="clean_route",
                emoji="🌟",
                label="클린 루트",
                description="위험 지적사항이 하나도 없는 깨끗한 길이에요!",
            )
        )

    return stamps


def compute_star_rating(safety_score: float) -> int:
    """안전점수를 부모가 한눈에 볼 수 있는 1~3점 별점으로 변환.

    컷은 사고다발 유무 경계 기준 (보통≥55, 안전≥70) — 오탐 최소화.
    """
    from ..config import settings

    if safety_score >= settings.safety_grade_high:
        return 3
    if safety_score >= settings.safety_grade_mid:
        return 2
    return 1


def safety_grade_label(safety_score: float) -> str:
    """UI용 등급 문구."""
    from ..config import settings

    if safety_score >= settings.safety_grade_high:
        return "안전"
    if safety_score >= settings.safety_grade_mid:
        return "보통"
    return "주의"


def stamps_summary_text(stamps: list[Stamp]) -> str:
    if not stamps:
        return "(획득한 안전 스탬프 없음)"
    return ", ".join(f"{s.emoji}{s.label}" + (f" x{s.count}" if s.count > 1 else "") for s in stamps)
