import LZString from "lz-string";

const PRODUCTION_APP_URL = "https://kids-abcd.vercel.app";
const DEFAULT_TITLE = "👶 오늘의 안전 길";
const DEFAULT_DESCRIPTION = "링크를 누르면 길 안내 카드가 바로 열려요!";
const OG_IMAGE = `${PRODUCTION_APP_URL}/og-guide.png`;
const BACKEND = (
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "https://kids-safe-route-api.onrender.com"
).replace(/\/$/, "");

// 카카오 미리보기 수집기만 (인앱 브라우저 KAKAOTALK UA는 제외)
const PREVIEW_BOTS =
  /kakaotalk-scrap|facebookexternalhit|Twitterbot|Slackbot|Discordbot|WhatsApp|LinkedInBot|TelegramBot/i;

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

  // 예전 긴 /g/{encoded} 만 (짧은 ID는 별도 처리)
  const match = pathname.match(/^\/g\/(.+)/i);
  if (match && match[1].length > 16) return match[1].replace(/\//g, "");

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

function readShareId(url) {
  const fromQuery = url.searchParams.get("id");
  if (fromQuery) return fromQuery.trim();

  const guide = url.pathname.match(/^\/guide\/([a-z0-9_-]{4,16})$/i);
  if (guide) return guide[1];

  const gShort = url.pathname.match(/^\/g\/([a-z0-9_-]{4,16})$/i);
  if (gShort) return gShort[1];

  return null;
}

function productionGuideUrl(url) {
  return `${PRODUCTION_APP_URL}${url.pathname}${url.search}`;
}

function previewHtml({ title, description, canonical, image }) {
  const safeTitle = escapeHtml(title);
  const safeDescription = escapeHtml(description);
  const safeCanonical = escapeHtml(canonical);
  const safeImage = escapeHtml(image);
  return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:type" content="website">
<meta property="og:title" content="${safeTitle}">
<meta property="og:description" content="${safeDescription}">
<meta property="og:url" content="${safeCanonical}">
<meta property="og:image" content="${safeImage}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${safeTitle}">
<meta name="twitter:description" content="${safeDescription}">
<meta name="twitter:image" content="${safeImage}">
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
    url.pathname.startsWith("/guide/") ||
    url.pathname.startsWith("/g/") ||
    url.pathname.endsWith("/kid-guide.html");
  if (!isGuidePath) return;

  const ua = request.headers.get("user-agent") || "";
  if (!PREVIEW_BOTS.test(ua)) return;

  let title = DEFAULT_TITLE;
  const description = DEFAULT_DESCRIPTION;
  const shareId = readShareId(url);

  if (shareId) {
    try {
      const endpoints = [
        `${BACKEND}/api/share/kid-guide/${encodeURIComponent(shareId)}`,
        `${BACKEND}/api/share/${encodeURIComponent(shareId)}`,
      ];
      for (const endpoint of endpoints) {
        const res = await fetch(endpoint, {
          headers: { Accept: "application/json" },
        });
        if (!res.ok) continue;
        const data = await res.json();
        const routeTitle =
          data?.title ||
          (data?.origin && data?.destination
            ? `${data.origin} → ${data.destination}`
            : "");
        if (routeTitle) {
          title = `👶 ${routeTitle}`;
          break;
        }
      }
    } catch {
      /* keep default */
    }
  } else {
    const encoded = readEncoded(url.searchParams, url.pathname);
    const decodedTitle = decodeTitleFromEncoded(encoded);
    if (decodedTitle) title = `👶 ${decodedTitle}`;
  }

  return new Response(
    previewHtml({
      title,
      description,
      canonical: productionGuideUrl(url),
      image: OG_IMAGE,
    }),
    {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "public, max-age=300",
      },
    }
  );
}

export const config = {
  matcher: ["/guide", "/guide/:path*", "/g", "/g/:path*", "/kid-guide.html"],
};
