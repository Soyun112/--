from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..services.jwt_tokens import decode_token
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
    safety_score: int | None = None
    duration_min: int | None = None
    steps: list[KidGuideStep] = Field(min_length=1)


class KidGuideShareResponse(BaseModel):
    id: str
    expires_at: str


def _require_user(authorization: Annotated[str | None, Header()] = None) -> None:
    if not settings.auth_enabled:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    token = authorization[7:].strip()
    try:
        payload = decode_token(token)
        if payload.get("typ") != "access":
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.") from exc


@router.post("/kid-guide", response_model=KidGuideShareResponse)
def post_kid_guide_share(
    body: KidGuideShareCreate,
    authorization: Annotated[str | None, Header()] = None,
) -> KidGuideShareResponse:
    _require_user(authorization)
    result = create_share(body.model_dump())
    return KidGuideShareResponse(**result)


@router.get("/kid-guide/{share_id}")
def get_kid_guide_share(share_id: str) -> dict:
    payload = get_share(share_id.strip())
    if not payload:
        raise HTTPException(status_code=404, detail="공유 링크를 찾을 수 없거나 만료되었습니다.")
    return payload
