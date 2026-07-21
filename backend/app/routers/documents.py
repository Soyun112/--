from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import db
from ..config import settings
from ..models import DocumentIngestResult, DocumentRiskPoint
from ..services.document_pipeline import ingest_document

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".hwp", ".hwpx", ".md", ".txt"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@router.post("/ingest", response_model=DocumentIngestResult)
async def ingest(file: UploadFile = File(...)) -> DocumentIngestResult:
    if not settings.document_ingest_enabled:
        raise HTTPException(status_code=403, detail="문서 업로드 API는 비활성화되어 있습니다.")
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

    try:
        result = ingest_document(contents, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"문서 파싱에 실패했습니다: {exc}") from exc

    return DocumentIngestResult(
        document_name=result["document_name"],
        extracted=result["extracted"],
        risk_points_created=result["risk_points_created"],
        used_mock=result["used_mock"],
    )


@router.get("", response_model=list[DocumentRiskPoint])
def list_risk_points() -> list[DocumentRiskPoint]:
    db.init_db()
    rows = db.fetch_all("doc_risk_points")
    return [
        DocumentRiskPoint(
            id=row["id"],
            lat=row["lat"],
            lng=row["lng"],
            risk_type=row["risk_type"],
            is_risk=bool(row["is_risk"]),
            snippet=row["snippet"],
            source_doc=row["source_doc"],
            page=row["page"],
            report_date=row["report_date"],
            recommendation=row["recommendation"],
        )
        for row in rows
    ]
