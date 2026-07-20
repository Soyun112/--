"""JWT 발급·검증 (Google OAuth 세션용)."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from ..config import settings

ALGORITHM = "HS256"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode_jwt(payload: dict[str, Any]) -> str:
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return str(token)


def create_access_token(*, sub: str, email: str, name: str, picture: str | None) -> str:
    expire = _now() + timedelta(hours=settings.jwt_expire_hours)
    now = _now()
    payload = {
        "sub": str(sub),
        "email": str(email),
        "name": str(name),
        "picture": str(picture) if picture else None,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "typ": "access",
    }
    return _encode_jwt(payload)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])


def create_oauth_state(*, frontend_url: str) -> str:
    expire = _now() + timedelta(minutes=10)
    now = _now()
    payload = {
        "frontend_url": frontend_url,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "typ": "oauth_state",
    }
    return _encode_jwt(payload)


def decode_oauth_state(state: str) -> dict[str, Any]:
    payload = jwt.decode(token=state, key=settings.jwt_secret, algorithms=[ALGORITHM])
    if payload.get("typ") != "oauth_state":
        raise jwt.InvalidTokenError("invalid oauth state")
    return payload
