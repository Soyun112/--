# 배포 가이드 (Vercel + Render)

## 구조

- **Vercel** → `frontend/` (정적 웹)
- **Render** → `backend/` (FastAPI API)
- **API 키** → Render 환경 변수 (Git `.env` 업로드 ❌)

---

## 1. Render (백엔드) — 먼저

1. https://render.com → GitHub 로그인
2. **New +** → **Web Service** → 레포 `Soyun112/-` 선택
3. 설정:

| 항목 | 값 |
|------|-----|
| Name | `kids-safe-route-api` |
| Root Directory | *(비움)* |
| Build Command | `pip install -r backend/requirements.txt` |
| Start Command | `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

4. **Environment** → `.env` 내용 복사 (이름 그대로):

```
TMAP_APP_KEY
DATA_GO_KR_SERVICE_KEY
UPSTAGE_API_KEY
KAKAO_REST_API_KEY
NAVER_SEARCH_CLIENT_ID
NAVER_SEARCH_CLIENT_SECRET
PUBLIC_DATA_MOCK=true
```

5. **Create Web Service** → 배포 완료 후 URL 복사  
   예: `https://kids-safe-route-api.onrender.com`

6. 확인: `https://...onrender.com/api/health` → `{"status":"ok"}`

---

## 2. Vercel (프론트)

1. https://vercel.com → GitHub 로그인
2. **Add New → Project** → `Soyun112/-` Import
3. 설정:

| 항목 | 값 |
|------|-----|
| Framework Preset | Other |
| Root Directory | `frontend` |
| Build Command | `npm run build` |
| Output Directory | `.` |

4. **Environment Variables**:

| Name | Value |
|------|--------|
| `BACKEND_URL` | Render URL (예: `https://kids-safe-route-api.onrender.com`) |

5. **Deploy**

프론트는 `/api/*` 요청을 Render로 프록시합니다 (CORS 설정 불필요).

---

## 3. 이후 코드 수정 시

```powershell
git add .
git commit -m "설명"
git push
```

Vercel·Render 모두 자동 재배포됩니다.
