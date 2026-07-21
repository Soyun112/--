/** 아이용 길 안내 공유 — LZ 압축 + ?d= (카톡은 # 해시를 제거함) */
function compactFriendly(value) {
  return (value || "").replace(/^👣\s*/, "");
}

function compactLandmark(value) {
  return (value || "").replace(/^📍\s*/, "").replace(/\s*쪽으로$/, "").trim();
}

function expandFriendly(value) {
  if (!value) return "";
  return value.startsWith("👣") ? value : `👣 ${value}`;
}

function expandLandmark(value) {
  if (!value) return "";
  if (value.startsWith("📍")) return value;
  return `📍 ${value} 쪽으로`;
}

function ultraCompactPayload(payload) {
  return {
    t: payload.title || "",
    s: (payload.steps || []).map((step) => [
      step.keyword || "",
      compactFriendly(step.friendly || ""),
      compactLandmark(step.landmark || ""),
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
    steps: data.s.map((row) => {
      const keyword = row[0] || "";
      const friendly = expandFriendly(row[1] || "");
      const landmark = expandLandmark(row[2] || "");
      const isArrive = !!row[3];
      return {
        keyword,
        friendly,
        landmark,
        is_arrive: isArrive,
        tip: tipForShareStep({ keyword, friendly, landmark, is_arrive: isArrive }),
        icon: iconForKeyword(keyword, isArrive),
      };
    }),
  });
}

function normalizeSteps(data) {
  const steps = (data.steps || []).map((step) => ({
    ...step,
    tip: step.tip || tipForShareStep(step),
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

function tipForShareStep(step) {
  if (!step || step.is_arrive) return "";
  if (step.tip) return step.tip;
  const stepCount = step.distance_m
    ? Math.max(1, Math.round(step.distance_m / 0.5))
    : parseStepCountFromFriendly(step.friendly);
  return buildKidSafetyTip({
    keyword: step.keyword || "",
    landmarkLabel: step.landmark || "",
    stepCount,
  });
}

function parseLandmarkLabel(landmark) {
  return (landmark || "").replace(/^📍\s*/, "").replace(/\s*쪽으로$/, "").trim();
}

function parseStepCountFromFriendly(friendly) {
  const match = (friendly || "").match(/(\d+)걸음/);
  return match ? parseInt(match[1], 10) : 0;
}

function buildKidSafetyTip({ keyword, landmarkLabel, stepCount, description, turn_type }) {
  const k = keyword || "";
  const place = parseLandmarkLabel(landmarkLabel);
  const desc = description || "";
  const tt = turn_type;

  if (k.includes("도착")) return "";

  if (k.includes("왼쪽")) {
    if (place) return `${place} 지나서 천천히 왼쪽으로, 나오는 차 조심해요`;
    return "모퉁이에서 멈추고, 나오는 차를 먼저 확인해요";
  }

  if (k.includes("오른쪽")) {
    if (place) return `${place} 앞에서 멈춘 뒤, 오른쪽으로 천천히 돌아요`;
    return "오른쪽으로 돌기 전, 뒤에서 오는 자전거도 확인해요";
  }

  if (k.includes("육교") || desc.includes("육교")) {
    return "손잡이를 잡고, 한 칸씩 천천히 걸어요";
  }

  if (k.includes("횡단") || desc.includes("횡단") || (tt >= 211 && tt <= 217)) {
    if (place) return `${place} 앞 횡단보도, 초록불일 때만 건너요`;
    return "손을 들고, 차가 멈춘 걸 확인한 뒤 건너요";
  }

  if (k.includes("직진")) {
    if (place) return `${place} 보이면 그대로 직진해요`;
    if (stepCount > 0 && stepCount <= 15) return "조금만 더 가면 돼요, 뛰지 말고 걸어요";
    if (stepCount >= 200) return "천천히 가도 괜찮아요, 보도 안쪽으로 걸어요";
    return "차도 쪽으로 나가지 말고, 보도 안쪽으로 걸어요";
  }

  return "";
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
    if (match) encoded = match[1];
  }

  if (!encoded) return null;

  encoded = String(encoded).trim();
  try {
    encoded = decodeURIComponent(encoded);
  } catch {
    /* keep raw */
  }
  return encoded.replace(/\//g, "");
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

const PRODUCTION_APP_URL = "https://kids-abcd.vercel.app";

function resolveKidGuideFrontendBase() {
  const host = window.location.hostname.toLowerCase();
  if (host.endsWith(".onrender.com")) {
    return PRODUCTION_APP_URL;
  }
  if (host.endsWith(".vercel.app") && host !== "kids-abcd.vercel.app") {
    return PRODUCTION_APP_URL;
  }
  if (window.location.protocol === "file:") {
    return "http://127.0.0.1:5500";
  }
  if (!host || host === "localhost" || host === "127.0.0.1") {
    return window.location.origin;
  }
  return window.location.origin;
}

function buildKidGuideShareUrl(payload) {
  const encoded = encodeKidGuidePayload(payload);
  const base = resolveKidGuideFrontendBase();

  if (encoded.length <= 1800) {
    return `${base}/guide?d=${encoded}`;
  }

  const chunks = encoded.match(/.{1,400}/g) || [];
  const query = chunks.map((chunk, idx) => `p${idx}=${encodeURIComponent(chunk)}`).join("&");
  return `${base}/guide?${query}`;
}

function buildKidGuideShortUrl(id) {
  return `${resolveKidGuideFrontendBase()}/guide?id=${encodeURIComponent(id)}`;
}
