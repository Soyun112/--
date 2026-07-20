"""Google OAuth 2.0 (Authorization Code) 연동."""
from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlencode

import requests

from ..config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES = "openid email profile"


class GoogleTokenExchangeError(Exception):
    def __init__(self, google_error: str, description: str = "") -> None:
        self.google_error = google_error
        self.description = description
        super().__init__(google_error)


def _decode_id_token_payload(id_token: str) -> dict[str, Any]:
    parts = id_token.split(".")
    if len(parts) != 3:
        return {}
    padding = "=" * (-len(parts[1]) % 4)
    payload = base64.urlsafe_b64decode(parts[1] + padding)
    return json.loads(payload)


def _profile_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
    return {
        "sub": str(claims.get("sub", "")),
        "email": str(claims.get("email") or ""),
        "name": str(claims.get("name") or claims.get("email") or "사용자"),
        "picture": claims.get("picture"),
    }


def build_authorization_url(*, state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_user(code: str) -> dict[str, Any]:
    token_resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if not token_resp.ok:
        try:
            body = token_resp.json()
            err = str(body.get("error") or "unknown")
            desc = str(body.get("error_description") or "")
        except Exception:
            err = "http_error"
            desc = str(token_resp.status_code)
        raise GoogleTokenExchangeError(err, desc)
    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    id_token = tokens.get("id_token")

    profile: dict[str, Any] = {}
    if id_token:
        try:
            profile = _profile_from_claims(_decode_id_token_payload(id_token))
        except Exception:
            profile = {}

    if not profile.get("sub") and access_token:
        user_resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if not user_resp.ok:
            try:
                body = user_resp.json()
                err = str(body.get("error") or "userinfo_failed")
            except Exception:
                err = "userinfo_failed"
            raise GoogleTokenExchangeError(err, str(user_resp.status_code))
        profile = _profile_from_claims(user_resp.json())

    if not profile.get("sub"):
        raise RuntimeError("google_profile_missing_sub")

    return profile
