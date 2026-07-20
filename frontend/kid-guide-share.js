/** 아이용 길 안내 공유 payload ↔ URL 인코딩 */
function encodeKidGuidePayload(payload) {
  const json = JSON.stringify(payload);
  const bytes = new TextEncoder().encode(json);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodeKidGuidePayload(encoded) {
  if (!encoded) return null;
  let raw = String(encoded).trim();
  try {
    raw = decodeURIComponent(raw);
  } catch {
    /* keep */
  }
  raw = raw.replace(/ /g, "+");
  try {
    const b64 = raw.replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
}

function readInlineGuidePayload() {
  const params = new URLSearchParams(window.location.search);
  let encoded = params.get("d");
  if (!encoded) {
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
    if (hash.startsWith("d=")) encoded = hash.slice(2);
    else if (hash && !hash.includes("=")) encoded = hash;
  }
  if (!encoded) {
    const match = window.location.pathname.match(/\/g\/([^/]+)/i);
    if (match) encoded = match[1];
  }
  return decodeKidGuidePayload(encoded);
}

function resolveKidGuideFrontendBase() {
  if (typeof resolveFrontendUrl === "function") {
    return resolveFrontendUrl();
  }
  const host = window.location.hostname.toLowerCase();
  if (host.endsWith(".onrender.com")) {
    return "https://kids-abcd.vercel.app";
  }
  if (window.location.protocol === "file:") {
    return "http://127.0.0.1:5500";
  }
  return window.location.origin;
}

function buildKidGuideInlineUrl(payload) {
  const encoded = encodeKidGuidePayload(payload);
  const base = resolveKidGuideFrontendBase();
  // 카톡 등에서 ?query 가 잘리는 경우가 있어 경로(/g/...) 방식 사용
  return `${base}/g/${encoded}`;
}

function buildKidGuideShortUrl(id) {
  const base = resolveKidGuideFrontendBase();
  return `${base}/guide?id=${encodeURIComponent(id)}`;
}

function resolveShareApiBase() {
  if (typeof API_BASE !== "undefined") return API_BASE;
  const host = window.location.hostname;
  const isLocal =
    !host ||
    host === "localhost" ||
    host === "127.0.0.1" ||
    window.location.protocol === "file:";
  if (!isLocal || window.location.port === "8000") return "";
  return "http://127.0.0.1:8000";
}

async function createKidGuideShareLink(payload) {
  const res = await fetch(`${resolveShareApiBase()}/api/share/kid-guide`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`share_create_failed_${res.status}`);
  }
  const data = await res.json();
  return buildKidGuideShortUrl(data.id);
}
