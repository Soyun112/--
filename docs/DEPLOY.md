# 배포 가이드 (Vercel + Render)

## 구조

- **Vercel** → `frontend/` (정적 웹) + `/api` → Render 프록시
- **Render** → `backend/` (FastAPI API, 인터넷 공개)
- **API 키** → Render 환경 변수만 (Git `.env` 업로드 ❌)

> ⚠️ Vercel만 배포하면 **화면만** 보입니다. 다른 사람도 쓰려면 **Render 백엔드**가 필수입니다.

---

## 1. Render (백엔드) — 먼저

1. https://render.com → GitHub 로그인
2. **New +** → **Web Service** → 레포 `Soyun112/-` 선택
3. 설정:

| 항목 | 값 |
|------|-----|
| Name | `kids-safe-route-api` |
| Root Directory | *(비움 — 저장소 루트)* |
| Build Command | `pip install -r backend/requirements.txt` |
| Start Command | `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

4. **Environment** → Render 대시보드에만 추가 (Git에 넣지 않음):

```
TMAP_APP_KEY=...
KAKAO_REST_API_KEY=...
NAVER_SEARCH_CLIENT_ID=...
NAVER_SEARCH_CLIENT_SECRET=...
UPSTAGE_API_KEY=...
DATA_GO_KR_SERVICE_KEY=...
PUBLIC_DATA_MOCK=true
```

5. **Create Web Service** → 배포 완료 후 URL 복사  
   예: `https://kids-safe-route-api.onrender.com`

6. 확인: `https://...onrender.com/api/health` → `{"status":"ok"}`

---

## 2. Vercel (프론트)

1. https://vercel.com → GitHub 로그인
2. 프로젝트 `abc` → **Settings → General**

| 항목 | 값 |
|------|-----|
| Root Directory | *(비움 — 저장소 루트)* |
| Framework Preset | Other |
| Build Command | `npm run build` |
| Output Directory | *(비움 — vercel.json이 `frontend` 지정)* |

3. **Settings → Environment Variables**:

| Name | Value |
|------|--------|
| `BACKEND_URL` | Render URL (예: `https://kids-safe-route-api.onrender.com`, 끝 `/` 없이) |

4. **Deployments → Redeploy**

빌드 시 `scripts/build-vercel.js`가 `vercel.json`에 `/api` → Render 프록시를 자동 설정합니다.  
브라우저는 `https://abc-xxx.vercel.app/api/...` 로 호출하고, Vercel이 Render로 전달합니다.

---

## 3. 로컬 개발 (변경 없음)

```powershell
# 터미널 1 — 백엔드
cd backend
python -m uvicorn app.main:app --reload --port 8000

# 터미널 2 — 프론트 (선택)
cd frontend
python -m http.server 5500
# 또는 frontend/index.html 을 브라우저로 직접 열기
```

로컬에서는 `127.0.0.1:8000`으로 자동 연결됩니다.

---

## 4. 이후 코드 수정 시

```powershell
git add .
git commit -m "설명"
git push
```

Vercel·Render 모두 자동 재배포됩니다.

---

## 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| Vercel에서 404 | Output Directory 잘못됨 | Root 비움, Build `npm run build`, Redeploy |
| 백엔드 연결 안됨 | `BACKEND_URL` 미설정 | Vercel Environment Variables 추가 후 Redeploy |
| Render 첫 요청 느림 | Free tier cold start | 30초 정도 기다린 후 재시도 |
| 경로 422 / 좌표 없음 | Render에 예전 코드 | Git push 후 Render 재배포 |
