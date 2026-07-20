/** 아이용 길 안내 공유 — 서버 없이 # 해시 또는 /g/ 경로로 바로 열림 */
function compactKidGuidePayload(payload) {
  return {
    t: payload.title || "",
    s: (payload.steps || []).map((step) => [
      step.icon || "↑",
      step.keyword || "",
      step.friendly || "",
      step.landmark || "",
      step.is_arrive ? 1 : 0,
    ]),
  };
}

function expandKidGuidePayload(data) {
  if (!data) return null;
  if (Array.isArray(data.steps) && data.steps.length) return data;
  if (!Array.isArray(data.s) || !data.s.length) return null;
  return {
    title: data.t || "오늘의 안전 길",
    steps: data.s.map(([icon, keyword, friendly, landmark, is_arrive]) => ({
      icon,
      keyword,
      friendly,
      landmark,
      is_arrive: !!is_arrive,
    })),
  };
}

function encodeKidGuidePayload(payload) {
  const json = JSON.stringify(compactKidGuidePayload(payload));
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
    return expandKidGuidePayload(JSON.parse(new TextDecoder().decode(bytes)));
  } catch {
    return null;
  }
}

function readShareIdFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const queryId = params.get("id");
  if (queryId) return queryId;

  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  if (hash.startsWith("id=")) return hash.slice(3);
  return null;
}

function readInlineGuidePayload() {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  if (hash && !hash.startsWith("id=")) {
    const fromHash = decodeKidGuidePayload(hash);
    if (fromHash?.steps?.length) return fromHash;
  }

  const params = new URLSearchParams(window.location.search);
  let encoded = params.get("d");

  if (!encoded) {
    const parts = params.getAll("p");
    if (parts.length) encoded = parts.join("").replace(/\//g, "");
  }

  if (!encoded) {
    const match = window.location.pathname.match(/\/g\/(.+)/i);
    if (match) encoded = match[1].replace(/\//g, "");
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

/** 카톡·모바일: 짧은 /guide#데이터 (해시는 서버 안 거치고 바로 카드 표시) */
function buildKidGuideShareUrl(payload) {
  const encoded = encodeKidGuidePayload(payload);
  const base = resolveKidGuideFrontendBase();
  return `${base}/guide#${encoded}`;
}

function buildKidGuideShortUrl(id) {
  const base = resolveKidGuideFrontendBase();
  return `${base}/guide#id=${encodeURIComponent(id)}`;
}
