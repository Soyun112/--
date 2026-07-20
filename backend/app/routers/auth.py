from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

import jwt
import requests
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..config import settings
from ..services.google_auth import build_authorization_url, exchange_code_for_user
from ..services.jwt_tokens import create_access_token, create_oauth_state, decode_oauth_state, decode_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class UserProfile(BaseModel):
    sub: str
    email: str
    name: str
    picture: str | None = None


class LogoutResponse(BaseModel):
    ok: bool = True


def _require_auth_config() -> None:
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth가 설정되지 않았습니다. GOOGLE_CLIENT_ID/SECRET, JWT_SECRET, GOOGLE_REDIRECT_URI를 확인하세요.",
        )


def _parse_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return token


def _profile_from_payload(payload: dict) -> UserProfile:
    return UserProfile(
        sub=str(payload.get("sub", "")),
        email=str(payload.get("email", "")),
        name=str(payload.get("name", "")),
        picture=payload.get("picture"),
    )


@router.get("/google/login")
def google_login(frontend_url: Annotated[str, Query(description="로그인 후 돌아갈 프론트 URL")]) -> RedirectResponse:
    _require_auth_config()
    normalized = frontend_url.rstrip("/")
    if not settings.is_allowed_frontend_url(normalized):
        raise HTTPException(status_code=400, detail="허용되지 않은 frontend_url 입니다.")
    state = create_oauth_state(frontend_url=normalized)
    return RedirectResponse(build_authorization_url(state=state), status_code=302)


@router.get("/google/callback")
def google_callback(
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    _require_auth_config()
    fallback = settings.default_frontend_url

    if error:
        return RedirectResponse(f"{fallback}?auth_error={quote(error)}", status_code=302)
    if not code or not state:
        return RedirectResponse(f"{fallback}?auth_error=missing_code", status_code=302)

    try:
        state_payload = decode_oauth_state(state)
        frontend_url = str(state_payload.get("frontend_url") or fallback).rstrip("/")
        if not settings.is_allowed_frontend_url(frontend_url):
            frontend_url = fallback

        profile = exchange_code_for_user(code)
        token = create_access_token(
            sub=profile["sub"],
            email=profile["email"],
            name=profile["name"],
            picture=profile.get("picture"),
        )
        safe_token = quote(token, safe="")
        return RedirectResponse(f"{frontend_url}/#access_token={safe_token}", status_code=302)
    except jwt.PyJWTError:
        return RedirectResponse(f"{fallback}?auth_error=invalid_state", status_code=302)
    except requests.HTTPError:
        return RedirectResponse(f"{fallback}?auth_error=google_token_failed", status_code=302)
    except Exception:
        return RedirectResponse(f"{fallback}?auth_error=login_failed", status_code=302)


@router.get("/me", response_model=UserProfile)
def auth_me(authorization: Annotated[str | None, Header()] = None) -> UserProfile:
    _require_auth_config()
    token = _parse_bearer(authorization)
    try:
        payload = decode_token(token)
        if payload.get("typ") != "access":
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
        return _profile_from_payload(payload)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="로그인이 만료되었습니다.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.") from exc


@router.get("/status")
def auth_status() -> dict:
    return {
        "enabled": settings.auth_enabled,
        "configured": settings.auth_config_status,
    }


@router.post("/logout", response_model=LogoutResponse)
def auth_logout() -> LogoutResponse:
    return LogoutResponse(ok=True)
