/** 아이용 길 안내 공유 — LZ 압축 + ?d= (카톡은 # 해시를 제거함) */
function ultraCompactPayload(payload) {
  return {
    t: payload.title || "",
    s: (payload.steps || []).map((step) => [
      step.keyword || "",
      step.friendly || "",
      step.landmark || "",
      step.is_arrive ? 1 : 0,
    ]),
  };
}

function expandKidGuidePayload(data) {
  if (!data) return null;
  if (Array.isArray(data.steps) && data.steps.length) return normalizeSteps(data);
  if (!Array.isArray(data.s) || !data.s.length) return null;
  return normalizeSteps({
    title: data.t || "오늘의 안전 길",
    steps: data.s.map(([keyword, friendly, landmark, is_arrive]) => ({
      keyword,
      friendly,
      landmark,
      is_arrive: !!is_arrive,
      icon: iconForKeyword(keyword, !!is_arrive),
    })),
  });
}

function normalizeSteps(data) {
  const steps = (data.steps || []).map((step) => ({
    ...step,
    icon: step.icon || iconForKeyword(step.keyword, step.is_arrive),
  }));
  return { ...data, steps };
}

function iconForKeyword(keyword, isArrive) {
  const k = keyword || "";
  if (isArrive || k.includes("도착")) return "🎉";
  if (k.includes("왼쪽")) return "↰";
  if (k.includes("오른쪽")) return "↱";
  if (k.includes("횡단") || k.includes("육교")) return "🚸";
  return "↑";
}

function encodeKidGuidePayload(payload) {
  const json = JSON.stringify(ultraCompactPayload(payload));
  if (typeof LZString !== "undefined") {
    return LZString.compressToEncodedURIComponent(json);
  }
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

  if (typeof LZString !== "undefined") {
    try {
      const json = LZString.decompressFromEncodedURIComponent(raw);
      if (json) return expandKidGuidePayload(JSON.parse(json));
    } catch {
      /* try base64 fallback */
    }
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

function readEncodedFromLocation() {
  const params = new URLSearchParams(window.location.search);
  let encoded = params.get("d");

  if (!encoded) {
    const parts = [];
    for (let i = 0; ; i += 1) {
      const part = params.get(`p${i}`);
      if (part === null) break;
      parts.push(part);
    }
    if (parts.length) encoded = parts.join("");
  }

  if (!encoded) {
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
    if (hash && !hash.startsWith("id=")) encoded = hash;
  }

  if (!encoded) {
    const match = window.location.pathname.match(/\/g\/(.+)/i);
    if (match) encoded = match[1].replace(/\//g, "");
  }

  return encoded;
}

function readInlineGuidePayload() {
  return decodeKidGuidePayload(readEncodedFromLocation());
}

function readShareIdFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const queryId = params.get("id");
  if (queryId) return queryId;

  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  if (hash.startsWith("id=")) return hash.slice(3);
  return null;
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

function buildKidGuideShareUrl(payload) {
  const encoded = encodeKidGuidePayload(payload);
  const base = resolveKidGuideFrontendBase();

  if (encoded.length <= 1200) {
    return `${base}/guide?d=${encoded}`;
  }

  const chunks = encoded.match(/.{1,400}/g) || [];
  const query = chunks.map((chunk, idx) => `p${idx}=${encodeURIComponent(chunk)}`).join("&");
  return `${base}/guide?${query}`;
}

function buildKidGuideShortUrl(id) {
  return `${resolveKidGuideFrontendBase()}/guide?id=${encodeURIComponent(id)}`;
}
