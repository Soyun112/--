# 아키텍처 상세 (구현 참고용)

상위 개념은 [`PROJECT_PLAN.md`](../PROJECT_PLAN.md) 4장을 참고. 이 문서는 실제 코드
모듈과의 대응 관계를 정리한다.

## 모듈 맵

| 계층 | 파일 | 역할 |
| --- | --- | --- |
| API | `backend/app/main.py` | FastAPI 앱, 시작 시 공공데이터 적재 + MOCK 문서 선적재 |
| API | `backend/app/routers/route.py` | `POST /api/route`, `GET /api/public-data` |
| API | `backend/app/routers/documents.py` | `POST /api/documents/ingest`, `GET /api/documents` |
| 서비스 | `backend/app/services/routing.py` | Tmap 보행자 API 연동 + 경로 후보 생성(MOCK 포함) |
| 서비스 | `backend/app/services/public_data.py` | 공공데이터 수집/정제/SQLite 적재/조회 |
| 서비스 | `backend/app/services/geo.py` | Haversine, 리샘플링, 버퍼 매칭 |
| 서비스 | `backend/app/services/scoring.py` | 안전점수 산출(상대 정규화) |
| 서비스 | `backend/app/services/document_pipeline.py` | Document Parse + Information Extract + 지오코딩 |
| 서비스 | `backend/app/services/solar.py` | Solar LLM 프롬프트/호출(부모용·아이용) |
| 저장소 | `backend/app/db.py` | SQLite 스키마 및 CRUD 헬퍼 |
| 배치 | `backend/scripts/ingest_public_data.py` | 공공데이터 배치 수집 스크립트 |
| 배치 | `backend/scripts/ingest_sample_document.py` | 샘플 문서 파이프라인 실행 스크립트 |
| 프론트 | `frontend/app.js` | API 호출, Leaflet+OSM 실지도(오프라인 시 SVG 스키매틱) 렌더링, 결과 표시 |
| 테스트 | `backend/tests/` | geo/scoring 모듈 단위 테스트(pytest) |

## SQLite 스키마

- `child_zones(id, name, lat, lng, cctv_count, managing_org, police_office, source)`
- `accident_hotspots(id, spot_id, name, lat, lng, occurrence_count, casualty_count, fatality_count, source)`
- `crime_grid(id, grid_key, lat_center, lng_center, region_name, risk_index, source)`
- `guardian_houses(id, name, category, lat, lng, contact, source)` — 아동안전지킴이집
- `streetlights(id, facility_id, lat, lng, light_type, source)` — 보안등/가로등
- `speed_cameras(id, facility_id, name, lat, lng, speed_limit_kmh, source)` — 무인 교통단속카메라
- `doc_risk_points(id, lat, lng, risk_type, is_risk, snippet, source_doc, page, report_date, recommendation, created_at)`

## MOCK / LIVE 전환 규칙

`backend/app/config.py`의 `Settings`가 `.env`의 키 존재 여부로 아래를 자동 결정한다.

- `TMAP_APP_KEY` 없음 → `routing_mock=True` (경로는 직선/그리드 합성 경로 3종 생성)
- `DATA_GO_KR_SERVICE_KEY` 없음 → `public_data_mock=True` (`sample_*.json` 사용)
- `UPSTAGE_API_KEY` 없음 → `upstage_mock=True` (문서 추출은 `sample_documents/`,
  Solar 설명은 템플릿 기반 생성으로 대체)

세 플래그는 독립적으로 동작하므로, 예를 들어 Upstage 키만 먼저 발급받아도 나머지는
MOCK으로 유지한 채 실제 Document Parse/Solar 파이프라인만 시험할 수 있다.

`.env`의 `PUBLIC_DATA_MOCK`으로 `public_data_mock`을 명시적으로 강제할 수도 있다
(서비스키 존재 여부와 무관하게 우선 적용). 아동안전지킴이집/보안등/무인단속카메라
3종은 `data.go.kr`의 "표준데이터 개방 표준 API"로 실제 연동은 정상 동작하지만,
지역 필터 파라미터가 없는 전국 단위 데이터라 페이지네이션(`pageNo`)으로 받아오는
부분이 데모 좌표와 무관한 지역일 수 있다(예: 확인 결과 streetlights는 종로구,
guardian_houses는 여수 인근이 1페이지에 위치). 그래서 데모 발표 시에는
`PUBLIC_DATA_MOCK=true`로 고정해 데모 좌표에 맞는 샘플 데이터를 쓰는 것을 권장하며,
실서비스 전환 시에는 전국 데이터를 1회 전체 적재 후 SQLite에서 bbox로 조회하는
방식(로드맵)으로 바꿔야 한다.

## 실제 API 연동 시 확인/교체가 필요한 지점

- `public_data.py`의 `CHILD_ZONE_API_URL`, `ACCIDENT_HOTSPOT_API_URL` — 아직 미검증 상태이며
  data.go.kr 활용신청 승인 후 발급되는 정확한 Endpoint/파라미터 방식으로 교체 필요
  (`GUARDIAN_HOUSE_API_URL`/`STREETLIGHT_API_URL`/`SPEED_CAMERA_API_URL`은 실제 서비스키로
  검증 완료 — `tn_pubr_public_*_api` 방식, 응답은 `response.body.items`)
- 전국 단위 데이터를 데모 좌표 인근으로 좁혀 받는 지역 필터가 없으므로, 실서비스 전환 시
  전체 데이터를 1회 적재 후 SQLite bbox 조회로 바꾸는 작업 필요 (`PROJECT_PLAN.md` 로드맵)
- `document_pipeline.py`의 `geocode_location_text` — 현재는 수동 매핑 + Tmap POI 검색
  스텁이므로, 실제 서비스에서는 검증된 지오코딩 API로 교체 권장
- `routing.py`의 `_call_tmap` — 실제 Tmap 응답 필드명이 문서와 다를 경우 `total_distance`/
  `total_time` 파싱 로직 보정 필요
