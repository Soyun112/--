# AI 어린이 안심 길찾기 서비스

공공데이터(어린이보호구역·CCTV·교통사고다발지역·아동안전지킴이집·보안등·무인단속카메라)와 지자체의 비정형 안전 문서(Upstage Document Parse + Information Extract로 구조화)를 결합해 경로 후보별 안전점수를 계산하고, Upstage Solar LLM이 부모용/아이용으로 각각 다르게 설명해주는 서비스입니다.

기획 배경과 루브릭 대응 상세는 [`PROJECT_PLAN.md`](PROJECT_PLAN.md)를 참고하세요.

## 폴더 구조

```
kids/
  .env.example            API 키 입력 템플릿 (복사 후 .env 로 이름 변경)
  run.bat                 Windows: 더블클릭으로 서버+화면 실행
  PROJECT_PLAN.md         기획서 (루브릭 대응)
  backend/                FastAPI 백엔드 (경로/데이터/안전점수/Upstage 연동)
  frontend/               정적 웹 프론트엔드 (지도/마커/AI 설명 패널)
  docs/                   아키텍처, API 키 목록, 발표자료 개요
```

## 빠른 시작 (Windows — 권장)

1. `.env.example` 을 복사해 이름을 **`.env`** 로 바꿉니다. (`example`만 지우면 됨)
2. `.env` 를 열어 **[API 키]** 칸만 채웁니다. (비워 두면 MOCK으로 동작)
3. **`run.bat`** 을 더블클릭합니다. → 가상환경/패키지 준비 후 서버 실행 + 브라우저 오픈

종료: `run.bat` 으로 열린 검은 창을 닫으면 됩니다.

API 키·엔드포인트 목록은 [`docs/API_KEYS.md`](docs/API_KEYS.md) 참고.

## 빠른 시작 (수동 / macOS·Linux)

```bash
cp .env.example .env   # 키 입력 (없어도 MOCK 동작)
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

브라우저에서 `frontend/index.html`을 엽니다. 지도는 Leaflet + OpenStreetMap(키 불필요)입니다.

## 핵심 API

- `POST /api/route` — 출발지/목적지 좌표를 받아 경로 후보, 안전점수, 부모용/아이용 AI 리포트를 반환
- `POST /api/documents/ingest` — 안전 문서(PDF 등)를 업로드해 Document Parse + Information Extract 파이프라인 실행
- `GET /api/documents` — 문서에서 추출된 위험/안전 포인트 목록
- `GET /api/config` — 프론트엔드용 공개 설정(MOCK/LIVE 상태, 데모 좌표 등. API 키는 포함하지 않음)

## 데이터 출처

- 전국어린이보호구역표준데이터, 교통사고다발지역, 아동안전지킴이집, 보안등설치현황, 무인교통단속카메라 — data.go.kr (공공데이터포털)
- 범죄주의구간 — safemap.go.kr (행정안전부 생활안전지도)
- 도보 경로 — Tmap 보행자 길찾기 API (SK Open API)
- 지도 시각화 — Leaflet + OpenStreetMap (무료, API 키 불필요)
- 문서 파싱/추출/설명 — Upstage Document Parse, Information Extract, Solar LLM
