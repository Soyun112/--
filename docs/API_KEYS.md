# 사용 API / 키 정리

Git에서 받은 뒤 `.env.example` → `.env` 로 이름을 바꾸고, 아래 키만 채우면 됩니다.
키가 비어 있으면 해당 구간은 **MOCK(샘플 데이터)** 으로 동작합니다.

## 환경변수 ↔ API

| # | 환경변수 | 제공사 | 발급처 | 이 프로젝트에서의 역할 |
|---|----------|--------|--------|------------------------|
| 1 | `TMAP_APP_KEY` | SK Tmap | https://openapi.sk.com | 보행자 경로, POI·주소 지오코딩 (동일 appKey) |
| 2 | `DATA_GO_KR_SERVICE_KEY` | 공공데이터포털 | https://www.data.go.kr | 어린이보호구역, 사고다발지역, 안심지킴이집, 보안등, 단속카메라 |
| 3 | `UPSTAGE_API_KEY` | Upstage | https://console.upstage.ai | Document Parse, Information Extract, Solar LLM |
| 4 | `KAKAO_REST_API_KEY` | 카카오 | https://developers.kakao.com | 건물·상호·역 지오코딩 |
| 5 | `NAVER_SEARCH_CLIENT_ID` / `NAVER_SEARCH_CLIENT_SECRET` | 네이버 | https://developers.naver.com | 지역 검색(지오코딩·랜드마크) |
| 6 | `KMA_SERVICE_KEY` (선택) | 기상청 | data.go.kr | 초단기실황(비우면 2번 키 재사용) |

## 실제 호출하는 외부 엔드포인트 (13개)

### Tmap (3) — **appKey 하나로 모두 사용**
- `POST https://apis.openapi.sk.com/tmap/routes/pedestrian` — 보행자 길찾기
- `GET https://apis.openapi.sk.com/tmap/pois` — POI 검색 (건물명·학원)
- `GET https://apis.openapi.sk.com/tmap/geo/fullAddrGeo` — 주소 → 좌표

### Upstage (3)
- `POST https://api.upstage.ai/v1/document-digitization` — Document Parse
- `POST https://api.upstage.ai/v1/information-extraction` — Information Extract
- `POST https://api.upstage.ai/v1/chat/completions` — Solar LLM

### 카카오 (1)
- `GET https://dapi.kakao.com/v2/local/search/keyword.json` — 키워드 지오코딩

### 네이버 (1)
- `GET https://openapi.naver.com/v1/search/local.json` — 지역 검색

### 공공데이터포털 (5)
- 어린이보호구역 (odcloud)
- 교통사고다발지역
- 전국안심지킴이집표준데이터
- 전국보안등정보표준데이터
- 전국무인교통단속카메라표준데이터

### 기상청 (1)
- `GET .../VilageFcstInfoService_2.0/getUltraSrtNcst` — 초단기실황

## API 키 없이 쓰는 것
- **Leaflet + OpenStreetMap** — 지도 타일 (키 불필요)
- **safemap 범죄주의구간** — 현재 샘플 JSON (실 API 미연동)

## 자체 백엔드 API (이 서비스가 제공하는 것)
- `GET /api/health`
- `GET /api/config`
- `GET /api/geocode`
- `GET /api/public-data`
- `POST /api/route`
- `POST /api/documents/ingest`
- `GET /api/documents`
