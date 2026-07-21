"""중앙 설정. .env가 없거나 키가 비어 있으면 자동으로 MOCK 모드로 동작해
API 키 없이도 전체 파이프라인을 오프라인으로 시연할 수 있게 한다."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

# Render/배포 환경 변수가 .env 빈 값으로 덮이지 않도록 override=False
load_dotenv(REPO_ROOT / ".env", override=False)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    tmap_app_key: str = os.getenv("TMAP_APP_KEY", "").strip()
    data_go_kr_service_key: str = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
    upstage_api_key: str = os.getenv("UPSTAGE_API_KEY", "").strip()

    # 건물명/역이름 -> 좌표 지오코딩용 키 (없으면 Tmap POI + 내장 사전으로 폴백)
    kakao_rest_api_key: str = os.getenv("KAKAO_REST_API_KEY", "").strip()
    naver_search_client_id: str = os.getenv("NAVER_SEARCH_CLIENT_ID", "").strip()
    naver_search_client_secret: str = os.getenv("NAVER_SEARCH_CLIENT_SECRET", "").strip()

    # 기상청 초단기실황 키 (없으면 data.go.kr 서비스키를 재사용 — 동일 포털 계정 키)
    kma_service_key: str = os.getenv("KMA_SERVICE_KEY", "").strip() or data_go_kr_service_key

    demo_center_lat: float = float(os.getenv("DEMO_CENTER_LAT", "37.5013"))
    demo_center_lng: float = float(os.getenv("DEMO_CENTER_LNG", "127.0396"))

    database_path: Path = Path(os.getenv("DATABASE_PATH", str(BACKEND_DIR / "app" / "data" / "safety.db")))
    data_dir: Path = BACKEND_DIR / "app" / "data"
    repo_data_dir: Path = REPO_ROOT / "data"
    uploads_dir: Path = data_dir / "uploads"

    # 개별 키가 없으면 해당 구간만 MOCK으로 동작한다. MOCK_MODE로 전체를 강제할 수도 있다.
    force_mock: bool = _bool_env("MOCK_MODE", False)

    # 보안: 기본값은 디버그 로그·문서 업로드·OpenAPI 문서 비활성
    tmap_debug_logging: bool = _bool_env("TMAP_DEBUG_LOGGING", False)
    # Tmap 보행자 searchOption: 0=추천, 4=추천+대로우선, 10=최단, 30=최단+계단제외
    tmap_pedestrian_search_option: str = os.getenv("TMAP_PEDESTRIAN_SEARCH_OPTION", "4").strip() or "4"
    # 긴 직선 구간 재탐색은 API 호출이 많아 기본 off (Road API로 보강)
    tmap_route_densify_enabled: bool = _bool_env("TMAP_ROUTE_DENSIFY_ENABLED", False)
    tmap_route_densify_min_leg_m: float = float(os.getenv("TMAP_ROUTE_DENSIFY_MIN_LEG_M", "25"))
    # Tmap Free 티어 일일 한도 (SK Open API 기준)
    tmap_daily_limit_route: int = int(os.getenv("TMAP_DAILY_LIMIT_ROUTE", "1000"))
    tmap_daily_limit_road: int = int(os.getenv("TMAP_DAILY_LIMIT_ROAD", "1000"))
    tmap_daily_limit_poi: int = int(os.getenv("TMAP_DAILY_LIMIT_POI", "20000"))
    tmap_daily_limit_geocode: int = int(os.getenv("TMAP_DAILY_LIMIT_GEOCODE", "20000"))
    tmap_daily_reserve_route: int = int(os.getenv("TMAP_DAILY_RESERVE_ROUTE", "20"))
    tmap_daily_reserve_road: int = int(os.getenv("TMAP_DAILY_RESERVE_ROAD", "20"))
    tmap_cache_ttl_route_s: int = int(os.getenv("TMAP_CACHE_TTL_ROUTE_S", "21600"))  # 6h
    tmap_cache_ttl_geocode_s: int = int(os.getenv("TMAP_CACHE_TTL_GEOCODE_S", "86400"))  # 24h
    # Road API는 좌표가 적을 때만 (1회/검색). 기본 30개 미만일 때만 호출
    tmap_road_match_min_coords: int = int(os.getenv("TMAP_ROAD_MATCH_MIN_COORDS", "30"))
    tmap_road_match_enabled: bool = _bool_env("TMAP_ROAD_MATCH_ENABLED", True)
    # 대안 보행 경로(추가 API 1회) — 한도 절약을 위해 기본 off
    tmap_pedestrian_alt_enabled: bool = _bool_env("TMAP_PEDESTRIAN_ALT_ENABLED", False)
    document_ingest_enabled: bool = _bool_env("DOCUMENT_INGEST_ENABLED", True)
    enable_openapi_docs: bool = _bool_env("ENABLE_OPENAPI_DOCS", False)

    # Google OAuth (Render 환경 변수 / 로컬 .env) — 실행 시점에 읽음
    jwt_expire_hours: int = int(os.getenv("JWT_EXPIRE_HOURS", "168"))
    default_frontend_url: str = os.getenv(
        "FRONTEND_URL", "https://kids-abcd.vercel.app"
    ).strip().rstrip("/")

    @property
    def google_client_id(self) -> str:
        return os.getenv("GOOGLE_CLIENT_ID", "").strip()

    @property
    def google_client_secret(self) -> str:
        return os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

    @property
    def google_redirect_uri(self) -> str:
        return os.getenv("GOOGLE_REDIRECT_URI", "").strip()

    @property
    def jwt_secret(self) -> str:
        return os.getenv("JWT_SECRET", "").strip()

    @property
    def auth_enabled(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_redirect_uri
            and self.jwt_secret
        )

    @property
    def auth_config_status(self) -> dict[str, bool]:
        return {
            "GOOGLE_CLIENT_ID": bool(self.google_client_id),
            "GOOGLE_CLIENT_SECRET": bool(self.google_client_secret),
            "GOOGLE_REDIRECT_URI": bool(self.google_redirect_uri),
            "JWT_SECRET": bool(self.jwt_secret),
        }

    @property
    def allowed_frontend_origins(self) -> list[str]:
        raw = os.getenv("ALLOWED_FRONTEND_ORIGINS", "").strip()
        defaults = [
            self.default_frontend_url,
            "http://localhost:5500",
            "http://127.0.0.1:5500",
        ]
        if not raw:
            return list(dict.fromkeys(defaults))
        extra = [part.strip().rstrip("/") for part in raw.split(",") if part.strip()]
        return list(dict.fromkeys(defaults + extra))

    def is_allowed_frontend_url(self, url: str) -> bool:
        normalized = url.rstrip("/")
        if normalized in self.allowed_frontend_origins:
            return True
        # Vercel preview/production 배포 URL 허용
        from urllib.parse import urlparse

        host = urlparse(normalized).netloc.lower()
        return host.endswith(".vercel.app")

    @property
    def cors_origins(self) -> list[str]:
        raw = os.getenv("CORS_ORIGINS", "").strip()
        defaults = [
            "http://127.0.0.1:5500",
            "http://localhost:5500",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "https://kids-abcd.vercel.app",
            "null",
        ]
        defaults.extend(self.allowed_frontend_origins)
        if not raw:
            return list(dict.fromkeys(defaults))
        extra = [part.strip() for part in raw.split(",") if part.strip()]
        return list(dict.fromkeys(defaults + extra))

    @property
    def routing_mock(self) -> bool:
        return self.force_mock or not self.tmap_app_key

    @property
    def public_data_mock(self) -> bool:
        if self.force_mock:
            return True
        # 아동안전지킴이집/보안등/무인단속카메라는 지역 필터가 없는 전국 단위 표준데이터라
        # 서비스키가 있어도 페이지네이션으로 받아오는 부분이 데모 좌표와 무관한 지역일 수
        # 있다. PUBLIC_DATA_MOCK으로 명시적으로 강제 지정 가능(.env 참고). 지정이 없으면
        # 기존과 동일하게 서비스키 존재 여부로 자동 판단한다.
        return _bool_env("PUBLIC_DATA_MOCK", not self.data_go_kr_service_key)

    @property
    def upstage_mock(self) -> bool:
        return self.force_mock or not self.upstage_api_key

    # 안전점수 가중치 (PROJECT_PLAN.md 5장 수식과 대응)
    weights = {
        "cctv_density": 18.0,
        "child_zone_coverage": 15.0,
        "doc_safety": 10.0,
        "guardian_house": 10.0,
        "streetlight_density": 8.0,
        "speed_camera": 6.0,
        "accident_hotspot": 22.0,
        "crime_risk": 12.0,
        "doc_risk": 15.0,
        # 안심귀갓길 CSV 시설물 (CCTV·보안등 가점 크게)
        "safety_facility_cctv": 22.0,
        "safety_facility_streetlight": 14.0,
        "safety_bell": 6.0,
        "emergency112": 5.0,
    }

    buffer_radius_m: float = 40.0
    # 안심귀갓길 시설물 매칭 반경 (30~50m 권장, 기본 40m)
    safety_facility_buffer_m: float = float(os.getenv("SAFETY_FACILITY_BUFFER_M", "40"))
    resample_interval_m: float = 20.0


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
