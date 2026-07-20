/** 아이용 길 안내 공유 — 서버 없이 /g/ 경로 링크로 바로 열림 (카톡·모바일용) */
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

function readInlineGuidePayload() {
  const params = new URLSearchParams(window.location.search);
  let encoded = params.get("d");

  if (!encoded) {
    const parts = params.getAll("p");
    if (parts.length) encoded = parts.join("");
  }

  if (!encoded) {
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
    if (hash.startsWith("d=")) encoded = hash.slice(2);
    else if (hash && !hash.includes("=")) encoded = hash;
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

function buildKidGuideInlineUrl(payload) {
  const encoded = encodeKidGuidePayload(payload);
  const base = resolveKidGuideFrontendBase();

  // 카톡에서 ?query 가 잘리므로 경로(/g/...) 방식. 너무 길면 경로를 여러 조각으로.
  if (encoded.length <= 720) {
    return `${base}/g/${encoded}`;
  }

  const chunks = encoded.match(/.{1,360}/g) || [];
  return `${base}/g/${chunks.join("/")}`;
}

function buildKidGuideShareUrl(payload) {
  return buildKidGuideInlineUrl(payload);
}
