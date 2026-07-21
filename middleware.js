import LZString from "lz-string";

const PRODUCTION_APP_URL = "https://kids-abcd.vercel.app";
const DEFAULT_TITLE = "👶 오늘의 안전 길";
const DEFAULT_DESCRIPTION = "링크를 누르면 길 안내 카드가 바로 열려요!";
const BACKEND = "https://kids-safe-route-api.onrender.com";

// 카카오 미리보기 수집기만 (인앱 브라우저 KAKAOTALK UA는 제외)
const PREVIEW_BOTS = /kakaotalk-scrap|facebookexternalhit|Twitterbot|Slackbot|Discordbot|WhatsApp|LinkedInBot|TelegramBot/i;

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function readEncoded(searchParams, pathname) {
  let encoded = searchParams.get("d");
  if (encoded) return encoded;

  const parts = [];
  for (let i = 0; ; i += 1) {
    const part = searchParams.get(`p${i}`);
    if (part === null) break;
    parts.push(part);
  }
  if (parts.length) return parts.join("");

  const match = pathname.match(/^\/g\/(.+)/i);
  if (match) return match[1].replace(/\//g, "");

  return null;
}

function decodeTitleFromEncoded(encoded) {
  if (!encoded) return null;
  try {
    let raw = encoded;
    try {
      raw = decodeURIComponent(encoded);
    } catch {
      /* keep raw */
    }
    const json = LZString.decompressFromEncodedURIComponent(raw);
    if (!json) return null;
    const data = JSON.parse(json);
    return data?.t || null;
  } catch {
    return null;
  }
}

function productionGuideUrl(url) {
  return `${PRODUCTION_APP_URL}${url.pathname}${url.search}`;
}

function previewHtml({ title, description, canonical }) {
  const safeTitle = escapeHtml(title);
  const safeDescription = escapeHtml(description);
  const safeCanonical = escapeHtml(canonical);
  return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta property="og:type" content="website">
<meta property="og:title" content="${safeTitle}">
<meta property="og:description" content="${safeDescription}">
<meta property="og:url" content="${safeCanonical}">
<title>${safeTitle}</title>
</head>
<body>
<p>${safeDescription}</p>
<p><a href="${safeCanonical}">${safeCanonical}</a></p>
</body>
</html>`;
}

export default async function middleware(request) {
  const url = new URL(request.url);
  const isGuidePath =
    url.pathname === "/guide" ||
    url.pathname.startsWith("/g/") ||
    url.pathname.endsWith("/kid-guide.html");
  if (!isGuidePath) return;

  const ua = request.headers.get("user-agent") || "";
  if (!PREVIEW_BOTS.test(ua)) return;

  let title = DEFAULT_TITLE;
  const description = DEFAULT_DESCRIPTION;
  const shareId = url.searchParams.get("id");

  if (shareId) {
    try {
      const res = await fetch(
        `${BACKEND}/api/share/kid-guide/${encodeURIComponent(shareId)}`
      );
      if (res.ok) {
        const data = await res.json();
        if (data?.title) title = `👶 ${data.title}`;
      }
    } catch {
      /* keep default */
    }
  } else {
    const encoded = readEncoded(url.searchParams, url.pathname);
    const decodedTitle = decodeTitleFromEncoded(encoded);
    if (decodedTitle) title = `👶 ${decodedTitle}`;
  }

  return new Response(previewHtml({ title, description, canonical: productionGuideUrl(url) }), {
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

export const config = {
  matcher: ["/guide", "/g/:path*", "/kid-guide.html"],
};
