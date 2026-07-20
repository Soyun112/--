/** 아이용 길 안내 공유 payload ↔ URL 인코딩 (백엔드 없이도 동작) */
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
  try {
    const b64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
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
  return `${base}/g?d=${encodeURIComponent(encoded)}`;
}
