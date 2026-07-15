/**
 * Vercel 배포 시 BACKEND_URL 환경 변수로 vercel.json(프록시) 생성.
 * 로컬에서는 실행하지 않아도 됨.
 */
const fs = require("fs");
const path = require("path");

const backend = (process.env.BACKEND_URL || "").replace(/\/$/, "");
const dir = __dirname;

if (!backend) {
  console.warn("[build-vercel] BACKEND_URL 없음 — /api 프록시 없이 정적 파일만 배포");
  fs.writeFileSync(path.join(dir, "vercel.json"), JSON.stringify({ version: 2 }, null, 2));
} else {
  const vercel = {
    version: 2,
    rewrites: [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ],
  };
  fs.writeFileSync(path.join(dir, "vercel.json"), JSON.stringify(vercel, null, 2));
  console.log("[build-vercel] API 프록시 →", backend);
}
