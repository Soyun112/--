from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import db
from ..config import settings
from ..models import (
    DocumentIngestResult,
    DocumentPointConfirmRequest,
    DocumentPointConfirmResult,
    DocumentRiskPoint,
)
from ..services.document_pipeline import confirm_document_point, ingest_document

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".hwp", ".hwpx", ".md", ".txt"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
_SAFE_NAME_RE = re.compile(r"[^\w.\-()\[\]\uac00-\ud7a3 ]+", re.UNICODE)


def _safe_filename(filename: str) -> str:
    name = Path(filename or "").name.strip() or "document"
    name = _SAFE_NAME_RE.sub("_", name).strip(" ._")
    if not name:
        name = "document"
    # 경로 조작 방지
    return Path(name).name


def _save_upload(contents: bytes, filename: str) -> str:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_filename(filename)
    path = settings.uploads_dir / safe
    path.write_bytes(contents)
    return safe


def _clear_uploads() -> None:
    uploads = settings.uploads_dir
    if not uploads.is_dir():
        return
    for path in uploads.iterdir():
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


def _resolve_upload(filename: str) -> Path:
    safe = _safe_filename(filename)
    base = settings.uploads_dir.resolve()
    path = (settings.uploads_dir / safe).resolve()
    if path != base and base not in path.parents:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="원본 파일이 없습니다. 문서를 다시 올려 주세요.",
        )
    return path


def _to_risk_point(row) -> DocumentRiskPoint:
    keys = set(row.keys())
    return DocumentRiskPoint(
        id=row["id"],
        lat=row["lat"],
        lng=row["lng"],
        end_lat=row["end_lat"] if "end_lat" in keys else None,
        end_lng=row["end_lng"] if "end_lng" in keys else None,
        location_text=row["location_text"] if "location_text" in keys else None,
        geocode_query=row["geocode_query"] if "geocode_query" in keys else None,
        end_geocode_query=row["end_geocode_query"] if "end_geocode_query" in keys else None,
        matched_label=row["matched_label"] if "matched_label" in keys else None,
        risk_type=row["risk_type"] or "",
        is_risk=bool(row["is_risk"]),
        snippet=row["snippet"] or "",
        source_doc=row["source_doc"] or "",
        page=row["page"],
        report_date=row["report_date"],
        recommendation=row["recommendation"],
        is_estimated=bool(row["is_estimated"]) if "is_estimated" in keys else False,
    )


@router.post("/ingest", response_model=DocumentIngestResult)
async def ingest(
    file: UploadFile = File(...),
    region_hint: str = Form(""),
) -> DocumentIngestResult:
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일명이 없습니다.")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식입니다. 허용: {', '.join(sorted(ALLOWED_SUFFIXES))}",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="파일 크기는 15MB 이하여야 합니다.")

    saved_name = _save_upload(contents, file.filename)

    try:
        # 이전 핀은 DELETE /api/documents 또는 클라이언트가 이미 비운 뒤 호출한다.
        # 여러 파일을 연속 올릴 때 앞 문서 핀이 지워지지 않도록 replace_existing=False.
        result = ingest_document(
            contents,
            saved_name,
            region_hint=(region_hint or "").strip(),
            replace_existing=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"문서 파싱에 실패했습니다: {exc}") from exc

    return DocumentIngestResult(
        document_name=result["document_name"],
        extracted=result["extracted"],
        risk_points_created=result["risk_points_created"],
        risk_points_skipped=int(result.get("risk_points_skipped") or 0),
        used_mock=result["used_mock"],
    )


@router.post("/confirm", response_model=DocumentPointConfirmResult)
def confirm_point(body: DocumentPointConfirmRequest) -> DocumentPointConfirmResult:
    try:
        result = confirm_document_point(
            location_text=body.location_text,
            geocode_query=body.geocode_query,
            risk_type=body.risk_type,
            is_risk=body.is_risk,
            snippet=body.snippet,
            source_doc=body.source_doc,
            page=body.page,
            report_date=body.report_date,
            recommendation=body.recommendation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"위치 확인에 실패했습니다: {exc}") from exc

    return DocumentPointConfirmResult(**result)


@router.get("/files/{filename}")
def get_document_file(filename: str) -> FileResponse:
    """업로드해 둔 원본 문서를 연다 (안전 리포트에서 클릭)."""
    path = _resolve_upload(filename)
    return FileResponse(path, filename=path.name)


@router.get("", response_model=list[DocumentRiskPoint])
def list_risk_points() -> list[DocumentRiskPoint]:
    db.init_db()
    rows = db.fetch_all("doc_risk_points")
    return [_to_risk_point(row) for row in rows]


@router.delete("")
def clear_risk_points() -> dict:
    """문서 재분석 전 기존 위험 표시와 업로드 원본을 지운다."""
    db.init_db()
    db.clear_table("doc_risk_points")
    _clear_uploads()
    return {"ok": True}
