# AI 어린이 안심 길찾기 서비스

공공데이터(어린이보호구역·CCTV·교통사고다발지역·아동안전지킴이집·보안등·무인단속카메라)와 지자체의 비정형 안전 문서(Upstage Document Parse + Information Extract로 구조화)를 결합해 경로 후보별 안전점수를 계산하고, Upstage Solar LLM이 부모용/아이용으로 각각 다르게 설명해주는 서비스입니다.

기획 배경과 루브릭 대응 상세는 [`PROJECT_PLAN.md`](PROJECT_PLAN.md)를 참고하세요.

## 폴더 구조

```
kids/
  PROJECT_PLAN.md        기획서 (루브릭 대응)
  backend/                FastAPI 백엔드 (경로/데이터/안전점수/Upstage 연동)
  frontend/               정적 웹 프론트엔드 (지도/마커/AI 설명 패널)
  docs/                   아키텍처, 발표자료 개요, 루브릭 매핑
```

## 빠른 시작 (백엔드)

```bash
cd backend
python -m venv .venv
. .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp ../.env.example ../.env  # 실제 키가 있으면 채워 넣기 (없어도 MOCK 데이터로 동작)
uvicorn app.main:app --reload --port 8000
```

API 키(`TMAP_APP_KEY`, `DATA_GO_KR_SERVICE_KEY`, `UPSTAGE_API_KEY`)가 `.env`에 없으면 서비스는 자동으로 **MOCK 모드**로 동작하며, `backend/app/data/`의 샘플 데이터로 전체 파이프라인(경로 생성 → 안전점수 → AI 리포트)을 오프라인으로 시연할 수 있습니다.

## 빠른 시작 (프론트엔드)

백엔드가 8000번 포트에서 실행 중이면 `frontend/index.html`을 브라우저로 바로 열면 됩니다(별도 빌드 불필요). 지도는 Leaflet + OpenStreetMap 타일로 렌더링되며(API 키/도메인 등록 불필요), 오프라인 등으로 타일 로드가 실패하면 좌표를 정규화한 SVG 스키매틱 지도로 자동 대체됩니다. `TMAP_APP_KEY`는 지도 표시가 아니라 백엔드의 실제 보행자 경로 계산(도로 폴리라인 생성)에만 사용됩니다.

## 핵심 API

- `POST /api/route` — 출발지/목적지 좌표를 받아 경로 후보, 안전점수, 부모용/아이용 AI 리포트를 반환
- `POST /api/documents/ingest` — 안전 문서(PDF 등)를 업로드해 Document Parse + Information Extract 파이프라인 실행
- `GET /api/documents` — 문서에서 추출된 위험/안전 포인트 목록
- `GET /api/config` — 프론트엔드용 공개 설정(Tmap 앱키 존재 여부 등)

## 데이터 출처

- 전국어린이보호구역표준데이터, 교통사고다발지역, 아동안전지킴이집, 보안등설치현황, 무인교통단속카메라 — data.go.kr (공공데이터포털)
- 범죄주의구간 — safemap.go.kr (행정안전부 생활안전지도)
- 도보 경로 — Tmap 보행자 길찾기 API (SK Open API)
- 지도 시각화 — Leaflet + OpenStreetMap (무료, API 키 불필요)
- 문서 파싱/추출/설명 — Upstage Document Parse, Information Extract, Solar LLM
