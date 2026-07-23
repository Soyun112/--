from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.kid_guide_share import create_share, get_share

router = APIRouter(prefix="/api/share", tags=["share"])


class KidGuideStep(BaseModel):
    icon: str = "↑"
    keyword: str
    friendly: str = ""
    tip: str = ""
    distance_m: float = 0
    landmark: str = ""
    is_arrive: bool = False


class KidGuideShareCreate(BaseModel):
    title: str = "오늘의 안전 길"
    origin: str = ""
    destination: str = ""
    # 점수·거리는 소수로 산출되므로 float 유지 (반올림 저장 금지)
    safety_score: float | None = None
    duration_min: float | None = None
    steps: list[KidGuideStep] = Field(min_length=1)


class KidGuideShareResponse(BaseModel):
    id: str
    expires_at: str


def _create_response(body: KidGuideShareCreate) -> KidGuideShareResponse:
    result = create_share(body.model_dump())
    return KidGuideShareResponse(**result)


@router.post("", response_model=KidGuideShareResponse)
@router.post("/", response_model=KidGuideShareResponse, include_in_schema=False)
def post_share(body: KidGuideShareCreate) -> KidGuideShareResponse:
    """짧은 ID 공유 링크 생성. POST /api/share"""
    return _create_response(body)


@router.post("/kid-guide", response_model=KidGuideShareResponse)
def post_kid_guide_share(body: KidGuideShareCreate) -> KidGuideShareResponse:
    """하위 호환: POST /api/share/kid-guide"""
    return _create_response(body)


@router.get("/kid-guide/{share_id}")
def get_kid_guide_share(share_id: str) -> dict:
    payload = get_share(share_id.strip())
    if not payload:
        raise HTTPException(status_code=404, detail="공유 링크를 찾을 수 없거나 만료되었습니다.")
    return payload


@router.get("/{share_id}")
def get_share_by_id(share_id: str) -> dict:
    """짧은 경로: GET /api/share/{id}"""
    if share_id in {"kid-guide", ""}:
        raise HTTPException(status_code=404, detail="공유 링크를 찾을 수 없거나 만료되었습니다.")
    payload = get_share(share_id.strip())
    if not payload:
        raise HTTPException(status_code=404, detail="공유 링크를 찾을 수 없거나 만료되었습니다.")
    return payload
