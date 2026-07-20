from __future__ import annotations

import sys

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .routers import auth, documents, route
from .services import public_data

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

app = FastAPI(
    title="AI 어린이 안심 길찾기 서비스",
    description="공공데이터 + Upstage Document Parse/Information Extract + Solar LLM 기반 어린이 안심 통학로 추천 API",
    version="0.1.0",
    docs_url="/docs" if settings.enable_openapi_docs else None,
    redoc_url="/redoc" if settings.enable_openapi_docs else None,
    openapi_url="/openapi.json" if settings.enable_openapi_docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://([a-z0-9-]+\.)*vercel\.app",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(route.router)
app.include_router(documents.router)


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    public_data.ingest_all()

    from .services import routing as routing_mod

    key = settings.tmap_app_key
    if key:
        masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"
        key_status = f"설정됨 ({masked}, {len(key)}자)"
    else:
        key_status = "없음 — MOCK 경로 모드로 동작"
    routing_mode = "MOCK" if settings.routing_mock else "LIVE (Tmap 보행자 API)"
    print(f"[설정] TMAP_APP_KEY: {key_status}")
    print(f"[설정] 경로 모드: {routing_mode}")
    print(f"[설정] routing.py: {routing_mod.__file__}")

    from .services.safety_facilities import get_safety_facilities

    sf = get_safety_facilities()
    if sf:
        by_type: dict[str, int] = {}
        for f in sf:
            by_type[f["facility_type"]] = by_type.get(f["facility_type"], 0) + 1
        print(
            f"[안심귀갓길] CSV 로드 완료 - 총 {len(sf)}건 "
            f"(CCTV {by_type.get('cctv', 0)} / 보안등 {by_type.get('streetlight', 0)} / "
            f"안심벨 {by_type.get('safety_bell', 0)} / 112 {by_type.get('emergency112', 0)})"
        )
    else:
        print("[안심귀갓길] CSV를 찾지 못했습니다. kids/data/ 또는 backend/app/data/ 를 확인하세요.")

    # MOCK 모드에서는 데모용 샘플 안전진단 문서를 자동으로 1건 선적재해
    # /api/route 호출 시 문서기반 근거(grounding)가 바로 반영되도록 한다.
    if settings.upstage_mock and not public_data.get_doc_risk_points():
        from .services.document_pipeline import ingest_document

        sample_path = settings.data_dir / "sample_documents" / "sample_report.md"
        ingest_document(sample_path.read_bytes(), "OO구_2024_통학로_안전진단_보고서(SAMPLE).pdf")


@app.get("/api/config")
def get_public_config() -> dict:
    return {
        "demo_center": {"lat": settings.demo_center_lat, "lng": settings.demo_center_lng},
        "tmap_web_key": settings.tmap_app_key,
        "mock": {
            "routing": settings.routing_mock,
            "public_data": settings.public_data_mock,
            "upstage": settings.upstage_mock,
        },
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "api_version": "2026-07-20-tmap"}


@app.get("/api/tmap-bootstrap.js")
def tmap_bootstrap_js():
    """head에서 동기 로드되어 document.write 로 Tmap jsv2 로더를 주입한다.

    주의: jsv2 응답은 실제 SDK가 아니라 document.write 로 tmapjs2.min.js 를
    불러오는 스텁이다. async createElement 로 넣으면 write 가 실패해
    LatLng/Map 생성자가 영원히 안 생긴다.
    """
    from fastapi.responses import Response

    key = settings.tmap_app_key.replace("\\", "\\\\").replace("'", "\\'")
    body = (
        "(function(){\n"
        f"  var key = '{key}';\n"
        "  window.__TMAP_APP_KEY__ = key;\n"
        "  if (!key) { window.__TMAP_BOOT_ERROR__ = 'TMAP_APP_KEY empty'; return; }\n"
        "  if (document.querySelector('script[data-tmap-sdk=\"1\"]')) return;\n"
        "  // 파싱 중(동기)일 때만 document.write 가 동작한다\n"
        "  document.write(\"<script data-tmap-sdk='1' src='https://apis.openapi.sk.com/tmap/jsv2?version=1&appKey=\" + encodeURIComponent(key) + \"'><\\/script>\");\n"
        "})();\n"
    )
    return Response(content=body, media_type="application/javascript; charset=utf-8")


# API 라우트 등록 이후에 정적 프론트를 마운트해야 /api 가 가려지지 않는다.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
