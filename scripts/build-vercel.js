/**
 * Vercel 배포 시 BACKEND_URL 환경 변수로 /api → Render(또는 공개 백엔드) 프록시 설정.
 * 정적 파일(frontend/)은 그대로 두고 vercel.json만 생성한다.
 */
const fs = require("fs");
const path = require("path");

// Vercel Environment Variables의 BACKEND_URL 사용.
// 비어 있으면 이 프로젝트 기본 Render URL로 폴백 (연결 누락 방지).
const DEFAULT_BACKEND = "https://kids-safe-route-api.onrender.com";
const backend = (process.env.BACKEND_URL || DEFAULT_BACKEND).replace(/\/$/, "");
const root = path.join(__dirname, "..");

const config = {
  version: 2,
  outputDirectory: "frontend",
  rewrites: [
    {
      source: "/api/:path*",
      destination: `${backend}/api/:path*`,
    },
  ],
};

if (process.env.BACKEND_URL) {
  console.log("[build-vercel] API 프록시 →", backend, "(BACKEND_URL)");
} else {
  console.log(
    "[build-vercel] API 프록시 →",
    backend,
    "(기본값 — Vercel에 BACKEND_URL을 넣으면 그 주소로 바뀝니다)"
  );
}

fs.writeFileSync(path.join(root, "vercel.json"), JSON.stringify(config, null, 2) + "\n");
