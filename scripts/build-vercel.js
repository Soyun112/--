/**
 * Vercel 배포 시 BACKEND_URL 환경 변수로 /api → Render(또는 공개 백엔드) 프록시 설정.
 * 정적 파일(frontend/)은 그대로 두고 vercel.json만 생성한다.
 */
const fs = require("fs");
const path = require("path");

const backend = (process.env.BACKEND_URL || "").replace(/\/$/, "");
const root = path.join(__dirname, "..");

const config = {
  version: 2,
  outputDirectory: "frontend",
};

if (backend) {
  config.rewrites = [
    {
      source: "/api/:path*",
      destination: `${backend}/api/:path*`,
    },
  ];
  console.log("[build-vercel] API 프록시 →", backend);
} else {
  console.warn(
    "[build-vercel] BACKEND_URL 없음 — Vercel에서 /api 호출이 실패합니다. " +
      "Render 배포 후 Vercel Environment Variables에 BACKEND_URL을 추가하세요."
  );
}

fs.writeFileSync(path.join(root, "vercel.json"), JSON.stringify(config, null, 2) + "\n");
