"""아이용 길 안내 카드 공유 링크 저장."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import session

SHARE_TTL_HOURS = 168  # 7일


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def ensure_share_table() -> None:
    with session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kid_guide_shares (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_kid_guide_shares_expires ON kid_guide_shares(expires_at)"
        )


def create_share(payload: dict[str, Any]) -> dict[str, str]:
    ensure_share_table()
    share_id = secrets.token_urlsafe(9)
    created = _utc_now()
    expires = created + timedelta(hours=SHARE_TTL_HOURS)
    with session() as conn:
        conn.execute(
            "INSERT INTO kid_guide_shares (id, payload_json, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (share_id, json.dumps(payload, ensure_ascii=False), _iso(created), _iso(expires)),
        )
    return {"id": share_id, "expires_at": _iso(expires)}


def get_share(share_id: str) -> dict[str, Any] | None:
    ensure_share_table()
    with session() as conn:
        row = conn.execute(
            "SELECT payload_json, expires_at FROM kid_guide_shares WHERE id = ?",
            (share_id,),
        ).fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if _utc_now() > expires_at:
        return None
    payload = json.loads(row["payload_json"])
    payload["expires_at"] = row["expires_at"]
    return payload
