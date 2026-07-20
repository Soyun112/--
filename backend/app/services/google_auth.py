"""Google OAuth 2.0 (Authorization Code) 연동."""
from __future__ import annotations

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
    if not access_token:
        raise RuntimeError("Google token response missing access_token")

    user_resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    user_resp.raise_for_status()
    profile = user_resp.json()
    return {
        "sub": str(profile.get("sub", "")),
        "email": profile.get("email", ""),
        "name": profile.get("name") or profile.get("email") or "사용자",
        "picture": profile.get("picture"),
    }
