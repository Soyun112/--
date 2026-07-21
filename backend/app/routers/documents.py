from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .. import db
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


def _to_risk_point(row) -> DocumentRiskPoint:
    return DocumentRiskPoint(
        id=row["id"],
        lat=row["lat"],
        lng=row["lng"],
        risk_type=row["risk_type"] or "",
        is_risk=bool(row["is_risk"]),
        snippet=row["snippet"] or "",
        source_doc=row["source_doc"] or "",
        page=row["page"],
        report_date=row["report_date"],
        recommendation=row["recommendation"],
        is_estimated=bool(row["is_estimated"]) if "is_estimated" in row.keys() else False,
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

    try:
        result = ingest_document(contents, file.filename, region_hint=(region_hint or "").strip())
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


@router.get("", response_model=list[DocumentRiskPoint])
def list_risk_points() -> list[DocumentRiskPoint]:
    db.init_db()
    rows = db.fetch_all("doc_risk_points")
    return [_to_risk_point(row) for row in rows]
