// API_BASE는 auth.js에서 정의 (로컬 8000 / 배포 시 /api 프록시)

const CATEGORY_COLORS = {
  cctv: "#2f7dd1",
  hotspot: "#c45c26",
  docRisk: "#d64545",
  docRiskEstimated: "#e07070",
  guardian: "#8e44ad",
  safetyCctv: "#1a6fbf",
  safetyStreetlight: "#f5b800",
};

const PUBLIC_DATA_LEGEND = [
  ["safety-cctv", "safetyCctv", "안심귀갓길 CCTV"],
  ["safety-streetlight", "safetyStreetlight", "안심귀갓길 보안등"],
  ["cctv", "cctv", "어린이 보호구역 CCTV"],
  ["hotspot", "hotspot", "교통사고다발지역"],
  ["guardian", "guardian", "아동안전지킴이집"],
  ["doc-risk", "docRisk", "문서 기반 위험지역"],
];

const DEMO_SCENARIOS = {
  morning_school: {
    origin: "개나리SK뷰5차아파트",
    destination: "도성초등학교",
    age: 8,
    note: "도성초등학교 주변 통학로를 비교해 CCTV·보호구역이 많은 길을 추천합니다.",
  },
  night_academy: {
    origin: "필수학학원",
    destination: "개나리SK뷰5차아파트",
    age: 11,
    note: "야간 하원도 Tmap 보행자 큰길(대로 우선) 경로로 안내합니다.",
  },
  school_to_academy: {
    origin: "도성초등학교",
    destination: "필수학학원",
    age: 8,
    note: "도성초등학교에서 필수학학원으로 이동하는 길의 안전시설을 비교해 보여줍니다.",
  },
};

const state = {
  config: null,
  lastResult: null,
  publicData: null,
  tmapReady: false,
  tmap: null,
  tmapOverlays: [],
  infoWindow: null,
  mode: "parent",
  selectedRouteId: null,
  activePublicLayer: null,
  kidCardSteps: [],
  kidCardIndex: 0,
  // 구간 진행 스탬프 (안전 스탬프와 별개, 세션 단위)
  progressStamps: { third: false, twoThirds: false, arrive: false },
  clockTimer: null,
  // 안전 문서: 큐 → 확인(분석) 또는 반영 안함 → 경로 찾기 가능
  docQueue: [],
  docReady: false,
  docMode: null, // "analyzed" | "skipped" | null
  docQueueSeq: 0,
};

const PROGRESS_STAMP_DEFS = [
  { id: "third", at: 1 / 3, cheer: "잘했어! 1/3 왔어요 ⭐" },
  { id: "twoThirds", at: 2 / 3, cheer: "멋져요! 거의 다 왔어요 🌟" },
  { id: "arrive", at: 1, cheer: "도착! 오늘도 안전하게 와줘서 고마워요 👑" },
];

async function fetchJson(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const headers = {
    ...(options.headers || {}),
    ...authHeaders(),
  };
  let res;
  try {
    res = await fetch(url, { ...options, headers });
  } catch (err) {
    const onVercel = /\.vercel\.app$/i.test(window.location.hostname);
    if (onVercel) {
      throw new Error(
        "백엔드에 연결할 수 없습니다. Vercel에 BACKEND_URL(Render URL)이 설정됐는지 확인해 주세요."
      );
    }
    throw new Error("백엔드(127.0.0.1:8000)에 연결할 수 없습니다. backend 폴더에서 서버를 켜 주세요.");
  }
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${path} 요청 실패 (${res.status}): ${detail}`);
  }
  return res.json();
}

function fillDemoCoordinates() {
  const select = document.getElementById("demo-scenario-select");
  const scenario = DEMO_SCENARIOS[select.value] || DEMO_SCENARIOS.morning_school;

  document.getElementById("origin-query").value = scenario.origin;
  document.getElementById("dest-query").value = scenario.destination;
  // 아이 나이 입력란을 다시 활성화하면 함께 복원합니다.
  // document.getElementById("audience-age").value = scenario.age;

  const hint = document.getElementById("scenario-hint");
  if (hint) hint.textContent = scenario.note;
}

function swapLocations() {
  const origin = document.getElementById("origin-query");
  const destination = document.getElementById("dest-query");
  [origin.value, destination.value] = [destination.value, origin.value];
  origin.focus();
}

function scoreColor(score) {
  if (score >= 70) return "#2e9e5b";
  if (score >= 55) return "#e08a2c";
  return "#d64545";
}

function scoreExplanation(candidate, routeData = null) {
  const features = candidate.features || {};
  const safetyFacilities =
    (features.safety_facility_cctv_count || 0) +
    (features.safety_facility_streetlight_count || 0) +
    (features.safety_bell_count || 0) +
    (features.emergency112_count || 0);
  const riskDocs = (features.matched_documents || []).filter((d) => d.is_risk);
  const safeDocs = (features.matched_documents || []).filter((d) => !d.is_risk);
  const isRecommended = routeData && candidate.id === routeData.recommended_id;
  const parts = [];

  if (isRecommended) {
    parts.push(`이 길은 종합 안전점수 ${candidate.safety_score}점으로 가장 안전한 추천 경로예요.`);
  } else {
    parts.push(`이 길은 종합 안전점수 ${candidate.safety_score}점이에요.`);
  }

  if (candidate.id.includes("doc-avoid")) {
    parts.push("문서에 나온 위험·공사 구간을 피해 가도록 만든 우회 경로예요.");
  }

  parts.push(
    `안심시설 ${safetyFacilities}곳, 보호구역 통과 ${features.child_zone_coverage_pct ?? 0}%, 사고다발 ${features.accident_hotspot_count || 0}곳을 반영했어요.`
  );

  if (riskDocs.length) {
    parts.push(
      `문서 주의: ${riskDocs
        .slice(0, 2)
        .map((d) => d.risk_type || "위험구간")
        .join(", ")}.`
    );
  } else if (safeDocs.length) {
    parts.push(`문서상 안전조치가 확인된 구간이 있어요.`);
  }

  if (candidate.safety_score >= 70) {
    parts.push("전반적으로 안심하고 걸을 수 있는 편이에요.");
  } else if (candidate.safety_score < 55 || (features.accident_hotspot_count || 0) > 0 || riskDocs.length) {
    parts.push("주의 구간이 있으니 다른 경로와 비교해 보세요.");
  }

  return parts.join(" ");
}

function buildSelectedRouteSafetyText(candidate, routeData) {
  if (!candidate) return "";
  if (candidate.id === routeData.recommended_id && routeData.parent_report) {
    return routeData.parent_report;
  }
  const features = candidate.features || {};
  const docs = (features.matched_documents || [])
    .slice(0, 3)
    .map((d) => `- ${d.is_risk ? "주의" : "양호"} ${d.risk_type} (${d.source_doc})`)
    .join("\n");
  return [
    scoreExplanation(candidate, routeData),
    "",
    `거리 ${(candidate.distance_m / 1000).toFixed(2)}km · 약 ${Math.round(candidate.duration_s / 60)}분 · 안전등급 ${"⭐".repeat(candidate.star_rating || 0)}`,
    docs ? `\n문서 근거\n${docs}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function routeDisplayName(routeId) {
  if (routeId.includes("seolleung-sidewalk") || routeId.includes("sidewalk")) return "선릉로 보도 경로";
  if (routeId.includes("avoid-hotspot") || routeId.includes("hotspot-avoid")) return "사고다발 우회 경로";
  if (routeId.includes("doc-avoid") || routeId.includes("avoid-doc")) return "문서 위험 우회 경로";
  if (routeId.includes("pedestrian-main") || routeId.includes("direct")) return "보행자 큰길 경로";
  if (routeId.includes("opt0")) return "보행자 추천 경로";
  if (routeId.includes("opt4") || routeId.includes("pedestrian-alt")) return "보행자 큰길 경로";
  if (routeId.includes("opt10")) return "보행자 최단 경로";
  if (routeId.endsWith("-a") || routeId.includes("grid-a")) return "우회 경로 A";
  if (routeId.endsWith("-b") || routeId.includes("grid-b")) return "우회 경로 B";
  return "보행자 경로";
}

function routeDisplaySortKey(routeId) {
  if (routeId.includes("seolleung-sidewalk") || routeId.includes("sidewalk")) return 0;
  if (routeId.includes("pedestrian-main") || routeId.includes("direct")) return 0;
  if (routeId.includes("opt0")) return 1;
  if (routeId.includes("opt4") || routeId.includes("pedestrian-alt")) return 2;
  if (routeId.includes("opt10")) return 3;
  if (routeId.includes("avoid-hotspot") || routeId.includes("hotspot-avoid")) return 4;
  if (routeId.includes("doc-avoid") || routeId.includes("avoid-doc")) return 5;
  if (routeId.endsWith("-a") || routeId.includes("grid-a")) return 5;
  if (routeId.endsWith("-b") || routeId.includes("grid-b")) return 6;
  return 7;
}

function isDuplicateRouteCard(first, second) {
  return (
    Math.abs(first.distance_m - second.distance_m) <= 10 &&
    Math.abs(first.duration_s - second.duration_s) <= 20
  );
}

function candidatesForDisplay(routeData) {
  const uniqueCandidates = [...routeData.candidates]
    .sort((first, second) => routeDisplaySortKey(first.id) - routeDisplaySortKey(second.id))
    .filter(
      (candidate, index, candidates) =>
        !candidates.slice(0, index).some((existing) => isDuplicateRouteCard(existing, candidate))
    );
  const recommended =
    uniqueCandidates.find((candidate) => candidate.id === routeData.recommended_id) ||
    uniqueCandidates[0];
  if (!recommended) return [];

  const alternatives = uniqueCandidates
    .filter((candidate) => candidate.id !== recommended.id)
    .sort(
      (first, second) =>
        second.safety_score - first.safety_score ||
        routeDisplaySortKey(first.id) - routeDisplaySortKey(second.id)
    );
  return [recommended, ...alternatives];
}

function activeRouteId(routeData) {
  const visibleCandidates = candidatesForDisplay(routeData);
  if (state.selectedRouteId && visibleCandidates.some((candidate) => candidate.id === state.selectedRouteId)) {
    return state.selectedRouteId;
  }
  return visibleCandidates.some((candidate) => candidate.id === routeData.recommended_id)
    ? routeData.recommended_id
    : visibleCandidates[0]?.id;
}

function activeRoute(routeData) {
  return routeData.candidates.find((candidate) => candidate.id === activeRouteId(routeData));
}

function navigationIcon(step) {
  const description = step.description || "";
  const turnType = step.turn_type;
  if (turnType === 201 || description.includes("도착")) return ["⌖", "arrive"];
  if (description.includes("횡단보도") || description.includes("육교") || (turnType >= 211 && turnType <= 217)) {
    return ["🚸", "cross"];
  }
  const plain = navigationKeywordPlain(step);
  if (plain.includes("왼쪽")) return ["↰", "turn"];
  if (plain.includes("오른쪽")) return ["↱", "turn"];
  return ["↑", ""];
}

function navigationKeywordPlain(step) {
  const description = step.description || "";
  const tt = step.turn_type;
  if (tt === 201 || description.includes("도착")) return "도착";
  if (description.includes("횡단보도") || description.includes("육교") || (tt >= 211 && tt <= 217)) {
    return description.includes("육교") ? "육교 건너기" : "횡단보도 건너기";
  }
  if (description.includes("좌회전") || description.includes("좌측") || tt === 12 || tt === 16) {
    return "왼쪽으로 가기";
  }
  if (description.includes("우회전") || description.includes("우측") || tt === 13 || tt === 17) {
    return "오른쪽으로 가기";
  }
  if (tt === 200) return "출발";
  return "직진";
}

function navigationKeyword(step) {
  const plain = navigationKeywordPlain(step);
  if (plain === "도착") return plain;
  const distance = step.distance_m > 0 ? ` · ${Math.round(step.distance_m)}m` : "";
  return `${plain}${distance}`;
}

function simplifyCoordinates(coordinates, minDistM = 15) {
  if (!coordinates || coordinates.length <= 2) return coordinates || [];
  const out = [coordinates[0]];
  for (let i = 1; i < coordinates.length; i += 1) {
    const last = out[out.length - 1];
    if (haversineM(last, coordinates[i]) >= minDistM) {
      out.push(coordinates[i]);
    }
  }
  const end = coordinates[coordinates.length - 1];
  const last = out[out.length - 1];
  if (last.lat !== end.lat || last.lng !== end.lng) out.push(end);
  return out.length >= 2 ? out : coordinates;
}

function mergeNavigationSteps(steps) {
  const merged = [];
  for (const step of steps) {
    const key = navigationKeywordPlain(step);
    const prev = merged[merged.length - 1];
    if (
      prev &&
      navigationKeywordPlain(prev) === key &&
      key !== "횡단보도 건너기" &&
      key !== "육교 건너기" &&
      key !== "도착" &&
      key !== "출발"
    ) {
      prev.distance_m = Math.round((prev.distance_m + step.distance_m) * 10) / 10;
      continue;
    }
    merged.push({ ...step });
  }
  return merged;
}

function stepsForDisplay(steps) {
  return (steps || []).filter((s) => {
    if (s.turn_type === 200) return false;
    if ((s.description || "").trim() === "출발") return false;
    return true;
  });
}

// 아이는 "m" 단위 감이 없다. 아이 보폭(약 0.5m = 1걸음) 기준으로 걸음 수를 계산해
// 세면서 걸을 수 있게 한다. 예) 58m ≈ 116걸음. 너무 크거나 작은 숫자는
// "많이"/"조금만" 같은 표현을 함께 붙여 감을 잡도록 돕는다.
const KID_STRIDE_M = 0.5;

function kidStepCount(distanceM) {
  return Math.max(1, Math.round(distanceM / KID_STRIDE_M));
}

// { steps, text } 반환. text 예) "약 116걸음", "약 8걸음(조금만)", "약 240걸음(많이)"
function kidStepText(distanceM) {
  if (!distanceM || distanceM <= 0) return { steps: 0, text: "" };
  const steps = kidStepCount(distanceM);
  let qualifier = "";
  if (steps <= 15) qualifier = "(조금만)";
  else if (steps >= 200) qualifier = "(많이)";
  return { steps, text: `약 ${steps}걸음${qualifier}` };
}

function kidFriendlySteps(distanceM) {
  const { text } = kidStepText(distanceM);
  return text ? `👣 ${text}` : "";
}

// 목록/카드에서 쓰는 한 문장. 예) "왼쪽으로 약 116걸음 걸어가요 (58m)"
function navigationSentence(step) {
  const plain = navigationKeywordPlain(step);
  if (plain === "도착") return "목적지에 도착해요";
  const meters = step.distance_m > 0 ? ` (${Math.round(step.distance_m)}m)` : "";
  const { text } = kidStepText(step.distance_m);
  if (plain.includes("횡단보도") || plain.includes("육교")) return `${plain.replace(" 건너기", "")}를 건너요`;
  let direction = "앞으로";
  if (plain.includes("왼쪽")) direction = "왼쪽으로";
  else if (plain.includes("오른쪽")) direction = "오른쪽으로";
  if (!text) return `${direction} 걸어가요`;
  return `${direction} ${text} 걸어가요${meters}`;
}

function landmarkPhrase(step) {
  return step && step.landmark ? `${step.landmark} 쪽으로` : "";
}

/** 아이 카드용 상황별 안전 한마디 (본문 행동 안내와 별도 1줄) */
function kidSafetyTip(step, { isArrive = false, weather = null } = {}) {
  if (isArrive) return "도착! 오늘도 안전하게 와줘서 고마워요";

  const desc = `${step?.description || ""} ${navigationKeywordPlain(step) || ""}`;
  const tt = step?.turn_type;
  const raining = Boolean(weather?.is_rain);

  if (desc.includes("횡단") || desc.includes("육교") || (tt >= 211 && tt <= 217)) {
    if (desc.includes("신호") || desc.includes("초록")) return "초록불일 때 함께 건너요";
    return raining ? "미끄러울 수 있어요, 뛰지 말고 천천히" : "👀 왼쪽·오른쪽 보고 천천히 건너요";
  }
  if (desc.includes("좌회전") || desc.includes("우회전") || desc.includes("왼쪽") || desc.includes("오른쪽") || tt === 12 || tt === 13 || tt === 16 || tt === 17) {
    return "모퉁이에선 천천히, 나오는 차 조심해요";
  }
  if (desc.includes("골목") || desc.includes("이면")) {
    return "조용한 길이어도 좌우 살피요";
  }
  if (raining) return "길이 미끄러울 수 있어요, 천천히";
  if (desc.includes("대로") || desc.includes("큰길")) return "차와 멀리, 인도로 걸어요";
  return "휴대폰 보지 말고 앞을 봐요";
}

function totalStepDistanceM(steps) {
  return (steps || []).reduce((sum, s) => sum + (Number(s.distance_m) || 0), 0);
}

/** 현재 카드까지 진행률 (0~1). 마지막 카드는 항상 1 */
function kidProgressRatio(steps, index) {
  const list = steps || [];
  if (!list.length) return 0;
  if (index >= list.length - 1) return 1;
  const total = totalStepDistanceM(list);
  if (total <= 0) return (index + 1) / list.length;
  let walked = 0;
  for (let i = 0; i <= index; i += 1) walked += Number(list[i].distance_m) || 0;
  return Math.min(1, walked / total);
}

function resetProgressStamps() {
  state.progressStamps = { third: false, twoThirds: false, arrive: false };
  renderProgressStampSlots();
  hideKidCardCheer();
  hideStampBurst();
}

function renderProgressStampSlots(justUnlockedIds = []) {
  const root = document.getElementById("kid-progress-stamps");
  if (!root) return;
  PROGRESS_STAMP_DEFS.forEach((def) => {
    const el = root.querySelector(`[data-stamp="${def.id}"]`);
    if (!el) return;
    const unlocked = Boolean(state.progressStamps[def.id]);
    el.classList.toggle("unlocked", unlocked);
    if (justUnlockedIds.includes(def.id)) {
      el.classList.remove("just-unlocked");
      void el.offsetWidth;
      el.classList.add("just-unlocked");
      clearTimeout(el._stampAnimTimer);
      el._stampAnimTimer = setTimeout(() => el.classList.remove("just-unlocked"), 1400);
    }
  });
}

function hideKidCardCheer() {
  const el = document.getElementById("kid-card-cheer");
  if (!el) return;
  el.hidden = true;
  el.textContent = "";
  el.classList.remove("pop");
}

function hideStampBurst() {
  const burst = document.getElementById("kid-stamp-burst");
  if (!burst) return;
  burst.hidden = true;
  burst.classList.remove("show");
  document.getElementById("kid-card")?.classList.remove("stamp-celebrate");
  const particles = document.getElementById("kid-stamp-burst-particles");
  if (particles) particles.innerHTML = "";
}

function showStampBurst(stampId, message) {
  const burst = document.getElementById("kid-stamp-burst");
  const card = document.getElementById("kid-card");
  if (!burst || !card) return;

  const def = PROGRESS_STAMP_DEFS.find((d) => d.id === stampId);
  const stampEl = document.querySelector(`#kid-progress-stamps [data-stamp="${stampId}"]`);
  const emoji = stampEl?.querySelector(".kid-progress-stamp-emoji")?.textContent?.trim() || "⭐";
  const shortLabel =
    stampId === "arrive" ? "도착 스탬프!" : stampId === "twoThirds" ? "2/3 스탬프!" : "1/3 스탬프!";

  document.getElementById("kid-stamp-burst-emoji").textContent = emoji;
  document.getElementById("kid-stamp-burst-text").textContent = message || shortLabel;

  const particles = document.getElementById("kid-stamp-burst-particles");
  if (particles) {
    const bits = ["✨", "⭐", "🌟", "💛", "🎉", "✦", "✸", "💫"];
    particles.innerHTML = Array.from({ length: 14 }, (_, i) => {
      const angle = (i / 14) * 360;
      const dist = 72 + (i % 3) * 18;
      return `<span class="kid-stamp-particle" style="--a:${angle}deg;--d:${dist}px;--delay:${i * 0.03}s">${bits[i % bits.length]}</span>`;
    }).join("");
  }

  burst.hidden = false;
  burst.classList.remove("show");
  card.classList.remove("stamp-celebrate");
  void burst.offsetWidth;
  burst.classList.add("show");
  card.classList.add("stamp-celebrate");

  clearTimeout(showStampBurst._timer);
  showStampBurst._timer = setTimeout(() => hideStampBurst(), 1600);
}

function showKidCardCheer(message) {
  const el = document.getElementById("kid-card-cheer");
  if (!el || !message) return;
  el.textContent = message;
  el.hidden = false;
  el.classList.remove("pop");
  void el.offsetWidth;
  el.classList.add("pop");
  clearTimeout(showKidCardCheer._timer);
  showKidCardCheer._timer = setTimeout(() => {
    el.classList.remove("pop");
    el.hidden = true;
  }, 2200);
}

/** 진행률에 맞춰 구간 스탬프 unlock (뒤로 가도 잠그지 않음) */
function updateProgressStamps(ratio, { announce = true } = {}) {
  const justUnlocked = [];
  let cheer = "";
  let lastId = "";
  PROGRESS_STAMP_DEFS.forEach((def) => {
    if (ratio + 1e-9 >= def.at && !state.progressStamps[def.id]) {
      state.progressStamps[def.id] = true;
      justUnlocked.push(def.id);
      cheer = def.cheer;
      lastId = def.id;
    }
  });
  renderProgressStampSlots(justUnlocked);
  if (announce && lastId) {
    showStampBurst(lastId, cheer);
    showKidCardCheer(cheer);
  }
  return cheer;
}

function progressStampSummaryText() {
  const n = PROGRESS_STAMP_DEFS.filter((d) => state.progressStamps[d.id]).length;
  return `🚶 길 스탬프 ${n}/3`;
}

// API navigation_steps가 비어 있을 때(구버전 백엔드 등) 경로 좌표로 턴바이턴을 합성한다.
const SYNTH_CHUNK_PATTERN = [58, 84, 43, 71, 96, 52];

function haversineM(a, b) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function bearingDeg(a, b) {
  const toRad = (d) => (d * Math.PI) / 180;
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const dlng = toRad(b.lng - a.lng);
  const x = Math.sin(dlng) * Math.cos(lat2);
  const y = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dlng);
  return (Math.atan2(x, y) * (180 / Math.PI) + 360) % 360;
}

function synthesizeStepsFromCoordinates(coordinates) {
  const simplified = simplifyCoordinates(coordinates);
  if (!simplified || simplified.length < 2) return [];

  const steps = [];
  let prevBearing = null;
  let chunkI = 0;

  for (let i = 0; i < simplified.length - 1; i += 1) {
    const start = simplified[i];
    const end = simplified[i + 1];
    const legDist = haversineM(start, end);
    if (legDist < 1) continue;

    const bearing = bearingDeg(start, end);
    let turnDesc = "직진";
    let turnType = 11;
    if (prevBearing !== null) {
      const diff = ((bearing - prevBearing + 540) % 360) - 180;
      if (diff < -30) {
        turnDesc = "좌회전";
        turnType = 12;
      } else if (diff > 30) {
        turnDesc = "우회전";
        turnType = 13;
      }
    }
    prevBearing = bearing;

    let remaining = legDist;
    let walked = 0;
    let firstChunk = true;
    while (remaining > 1) {
      const d = Math.min(SYNTH_CHUNK_PATTERN[chunkI % SYNTH_CHUNK_PATTERN.length], remaining);
      chunkI += 1;
      walked += d;
      remaining -= d;
      const desc = firstChunk ? turnDesc : "직진";
      const tt = firstChunk ? turnType : 11;
      firstChunk = false;
      steps.push({ description: desc, turn_type: tt, distance_m: Math.round(d * 10) / 10, landmark: null });
    }

    if (i < simplified.length - 2 && (turnType === 12 || turnType === 13)) {
      const cwDist = Math.max(12, Math.min(35, Math.round(legDist * 0.25)));
      steps.push({ description: "횡단보도 건너기", turn_type: 211, distance_m: cwDist, landmark: null });
    }
  }

  steps.push({ description: "목적지 도착", turn_type: 201, distance_m: 0, landmark: null });
  return mergeNavigationSteps(steps);
}

function polishNavigationSteps(steps) {
  return mergeNavigationSteps(stepsForDisplay(steps));
}

function resolveNavigationSteps(route) {
  if (!route) return [];
  let steps = route.navigation_steps;
  if (steps && steps.length > 0) {
    steps = polishNavigationSteps(steps);
  } else {
    const synthesized = synthesizeStepsFromCoordinates(route.coordinates);
    if (synthesized.length > 0) {
      console.log(
        `[경로안내] API steps 없음 → 프론트에서 좌표 기반 합성 ${synthesized.length}단계`,
        route.id
      );
      steps = synthesized;
    }
  }
  if (steps && steps.length > 0) {
    route.navigation_steps = steps;
  }
  return steps || [];
}

function buildTurnGuide(navigationSteps) {
  const steps = stepsForDisplay(navigationSteps);
  if (!steps.length) {
    return '<li class="turn-step"><span>이 경로는 상세 보행 안내를 제공하지 않습니다.</span></li>';
  }

  return steps
    .map((step) => {
      const [icon, className] = navigationIcon(step);
      const landmark = landmarkPhrase(step);
      const line = navigationKeyword(step);
      const friendly = navigationSentence(step);
      const showFriendly = friendly && friendly !== line && !line.includes("도착");
      return `<li class="turn-step ${className}"><span class="turn-icon">${icon}</span><span class="turn-step-body"><strong>${line}</strong>${showFriendly ? `<br><small class="turn-step-friendly">${friendly}</small>` : ""}${landmark ? `<br><small class="turn-step-landmark">📍 ${landmark}</small>` : ""}</span></li>`;
    })
    .join("");
}

function facilityCounts(features) {
  const f = features || {};
  return {
    cctv: (f.safety_facility_cctv_count || 0) + (f.cctv_count || 0),
    streetlight: (f.safety_facility_streetlight_count || 0) + (f.streetlight_count || 0),
    safetyBell: f.safety_bell_count || 0,
    emergency112: f.emergency112_count || 0,
  };
}

function safetyFacilitiesNearRoute(publicData, routeData, radiusM = 140) {
  const all = pointsNearRecommendedRoute(publicData.safety_facilities || [], routeData, radiusM);
  return {
    cctv: all.filter((p) => p.facility_type === "cctv"),
    streetlight: all.filter((p) => p.facility_type === "streetlight"),
    safetyBell: all.filter((p) => p.facility_type === "safety_bell"),
    emergency112: all.filter((p) => p.facility_type === "emergency112"),
    all,
  };
}

function formatKoreanTime(date = new Date()) {
  const hour = date.getHours();
  const minute = date.getMinutes();
  let period;
  let displayHour;
  if (hour < 12) {
    period = "오전";
    displayHour = hour === 0 ? 12 : hour;
  } else if (hour === 12) {
    period = "오후";
    displayHour = 12;
  } else {
    period = "오후";
    displayHour = hour - 12;
  }
  return `${period} ${displayHour}:${String(minute).padStart(2, "0")}`;
}

function updateLiveClock() {
  const el = document.getElementById("live-clock");
  if (!el) return;
  el.textContent = formatKoreanTime();
}

function etaMessageForDuration(durationS) {
  if (!durationS || durationS <= 0) return "";
  const arrival = new Date(Date.now() + durationS * 1000);
  return `지금 출발하면 약 ${formatKoreanTime(arrival)} 도착`;
}

function routeTimeRange(durationS) {
  if (!durationS || durationS <= 0) return "";
  const departure = new Date();
  const arrival = new Date(departure.getTime() + durationS * 1000);
  return `${formatKoreanTime(departure)} 출발 → ${formatKoreanTime(arrival)} 도착`;
}

function updateEtaForSelectedRoute(routeData) {
  const selected = activeRoute(routeData);
  const eta = document.getElementById("time-eta");
  if (!selected || !eta) return;
  const msg = etaMessageForDuration(selected.duration_s);
  eta.textContent = msg ? ` · ${msg}` : "";
}

function renderTimeContext(routeData) {
  const banner = document.getElementById("time-banner");
  const icon = document.getElementById("time-banner-icon");
  const rec = document.getElementById("time-recommendation");
  const eta = document.getElementById("time-eta");
  const tc = routeData && routeData.time_context;
  if (!banner || !tc) {
    if (banner) banner.hidden = true;
    return;
  }

  banner.hidden = false;
  banner.classList.toggle("night", tc.is_night);
  if (icon) icon.textContent = tc.period_emoji || (tc.is_night ? "🌙" : "☀️");
  if (rec) rec.textContent = tc.recommendation_message || "";
  updateEtaForSelectedRoute(routeData);

  const modeMsg = document.getElementById("mode-message");
  if (modeMsg && tc.recommendation_message) {
    modeMsg.textContent = tc.recommendation_message;
  }
}

function renderParentReport(routeData) {
  const el = document.getElementById("parent-report");
  if (!el) return;
  const selected = activeRoute(routeData);
  // 설명1: 기존(선택 경로별 설명 또는 Solar 리포트)
  const text1 = selected
    ? buildSelectedRouteSafetyText(selected, routeData)
    : routeData && routeData.parent_report;
  // 설명2: 좋은점·우회 2그룹만 반영 (비교용)
  const text2 = routeData && routeData.parent_report_v2;
  if (!text1 && !text2) {
    el.textContent = "경로를 찾으면 시간대 맞춤 안전 리포트가 표시됩니다.";
    el.classList.add("placeholder");
    return;
  }
  const parts = [];
  if (text1) {
    parts.push(`【설명1 (기존)】\n${text1}`);
  }
  if (text2) {
    parts.push(`【설명2 (좋은점·우회 2그룹 반영)】\n${text2}`);
  }
  el.textContent = parts.join("\n\n──────────────\n\n");
  el.classList.remove("placeholder");
}

function startLiveClock() {
  updateLiveClock();
  if (state.clockTimer) clearInterval(state.clockTimer);
  state.clockTimer = setInterval(updateLiveClock, 30_000);
}

function renderCandidates(data) {
  const el = document.getElementById("candidates-list");
  const displayCandidates = candidatesForDisplay(data);
  el.innerHTML = displayCandidates
    .map((c) => {
      const isRecommended = c.id === displayCandidates[0]?.id;
      const isActive = c.id === activeRouteId(data);
      const routeName = isRecommended ? "추천 경로" : routeDisplayName(c.id);
      const docsHtml = (c.features.matched_documents || [])
        .map(
          (d) =>
            `<div class="doc-evidence">${d.is_risk ? "⚠️" : "✅"} <strong>${d.risk_type}</strong> (${d.source_doc}, 경로에서 ${Math.round(d.distance_m)}m) — "${d.snippet}"</div>`
        )
        .join("");
      const stars = "⭐".repeat(c.star_rating) + "☆".repeat(3 - c.star_rating);
      const stampsHtml = (c.stamps || [])
        .map(
          (s) =>
            `<span class="stamp-chip" title="${s.description}">${s.emoji} ${s.label}${s.count > 1 ? ` x${s.count}` : ""}</span>`
        )
        .join("");
      const explain = scoreExplanation(c, data);
      return `
        <div class="candidate-card ${isRecommended ? "recommended" : ""} ${isActive ? "selected" : ""}" data-route-id="${c.id}" role="button" tabindex="0" aria-pressed="${isActive}">
          <h4>
            <span>${routeName}${isRecommended ? '<span class="recommended-tag">★ 가장 안전한 길</span>' : ""}</span>
            <span class="score-pill" style="background:${scoreColor(c.safety_score)}">${c.safety_score}점</span>
          </h4>
          <div class="star-rating" title="안전 등급 ${c.star_rating}/3">${stars}</div>
          ${isRecommended ? `<div class="candidate-time">${routeTimeRange(c.duration_s)}</div>` : ""}
          <div class="candidate-meta candidate-summary">
            <span>거리: ${(c.distance_m / 1000).toFixed(2)}km</span>
            <span>예상 소요: ${Math.round(c.duration_s / 60)}분</span>
          </div>
          ${c.access_warning ? `<div class="access-warning" role="status">${c.access_warning}</div>` : ""}
          ${stampsHtml ? `<div class="stamps-row">${stampsHtml}</div>` : ""}
          <details class="candidate-details">
            <summary>상세보기 · 안전 설명</summary>
            <div class="safety-explain-block">
              <p class="safety-explain-label">안전 설명</p>
              <p class="score-explanation">💬 ${explain}</p>
            </div>
            <div class="candidate-meta detail-meta">
              <span>안심귀갓길 CCTV: ${c.features.safety_facility_cctv_count || 0}대</span>
              <span>안심귀갓길 보안등: ${c.features.safety_facility_streetlight_count || 0}개</span>
              <span>안심벨: ${c.features.safety_bell_count || 0} · 112: ${c.features.emergency112_count || 0}</span>
              <span>보호구역 통과율: ${c.features.child_zone_coverage_pct}%</span>
              <span>사고다발지역: ${c.features.accident_hotspot_count}곳</span>
              <span>범죄위험 근사지수: ${c.features.crime_risk_proxy}</span>
              <span>안전지킴이집: ${c.features.guardian_house_count}곳</span>
              <span>보안등: 1km당 ${c.features.streetlight_density}개</span>
              <span>단속카메라: ${c.features.speed_camera_count}곳</span>
              <span>문서 위험 지점: ${c.features.doc_risk_count || 0}곳</span>
            </div>
            ${docsHtml}
          </details>
        </div>`;
    })
    .join("");
}

function renderReports(data) {
  const recommended = activeRoute(data);
  const keywords = document.getElementById("kid-keywords");
  const directions = document.getElementById("kid-directions");
  const board = document.getElementById("kid-stamp-board");
  if (!recommended) {
    keywords.innerHTML = "";
    directions.innerHTML = "";
    board.innerHTML = "";
    state.kidCardSteps = [];
    resetKidGuideShareCache();
    return;
  }

  state.kidCardSteps = resolveNavigationSteps(recommended);
  resetKidGuideShareCache();
  console.log(
    `[경로안내] 선택 경로 ${recommended.id} · ${state.kidCardSteps.length}단계`,
    state.kidCardSteps.slice(0, 5)
  );
  const fc = facilityCounts(recommended.features);

  keywords.innerHTML = `
    <span class="route-keyword score">안전 ${recommended.safety_score}점</span>
    <span class="route-keyword">${data.time_context?.period_emoji || "☀️"} ${data.time_context?.period_label || "낮"}</span>
    <span class="route-keyword">CCTV ${fc.cctv}곳</span>
    <span class="route-keyword">보안등 ${fc.streetlight}개</span>
    <span class="route-keyword">🔔 ${fc.safetyBell}</span>
    ${data.time_context?.eta_message ? `<span class="route-keyword">${data.time_context.eta_message}</span>` : ""}
    <span class="route-keyword">${Math.round(recommended.duration_s / 60)}분</span>
  `;
  directions.innerHTML = `
    <section class="turn-guide" aria-label="아이용 길 안내">
      <div class="turn-guide-header">
        <h5>오늘은 이렇게 걸어요 <span class="turn-step-count">${state.kidCardSteps.length}단계</span></h5>
        <button type="button" id="kid-card-mode-btn" class="kid-card-mode-btn">👶 아이가 보기 쉽게</button>
      </div>
      <ol class="turn-steps">${buildTurnGuide(state.kidCardSteps)}</ol>
    </section>
  `;
  document.getElementById("kid-card-mode-btn").addEventListener("click", openKidCardMode);

  if (!recommended.stamps || recommended.stamps.length === 0) {
    board.innerHTML = `<div class="kid-progress-summary">🚶 길 스탬프는 「아이가 보기 쉽게」에서 받아요</div>`;
    return;
  }
  const stars = "⭐".repeat(recommended.star_rating);
  board.innerHTML = `
    <div class="kid-progress-summary">🚶 길 스탬프는 「아이가 보기 쉽게」에서 받아요</div>
    <div class="stamp-board-title">🎉 오늘의 안전 스탬프 ${stars}</div>
    <div class="stamps-row">
      ${recommended.stamps
        .map(
          (s) =>
            `<span class="stamp-chip big" title="${s.description}">${s.emoji} ${s.label}${s.count > 1 ? ` x${s.count}` : ""}</span>`
        )
        .join("")}
    </div>`;
}

function openKidCardMode() {
  if (!state.lastResult) {
    alert("먼저 안전 경로를 찾아주세요.");
    return;
  }
  const route = activeRoute(state.lastResult);
  const steps = resolveNavigationSteps(route) || state.kidCardSteps;
  if (!steps || steps.length === 0) {
    alert("이 경로에 상세 보행 안내를 만들 수 없습니다.\n출발지와 도착지를 다시 확인해 주세요.");
    return;
  }
  state.kidCardSteps = steps;
  state.kidCardIndex = 0;
  resetProgressStamps();
  document.getElementById("kid-card-overlay").hidden = false;
  renderKidCard(0);
}

function closeKidCardMode() {
  document.getElementById("kid-card-overlay").hidden = true;
  hideKidCardCheer();
  updateKidProgressSummaryOnBoard();
}

function updateKidProgressSummaryOnBoard() {
  const board = document.getElementById("kid-stamp-board");
  if (!board) return;
  let line = board.querySelector(".kid-progress-summary");
  const unlocked = PROGRESS_STAMP_DEFS.filter((d) => state.progressStamps[d.id]).length;
  if (unlocked === 0 && !line) return;
  if (!line) {
    line = document.createElement("div");
    line.className = "kid-progress-summary";
    board.prepend(line);
  }
  line.textContent =
    unlocked >= 3
      ? "🚶 오늘 길 스탬프 3/3 · 안전하게 도착했어요!"
      : `${progressStampSummaryText()} · 「아이가 보기 쉽게」에서 받아요`;
}

let cachedKidGuideShareUrl = null;

function resetKidGuideShareCache() {
  cachedKidGuideShareUrl = null;
}

function buildKidGuideSharePayload() {
  const route = activeRoute(state.lastResult);
  const steps = state.kidCardSteps;
  const origin = document.getElementById("origin-query")?.value?.trim() || "";
  const destination = document.getElementById("dest-query")?.value?.trim() || "";
  return {
    title: origin && destination ? `${origin} → ${destination}` : "오늘의 안전 길",
    origin,
    destination,
    safety_score: route?.safety_score ?? null,
    duration_min: route ? Math.round(route.duration_s / 60) : null,
    steps: steps.map((step, idx) => {
      const isArrive = idx === steps.length - 1;
      const [icon] = navigationIcon(step);
      const { text: stepText } = kidStepText(step.distance_m);
      const landmark = landmarkPhrase(step);
      const weather = state.lastResult?.weather || null;
      return {
        icon: isArrive ? "🎉" : icon,
        keyword: isArrive ? "도착! 잘했어요" : navigationKeywordPlain(step),
        friendly: isArrive || !stepText ? "" : `👣 ${stepText} 걸어가요`,
        tip: kidSafetyTip(step, { isArrive, weather }),
        distance_m: isArrive ? 0 : step.distance_m || 0,
        landmark: isArrive || !landmark ? "" : `📍 ${landmark}`,
        is_arrive: isArrive,
      };
    }),
  };
}

function buildKidGuideShareText() {
  const payload = buildKidGuideSharePayload();
  const title = payload.title || "오늘의 안전 길";
  return `👶 ${title}\n링크를 누르면 길 안내 카드가 바로 열려요!`;
}

async function ensureKidGuideShareUrl() {
  cachedKidGuideShareUrl = buildKidGuideShareUrl(buildKidGuideSharePayload());
  return cachedKidGuideShareUrl;
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function showKidShareToast(message) {
  let toast = document.getElementById("kid-share-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "kid-share-toast";
    toast.className = "kid-share-toast";
    toast.setAttribute("role", "status");
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(showKidShareToast._timer);
  showKidShareToast._timer = setTimeout(() => toast.classList.remove("visible"), 2800);
}

async function shareKidGuide(mode = "kakao") {
  if (!state.kidCardSteps.length) {
    alert("먼저 길 안내를 만들어 주세요.");
    return;
  }

  const buttonId = mode === "copy" ? "kid-card-share-copy" : "kid-card-share-kakao";
  const button = document.getElementById(buttonId);
  const originalText = button?.textContent || "";

  try {
    if (button) {
      button.disabled = true;
      button.textContent = mode === "copy" ? "복사하는 중…" : "보내는 중…";
    }

    resetKidGuideShareCache();
    const payload = buildKidGuideSharePayload();
    const url = await ensureKidGuideShareUrl();
    const shareTitle = `👶 ${payload.title || "오늘의 안전 길"}`;

    if (mode === "kakao" && navigator.share) {
      try {
        await navigator.share({
          title: shareTitle,
          text: buildKidGuideShareText(),
          url,
        });
        return;
      } catch (shareErr) {
        if (shareErr?.name === "AbortError") return;
      }
    }

    await copyTextToClipboard(url);
    showKidShareToast(
      mode === "kakao"
        ? "링크가 복사됐어요. 카톡에 붙여넣기 하세요."
        : "링크가 복사됐어요!"
    );
  } catch (err) {
    if (err?.name !== "AbortError") {
      alert(err?.message || "공유에 실패했습니다.");
    }
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

function renderKidCard(direction = 0) {
  const steps = state.kidCardSteps;
  const total = steps.length;
  const index = Math.min(state.kidCardIndex, total - 1);
  const step = steps[index];
  const isArrive = index === total - 1;
  const [icon] = navigationIcon(step);
  const { text: stepText } = kidStepText(step.distance_m);
  const landmark = landmarkPhrase(step);
  const weather = state.lastResult?.weather || null;
  const tip = kidSafetyTip(step, { isArrive, weather });
  const ratio = kidProgressRatio(steps, index);
  const plain = navigationKeywordPlain(step);
  // 한 줄만: 횡단·회전·도착은 tip, 직진은 걸음 수 (m·tip·걸음 동시 표시 안 함)
  const preferTip =
    isArrive ||
    plain.includes("횡단") ||
    plain.includes("육교") ||
    plain.includes("왼쪽") ||
    plain.includes("오른쪽");
  let support = "";
  if (preferTip) support = tip || "";
  else if (stepText) support = `👣 ${stepText} 걸어가요`;
  else support = tip || "";

  document.getElementById("kid-card-progress").textContent = `${index + 1} / ${total}`;
  document.getElementById("kid-card").classList.toggle("arrived", isArrive);
  document.getElementById("kid-card-icon").textContent = isArrive ? "🎉" : icon;
  document.getElementById("kid-card-text").textContent = isArrive ? "도착! 잘했어요" : plain;
  const supportEl = document.getElementById("kid-card-support");
  if (supportEl) {
    supportEl.textContent = support;
    supportEl.classList.toggle("is-tip", preferTip && Boolean(tip));
    supportEl.classList.toggle("is-steps", !preferTip && Boolean(stepText));
  }
  document.getElementById("kid-card-landmark").textContent =
    isArrive || !landmark ? "" : `📍 ${landmark}`;
  const prevBtn = document.getElementById("kid-card-prev");
  if (prevBtn) {
    prevBtn.hidden = index === 0;
    prevBtn.disabled = index === 0;
  }
  const nextBtn = document.getElementById("kid-card-next");
  nextBtn.hidden = isArrive;
  nextBtn.textContent = index >= total - 2 ? "도착! →" : "다음 →";
  document.querySelector(".kid-card-nav")?.classList.toggle("solo-next", index === 0 && !isArrive);

  // 공유는 부모용 → 도착 카드에만
  const shareRow = document.getElementById("kid-card-share-row");
  if (shareRow) shareRow.hidden = !isArrive;

  updateProgressStamps(ratio, { announce: direction !== 0 || index === 0 });
  animateKidCard(direction);
}

// 카드 넘김 효과: 다음이면 오른쪽에서, 이전이면 왼쪽에서 슬라이드 인.
function animateKidCard(direction) {
  const stage = document.querySelector(".kid-card-stage");
  if (!stage) return;
  stage.classList.remove("slide-next", "slide-prev");
  // 리플로우를 강제해 애니메이션을 재시작시킨다.
  void stage.offsetWidth;
  stage.classList.add(direction < 0 ? "slide-prev" : "slide-next");
}

function stepKidCard(delta) {
  const total = state.kidCardSteps.length;
  const next = Math.min(total - 1, Math.max(0, state.kidCardIndex + delta));
  if (next === state.kidCardIndex) return;
  state.kidCardIndex = next;
  renderKidCard(delta);
}

function renderLegend() {
  const el = document.getElementById("legend");
  el.innerHTML = `
    <span class="legend-instruction">공공데이터 항목에 커서를 올리면 지도에 표시됩니다.</span>
    ${PUBLIC_DATA_LEGEND.map(
      ([layer, color, label]) =>
        `<button type="button" class="legend-item" data-public-layer="${layer}"><span class="dot" style="background:${CATEGORY_COLORS[color]}"></span>${label}</button>`
    ).join("")}
    <span class="legend-route-help">굵은 실선 = 선택한 경로 · 빨간 구간선 = 문서 위험(시작~끝)</span>
  `;
  el.querySelectorAll("[data-public-layer]").forEach((item) => {
    const showLayer = () => setActivePublicLayer(item.dataset.publicLayer);
    item.addEventListener("pointerenter", showLayer);
    item.addEventListener("focus", showLayer);
    item.addEventListener("pointerleave", () => setActivePublicLayer(null));
    item.addEventListener("blur", () => setActivePublicLayer(null));
  });
}

function setActivePublicLayer(layer) {
  if (state.activePublicLayer === layer) return;
  state.activePublicLayer = layer;
  if (state.lastResult && state.publicData) {
    renderMap(state.lastResult, state.publicData, false);
  } else if (state.publicData && state.docMode === "analyzed") {
    renderDocRiskOnlyMap(state.publicData);
  }
}

function shouldShowPublicLayer(layer) {
  // 문서 분석 후에는 범례에 올리지 않아도 문서 위험이 항상 보이게
  if (layer === "doc-risk" && state.docMode === "analyzed") return true;
  return state.activePublicLayer === layer;
}

function documentRiskPointsForMap(publicData, routeData) {
  const all = (publicData?.doc_risk_points || []).filter((d) => d.is_risk && !d.is_estimated);
  if (!all.length) return [];
  // 문서 반영 직후면 경로 검색 전에도 전체 표시
  if (state.docMode === "analyzed" || !routeData || !activeRoute(routeData)) return all;
  const near = pointsNearRecommendedRoute(all, routeData, 220);
  return near.length ? near : all;
}

function docRiskHasSegment(d) {
  return (
    Number.isFinite(d?.end_lat) &&
    Number.isFinite(d?.end_lng) &&
    (Math.abs(d.end_lat - d.lat) > 1e-6 || Math.abs(d.end_lng - d.lng) > 1e-6)
  );
}

function docRiskTitle(d) {
  const prefix = d.is_estimated ? "[추정] " : "";
  const label = d.location_text || d.risk_type || "위험";
  const src = d.source_doc ? ` (${d.source_doc})` : "";
  return `${prefix}[문서근거] ${label}${src}`;
}

function docRiskInfoHtml(d) {
  const lines = [`<strong>${docRiskTitle(d)}</strong>`];
  const startQ = d.geocode_query || "";
  const endQ = d.end_geocode_query || "";
  if (startQ && endQ) {
    lines.push(`검색어: ${startQ} ~ ${endQ}`);
  } else if (startQ) {
    lines.push(`검색어: ${startQ}`);
  }
  if (d.matched_label) lines.push(`매칭: ${d.matched_label}`);
  return `<div style="padding:6px 8px;font-size:12px;line-height:1.45;max-width:260px;">${lines.join("<br>")}</div>`;
}

/** 문서 위험: 구간이면 해당 시작~끝만 선으로 연결(지점끼리 연쇄 연결 금지). */
function drawDocRiskOverlays(points, { track, bounds, onBounds }) {
  let segmentCount = 0;
  points.forEach((d) => {
    const color = d.is_estimated ? CATEGORY_COLORS.docRiskEstimated : CATEGORY_COLORS.docRisk;
    const title = docRiskTitle(d);
    const start = new Tmapv2.LatLng(d.lat, d.lng);
    bounds.extend(start);
    if (onBounds) onBounds();

    if (docRiskHasSegment(d)) {
      const end = new Tmapv2.LatLng(d.end_lat, d.end_lng);
      bounds.extend(end);
      if (onBounds) onBounds();
      track(
        new Tmapv2.Polyline({
          path: [start, end],
          strokeColor: color,
          strokeWeight: 5,
          strokeStyle: "solid",
          strokeOpacity: 0.9,
          map: state.tmap,
        })
      );
      segmentCount += 1;
      [start, end].forEach((latlng) => {
        const m = track(
          new Tmapv2.Marker({
            position: latlng,
            icon: tmapDotIcon(color),
            iconSize: new Tmapv2.Size(14, 14),
            map: state.tmap,
          })
        );
        m.addListener("click", () => {
          if (state.infoWindow) state.infoWindow.setMap(null);
          state.infoWindow = new Tmapv2.InfoWindow({
            position: latlng,
            content: docRiskInfoHtml(d),
            type: 2,
            map: state.tmap,
          });
        });
      });
      return;
    }

    const m = track(
      new Tmapv2.Marker({
        position: start,
        icon: tmapDotIcon(color),
        iconSize: new Tmapv2.Size(18, 18),
        map: state.tmap,
      })
    );
    m.addListener("click", () => {
      if (state.infoWindow) state.infoWindow.setMap(null);
      state.infoWindow = new Tmapv2.InfoWindow({
        position: start,
        content: docRiskInfoHtml(d),
        type: 2,
        map: state.tmap,
      });
    });
  });
  return segmentCount;
}

function renderDocRiskOnlyMap(publicData) {
  if (!state.tmapReady || !state.tmap) {
    setMapStatus("지도를 준비한 뒤 문서 위험이 표시됩니다.", false);
    return;
  }
  setMapStatus("", false);
  document.getElementById("tmap").style.display = "block";
  document.getElementById("svg-map").style.display = "none";
  clearTmapOverlays();

  const points = documentRiskPointsForMap(publicData, null);
  if (!points.length) {
    setMapStatus("표시할 문서 위험 지점이 아직 없어요.", false);
    return;
  }

  const bounds = new Tmapv2.LatLngBounds();
  const track = (overlay) => {
    state.tmapOverlays.push(overlay);
    return overlay;
  };

  const segmentCount = drawDocRiskOverlays(points, { track, bounds });
  state.tmap.fitBounds(bounds);
  const pinOnly = points.length - segmentCount;
  const parts = [];
  if (segmentCount) parts.push(`구간 선 ${segmentCount}개`);
  if (pinOnly > 0) parts.push(`핀 ${pinOnly}곳`);
  setMapStatus(`문서 위험 ${parts.join(" · ") || `${points.length}곳`} 표시`, false);
  renderLegend();
}

// ---------- SVG 스키매틱 지도 (Leaflet/OSM 로드 실패 시 오프라인 폴백) ----------

function computeBounds(points) {
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  return {
    minLat: Math.min(...lats),
    maxLat: Math.max(...lats),
    minLng: Math.min(...lngs),
    maxLng: Math.max(...lngs),
  };
}

function project(point, bounds, size, padding) {
  const latSpan = bounds.maxLat - bounds.minLat || 0.001;
  const lngSpan = bounds.maxLng - bounds.minLng || 0.001;
  const x = padding + ((point.lng - bounds.minLng) / lngSpan) * (size - padding * 2);
  // 위도는 위로 갈수록 커지므로 SVG y축(아래로 증가)에 맞춰 반전
  const y = size - padding - ((point.lat - bounds.minLat) / latSpan) * (size - padding * 2);
  return { x, y };
}

function distanceMeters(a, b) {
  const radians = (value) => (value * Math.PI) / 180;
  const latDelta = radians(b.lat - a.lat);
  const lngDelta = radians(b.lng - a.lng);
  const lat1 = radians(a.lat);
  const lat2 = radians(b.lat);
  const value =
    Math.sin(latDelta / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(lngDelta / 2) ** 2;
  return 6_371_000 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

function pointsNearRecommendedRoute(points, routeData, radiusM = 140) {
  const selected = activeRoute(routeData);
  if (!selected) return [];
  return points.filter((point) => {
    const ends = [{ lat: point.lat, lng: point.lng }];
    if (docRiskHasSegment(point)) {
      ends.push({ lat: point.end_lat, lng: point.end_lng });
    }
    return ends.some((end) =>
      selected.coordinates.some((coordinate) => distanceMeters(end, coordinate) <= radiusM)
    );
  });
}

function renderSvgMap(routeData, publicData) {
  const svg = document.getElementById("svg-map");
  const size = 600;
  const padding = 40;
  svg.innerHTML = "";

  const childZones = pointsNearRecommendedRoute(publicData.child_zones || [], routeData);
  const accidentHotspots = pointsNearRecommendedRoute(publicData.accident_hotspots || [], routeData);
  const guardianHouses = pointsNearRecommendedRoute(publicData.guardian_houses || [], routeData);
  const sf = safetyFacilitiesNearRoute(publicData, routeData);
  const documentPoints = documentRiskPointsForMap(publicData, routeData);
  const allPoints = [];
  const active = activeRoute(routeData);
  routeData.candidates.forEach((c) => {
    if (!active || c.id !== active.id) return;
    c.coordinates.forEach((pt) => allPoints.push(pt));
  });
  [childZones, accidentHotspots, guardianHouses, sf.cctv, sf.streetlight, documentPoints]
    .forEach((points) =>
      points.forEach((point) => {
        allPoints.push(point);
        if (docRiskHasSegment(point)) {
          allPoints.push({ lat: point.end_lat, lng: point.end_lng });
        }
      })
    );
  if (allPoints.length === 0) return;

  const bounds = computeBounds(allPoints);

  const ns = "http://www.w3.org/2000/svg";
  const bg = document.createElementNS(ns, "rect");
  bg.setAttribute("x", 0);
  bg.setAttribute("y", 0);
  bg.setAttribute("width", size);
  bg.setAttribute("height", size);
  bg.setAttribute("fill", "#eef3f8");
  svg.appendChild(bg);

  // 선택한 경로만 폴리라인으로 표시
  if (active && active.coordinates.length >= 2) {
    const pts = active.coordinates.map((pt) => project(pt, bounds, size, padding));
    const path = document.createElementNS(ns, "polyline");
    path.setAttribute("points", pts.map((p) => `${p.x},${p.y}`).join(" "));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", scoreColor(active.safety_score));
    path.setAttribute("stroke-width", 5);
    path.setAttribute("stroke-opacity", 0.95);
    path.setAttribute("stroke-linecap", "round");
    svg.appendChild(path);
  }

  function drawMarker(pt, color, shape, title) {
    const p = project(pt, bounds, size, padding);
    let node;
    if (shape === "circle") {
      node = document.createElementNS(ns, "circle");
      node.setAttribute("cx", p.x);
      node.setAttribute("cy", p.y);
      node.setAttribute("r", 6);
    } else if (shape === "triangle") {
      node = document.createElementNS(ns, "polygon");
      const s = 8;
      node.setAttribute("points", `${p.x},${p.y - s} ${p.x - s},${p.y + s} ${p.x + s},${p.y + s}`);
    } else if (shape === "diamond") {
      node = document.createElementNS(ns, "polygon");
      const s = 7;
      node.setAttribute("points", `${p.x},${p.y - s} ${p.x + s},${p.y} ${p.x},${p.y + s} ${p.x - s},${p.y}`);
    } else {
      node = document.createElementNS(ns, "rect");
      node.setAttribute("x", p.x - 6);
      node.setAttribute("y", p.y - 6);
      node.setAttribute("width", 12);
      node.setAttribute("height", 12);
    }
    node.setAttribute("fill", color);
    node.setAttribute("stroke", "white");
    node.setAttribute("stroke-width", 1.5);
    const titleEl = document.createElementNS(ns, "title");
    titleEl.textContent = title;
    node.appendChild(titleEl);
    svg.appendChild(node);
  }

  if (shouldShowPublicLayer("cctv")) {
    childZones.forEach((z) =>
      drawMarker(z, CATEGORY_COLORS.cctv, "circle", `${z.name || "어린이보호구역"} (CCTV ${z.cctv_count}대)`)
    );
  }
  if (shouldShowPublicLayer("safety-cctv")) sf.cctv.forEach((f) =>
    drawMarker(f, CATEGORY_COLORS.safetyCctv, "circle", `📹 ${f.label} ${f.install_count > 1 ? `x${f.install_count}` : ""} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("safety-streetlight")) sf.streetlight.forEach((f) =>
    drawMarker(f, CATEGORY_COLORS.safetyStreetlight, "circle", `💡 ${f.label} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("hotspot")) accidentHotspots.forEach((h) =>
    drawMarker(h, CATEGORY_COLORS.hotspot, "triangle", `${h.name || "사고다발지역"} (${h.occurrence_count}건)`)
  );
  if (shouldShowPublicLayer("guardian")) guardianHouses.forEach((g) =>
    drawMarker(g, CATEGORY_COLORS.guardian, "diamond", `🏪 ${g.name || "아동안전지킴이집"}`)
  );
  if (shouldShowPublicLayer("doc-risk")) {
    documentPoints.forEach((d) => {
      const color = d.is_estimated ? CATEGORY_COLORS.docRiskEstimated : CATEGORY_COLORS.docRisk;
      const title = docRiskTitle(d);
      if (docRiskHasSegment(d)) {
        const a = project(d, bounds, size, padding);
        const b = project({ lat: d.end_lat, lng: d.end_lng }, bounds, size, padding);
        const path = document.createElementNS(ns, "polyline");
        path.setAttribute("points", `${a.x},${a.y} ${b.x},${b.y}`);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", 4);
        path.setAttribute("stroke-opacity", 0.9);
        path.setAttribute("stroke-linecap", "round");
        const titleEl = document.createElementNS(ns, "title");
        titleEl.textContent = title;
        path.appendChild(titleEl);
        svg.appendChild(path);
        drawMarker(d, color, "square", title);
        drawMarker({ lat: d.end_lat, lng: d.end_lng }, color, "square", title);
      } else {
        drawMarker(d, color, "square", title);
      }
    });
  }

  // 출발/도착: 사진과 같은 물방울 핀 (SVG 폴백)
  [routeData.origin, routeData.destination].forEach((wp, idx) => {
    const p = project(wp, bounds, size, padding);
    const pin = waypointPinIcon(idx === 0 ? "origin" : "destination");
    const img = document.createElementNS(ns, "image");
    img.setAttribute("href", pin.url);
    img.setAttributeNS("http://www.w3.org/1999/xlink", "href", pin.url);
    img.setAttribute("width", String(pin.width));
    img.setAttribute("height", String(pin.height));
    img.setAttribute("x", String(p.x - pin.width / 2));
    img.setAttribute("y", String(p.y - pin.height));
    svg.appendChild(img);
  });
}

// ---------- Tmap 지도 (Tmap JS SDK v2) ----------

function setMapStatus(message, visible = true) {
  const el = document.getElementById("map-status");
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("visible", Boolean(visible && message));
}

function isTmapReady() {
  const T = window.Tmapv2;
  // Tmapv2 객체만 있고 LatLng/Map 생성자가 아직 없는 순간이 있음 → 둘 다 function 일 때만 준비 완료
  return Boolean(
    T &&
      typeof T.Map === "function" &&
      typeof T.LatLng === "function" &&
      typeof T.LatLngBounds === "function" &&
      typeof T.Polyline === "function" &&
      typeof T.Marker === "function"
  );
}

function loadScriptOnce(src, datasetKey) {
  return new Promise((resolve, reject) => {
    const existing = datasetKey
      ? document.querySelector(`script[data-tmap-sdk="${datasetKey}"]`)
      : document.querySelector(`script[src="${src}"]`);
    if (existing) {
      if (existing.dataset.loaded === "1") return resolve();
      if (existing.readyState === "complete" || existing.readyState === "loaded") {
        existing.dataset.loaded = "1";
        return resolve();
      }
      const timer = setTimeout(
        () => reject(new Error(`스크립트 로드 시간 초과: ${src}`)),
        20000
      );
      existing.addEventListener("load", () => {
        clearTimeout(timer);
        existing.dataset.loaded = "1";
        resolve();
      });
      existing.addEventListener("error", () => {
        clearTimeout(timer);
        existing.remove();
        reject(new Error(`스크립트 로드 실패: ${src}`));
      });
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    if (datasetKey) script.dataset.tmapSdk = datasetKey;
    const timer = setTimeout(
      () => reject(new Error(`스크립트 로드 시간 초과: ${src}`)),
      20000
    );
    script.onload = () => {
      clearTimeout(timer);
      script.dataset.loaded = "1";
      resolve();
    };
    script.onerror = () => {
      clearTimeout(timer);
      script.remove();
      reject(new Error(`스크립트 로드 실패: ${src}`));
    };
    document.head.appendChild(script);
  });
}

async function waitUntil(predicate, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error(label || "대기 시간 초과");
}

async function loadTmapSdk(appKey) {
  if (!appKey) {
    throw new Error("Tmap appKey가 없습니다. Render Environment에 TMAP_APP_KEY를 설정하세요.");
  }

  if (isTmapReady()) {
    window.__TMAP_APP_KEY__ = appKey;
    try {
      window.Tmapv2.appKey = appKey;
    } catch (_) {
      /* ignore */
    }
    return;
  }

  const coreUrls = [1, 2, 3].map(
    (n) => `https://topopentile${n}.tmap.co.kr/scriptSDKV2/tmapjs2.min.js?version=20231206`
  );
  let lastError = null;
  for (let i = 0; i < coreUrls.length; i += 1) {
    try {
      await loadScriptOnce(coreUrls[i], `tmap-core-${i + 1}`);
      await waitUntil(isTmapReady, 15000, "Tmap SDK를 불러오지 못했습니다.");
      window.__TMAP_APP_KEY__ = appKey;
      if (typeof window.Tmapv2.setHttpsMode === "function") {
        window.Tmapv2.setHttpsMode(true);
      }
      try {
        window.Tmapv2.appKey = appKey;
      } catch (_) {
        /* ignore */
      }
      return;
    } catch (err) {
      lastError = err;
      document.querySelector(`script[data-tmap-sdk="tmap-core-${i + 1}"]`)?.remove();
    }
  }
  throw lastError || new Error("Tmap SDK를 불러오지 못했습니다.");
}

async function tryInitTmap() {
  const container = document.getElementById("tmap");
  const svgEl = document.getElementById("svg-map");
  try {
    setMapStatus("티맵 지도를 불러오는 중…", true);
    const appKey =
      (state.config && state.config.tmap_web_key) ||
      window.__TMAP_APP_KEY__ ||
      "";
    await loadTmapSdk(appKey);

    // 로그인 직후 app-shell 표시 직후 레이아웃 확정 대기
    await new Promise((resolve) => requestAnimationFrame(resolve));

    // 이전에 실패한 지도 DOM이 남아 있으면 비우고 다시 생성
    container.innerHTML = "";
    container.style.display = "block";
    container.style.width = "100%";
    container.style.height = "420px";
    if (svgEl) svgEl.style.display = "none";

    const center = (state.config && state.config.demo_center) || { lat: 37.5013, lng: 127.0396 };
    const T = window.Tmapv2;
    state.tmap = new T.Map("tmap", {
      center: new T.LatLng(center.lat, center.lng),
      width: "100%",
      height: "420px",
      zoom: 16,
      zoomControl: true,
      scrollwheel: true,
    });
    state.tmapOverlays = [];
    state.tmapReady = true;
    setMapStatus("", false);
  } catch (err) {
    console.warn("Tmap 지도 로드 실패, SVG 스키매틱 지도로 대체합니다.", err);
    state.tmapReady = false;
    if (container) container.style.display = "none";
    if (svgEl) {
      svgEl.style.display = "block";
      renderSvgMap(
        state.lastResult || {
          origin: { lat: 37.5013, lng: 127.0396, name: "출발" },
          destination: { lat: 37.5013, lng: 127.0396, name: "목적지" },
          candidates: [],
        },
        state.publicData || { cctvs: [], child_zones: [], accident_hotspots: [] }
      );
    }
    setMapStatus(
      `티맵 지도를 불러오지 못했습니다. (${err.message || err}) SVG 지도로 표시합니다.`,
      true
    );
  }
}

// Leaflet circleMarker 대체: 카테고리 색상 원을 data-URI SVG 아이콘으로 만든다.
function tmapDotIcon(color) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18">` +
    `<circle cx="9" cy="9" r="6" fill="${color}" stroke="white" stroke-width="2"/></svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

/** 내비 앱과 같은 물방울 핀(원형 머리 + 뾰족한 끝 + 출발/도착 글자). */
function waypointPinIcon(kind) {
  const isOrigin = kind === "origin";
  const fill = isOrigin ? "#2bb673" : "#e53935";
  const label = isOrigin ? "출발" : "도착";
  // 표시 크기는 작게, viewBox는 글자가 또렷하게 보이도록 여유 있게
  const w = 30;
  const h = 40;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 40 52">` +
    `<defs>` +
    `<filter id="s" x="-20%" y="-10%" width="140%" height="140%">` +
    `<feDropShadow dx="0" dy="1" stdDeviation="1.2" flood-opacity="0.35"/>` +
    `</filter>` +
    `</defs>` +
    `<path filter="url(#s)" fill="${fill}" ` +
    `d="M20 1.5C10.06 1.5 2 9.56 2 19.5c0 12.8 15.4 29.2 17.4 31.2a0.9 0.9 0 0 0 1.2 0C22.6 48.7 38 32.3 38 19.5 38 9.56 29.94 1.5 20 1.5z"/>` +
    `<text x="20" y="23.5" text-anchor="middle" dominant-baseline="middle" ` +
    `font-size="12" font-weight="800" letter-spacing="-0.5" ` +
    `font-family="Apple SD Gothic Neo,Malgun Gothic,Pretendard,sans-serif" fill="#ffffff">${label}</text>` +
    `</svg>`;
  return {
    url: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg),
    width: w,
    height: h,
  };
}

// Tmap은 layerGroup.clearLayers()가 없으므로, 다시 그리기 전 오버레이를 직접 지운다.
function clearTmapOverlays() {
  (state.tmapOverlays || []).forEach((overlay) => overlay.setMap(null));
  state.tmapOverlays = [];
  if (state.infoWindow) {
    state.infoWindow.setMap(null);
    state.infoWindow = null;
  }
}

function renderTmapRoutes(routeData, publicData) {
  if (!state.tmap) return;
  clearTmapOverlays();
  const bounds = new Tmapv2.LatLngBounds();
  let hasPoint = false;
  const track = (overlay) => {
    state.tmapOverlays.push(overlay);
    return overlay;
  };

  const childZones = pointsNearRecommendedRoute(publicData.child_zones || [], routeData);
  const accidentHotspots = pointsNearRecommendedRoute(publicData.accident_hotspots || [], routeData);
  const guardianHouses = pointsNearRecommendedRoute(publicData.guardian_houses || [], routeData);
  const sf = safetyFacilitiesNearRoute(publicData, routeData);
  const documentPoints = documentRiskPointsForMap(publicData, routeData);

  const active = activeRoute(routeData);
  if (active && active.coordinates.length >= 2) {
    const path = active.coordinates.map((pt) => {
      const latlng = new Tmapv2.LatLng(pt.lat, pt.lng);
      bounds.extend(latlng);
      hasPoint = true;
      return latlng;
    });
    track(
      new Tmapv2.Polyline({
        path,
        strokeColor: scoreColor(active.safety_score),
        strokeWeight: 6,
        strokeStyle: "solid",
        strokeOpacity: 0.95,
        map: state.tmap,
      })
    );
  }

  function marker(pt, color, title, label) {
    const latlng = new Tmapv2.LatLng(pt.lat, pt.lng);
    bounds.extend(latlng);
    hasPoint = true;
    const options = {
      position: latlng,
      icon: tmapDotIcon(color),
      iconSize: new Tmapv2.Size(18, 18),
      map: state.tmap,
    };
    if (label) options.label = label;
    const m = track(new Tmapv2.Marker(options));
    if (title) {
      m.addListener("click", () => {
        if (state.infoWindow) state.infoWindow.setMap(null);
        state.infoWindow = new Tmapv2.InfoWindow({
          position: latlng,
          content: `<div style="padding:6px 8px;font-size:12px;max-width:220px">${title}</div>`,
          type: 2,
          border: "1px solid #888",
          map: state.tmap,
        });
      });
    }
    return m;
  }

  function waypointMarker(pt, kind, title) {
    const pin = waypointPinIcon(kind);
    const latlng = new Tmapv2.LatLng(pt.lat, pt.lng);
    bounds.extend(latlng);
    hasPoint = true;
    const m = track(
      new Tmapv2.Marker({
        position: latlng,
        icon: pin.url,
        iconSize: new Tmapv2.Size(pin.width, pin.height),
        // 핀 끝이 좌표에 닿도록 하단 중앙을 앵커로 둔다.
        offset: new Tmapv2.Point(pin.width / 2, pin.height),
        map: state.tmap,
      })
    );
    if (title) {
      m.addListener("click", () => {
        if (state.infoWindow) state.infoWindow.setMap(null);
        state.infoWindow = new Tmapv2.InfoWindow({
          position: latlng,
          content: `<div style="padding:6px 8px;font-size:12px;max-width:220px">${title}</div>`,
          type: 2,
          border: "1px solid #888",
          map: state.tmap,
        });
      });
    }
    return m;
  }

  if (shouldShowPublicLayer("cctv")) {
    childZones.forEach((z) =>
      marker(z, CATEGORY_COLORS.cctv, `${z.name || "어린이보호구역"} (CCTV ${z.cctv_count}대)`)
    );
  }
  if (shouldShowPublicLayer("safety-cctv")) sf.cctv.forEach((f) =>
    marker(f, CATEGORY_COLORS.safetyCctv, `📹 ${f.label} ${f.install_count > 1 ? `x${f.install_count}` : ""} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("safety-streetlight")) sf.streetlight.forEach((f) =>
    marker(f, CATEGORY_COLORS.safetyStreetlight, `💡 ${f.label} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("hotspot")) accidentHotspots.forEach((h) =>
    marker(h, CATEGORY_COLORS.hotspot, `${h.name || "사고다발지역"} (${h.occurrence_count}건)`)
  );
  if (shouldShowPublicLayer("guardian")) guardianHouses.forEach((g) =>
    marker(g, CATEGORY_COLORS.guardian, `🏪 ${g.name || "아동안전지킴이집"}`)
  );
  if (shouldShowPublicLayer("doc-risk")) {
    drawDocRiskOverlays(documentPoints, {
      track,
      bounds,
      onBounds: () => {
        hasPoint = true;
      },
    });
  }

  // 출발/도착: 초록·빨강 핀 아이콘
  waypointMarker(routeData.origin, "origin", routeData.origin.name || "출발");
  waypointMarker(routeData.destination, "destination", routeData.destination.name || "도착");

  if (hasPoint) {
    state.tmap.fitBounds(bounds);
  }
}

function renderMap(routeData, publicData, refreshLegend = true) {
  if (state.tmapReady) {
    setMapStatus("", false);
    document.getElementById("tmap").style.display = "block";
    document.getElementById("svg-map").style.display = "none";
    renderTmapRoutes(routeData, publicData);
  } else {
    document.getElementById("svg-map").style.display = "block";
    document.getElementById("tmap").style.display = "none";
    renderSvgMap(routeData, publicData);
    setMapStatus("", false);
  }
  if (refreshLegend) renderLegend();
}

function selectRoute(routeId, { preserveDetails = false } = {}) {
  if (!state.lastResult || !state.publicData) return;
  state.selectedRouteId = routeId;
  if (preserveDetails) {
    document.querySelectorAll("#candidates-list .candidate-card").forEach((card) => {
      const selected = card.dataset.routeId === routeId;
      card.classList.toggle("selected", selected);
      card.setAttribute("aria-pressed", String(selected));
    });
  } else {
    renderCandidates(state.lastResult);
  }
  renderReports(state.lastResult);
  renderParentReport(state.lastResult);
  renderTimeContext(state.lastResult);
  renderMap(state.lastResult, state.publicData);
}

async function handleSubmit(event) {
  event.preventDefault();
  if (!state.docReady) {
    alert("먼저 왼쪽에서 문서를 「확인」하거나 「반영 안함」을 선택해 주세요.");
    return;
  }

  const submitBtn = document.getElementById("submit-btn");
  submitBtn.disabled = true;
  submitBtn.textContent = "계산 중...";

  try {
    const originQuery = document.getElementById("origin-query").value.trim();
    const destQuery = document.getElementById("dest-query").value.trim();
    if (!originQuery || !destQuery) {
      alert("출발지와 목적지 이름을 모두 입력해주세요.");
      return;
    }

    const payload = {
      origin: { query: originQuery, name: originQuery },
      destination: { query: destQuery, name: destQuery },
    };

    const [routeData, publicData] = await Promise.all([
      fetchJson("/api/route", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
      fetchJson("/api/public-data"),
    ]);

    state.lastResult = routeData;
    state.publicData = publicData;
    state.selectedRouteId = null;
    if (state.docMode === "analyzed") state.activePublicLayer = "doc-risk";

    renderWeather(routeData.weather);
    renderTimeContext(routeData);
    renderParentReport(routeData);
    renderCandidates(routeData);
    renderReports(routeData);
    renderMap(routeData, publicData);

    if (routeData.used_mock && routeData.used_mock.routing) {
      console.warn("[경로] MOCK 모드 — Tmap 보행자 API 미사용");
    } else {
      const main = routeData.candidates.find((c) => c.source === "TMAP_PEDESTRIAN_API");
      if (main) {
        console.log(`[경로] Tmap 보행자 경로 좌표 ${main.coordinates.length}개`);
      }
    }
  } catch (err) {
    const msg = err.message || String(err);
    const friendly = msg.includes("429") || msg.includes("한도")
      ? "Tmap API 호출 한도에 걸렸습니다. 1~2분 후 다시 시도해 주세요."
      : msg.includes("503")
        ? "Tmap 보행 경로를 불러오지 못했습니다. 잠시 후 다시 시도하거나 Render 배포·TMAP_APP_KEY를 확인해 주세요."
        : msg;
    alert(`경로 계산 중 오류가 발생했습니다: ${friendly}`);
    console.error(err);
  } finally {
    const btn = document.getElementById("submit-btn");
    if (btn) btn.textContent = "안전 경로 찾기";
    syncRouteSubmitButton();
  }
}

function setDocUploadStatus(message, kind = "") {
  const el = document.getElementById("doc-upload-status");
  if (!el) return;
  el.textContent = message || "";
  el.classList.toggle("is-error", kind === "error");
  el.classList.toggle("is-ok", kind === "ok");
}

function hideDocReviewPanel() {
  const panel = document.getElementById("doc-review-panel");
  const list = document.getElementById("doc-review-list");
  if (panel) panel.hidden = true;
  if (list) list.innerHTML = "";
}

function hideDocPlacedPanel() {
  const panel = document.getElementById("doc-placed-panel");
  const list = document.getElementById("doc-placed-list");
  if (panel) panel.hidden = true;
  if (list) list.innerHTML = "";
}

function renderDocPlacedPanel(createdPoints) {
  const panel = document.getElementById("doc-placed-panel");
  const list = document.getElementById("doc-placed-list");
  if (!panel || !list) return;

  const points = Array.isArray(createdPoints) ? createdPoints : [];
  if (!points.length) {
    hideDocPlacedPanel();
    return;
  }

  list.innerHTML = "";
  points.forEach((pt) => {
    const li = document.createElement("li");
    li.className = "doc-review-item";
    const title = document.createElement("p");
    title.className = "doc-review-item-title";
    title.textContent = pt.location_text || pt.geocode_query || "구간";
    const meta = document.createElement("p");
    meta.className = "doc-review-item-meta";
    const startQ = pt.start_geocode_query || pt.geocode_query || "";
    const endQ = pt.end_geocode_query || "";
    const queryLine = endQ ? `${startQ} ~ ${endQ}` : startQ;
    const match = pt.matched_label || "";
    const matchClean = match.replace(/\s+/g, "");
    const queryClean = queryLine.replace(/\s+/g, "");
    const showMatch = match && matchClean && matchClean !== queryClean;
    meta.textContent = showMatch ? `검색어: ${queryLine} → ${match}` : `검색어: ${queryLine}`;
    li.append(title, meta);
    list.appendChild(li);
  });
  panel.hidden = false;
}

function renderDocReviewPanel(pendingPoints) {
  const panel = document.getElementById("doc-review-panel");
  const list = document.getElementById("doc-review-list");
  if (!panel || !list) return;

  const points = Array.isArray(pendingPoints) ? pendingPoints : [];
  if (!points.length) {
    hideDocReviewPanel();
    return;
  }

  list.innerHTML = "";
  points.forEach((pt, idx) => {
    const li = document.createElement("li");
    li.className = "doc-review-item";
    li.dataset.index = String(idx);

    const title = document.createElement("p");
    title.className = "doc-review-item-title";
    title.textContent = pt.location_text || pt.geocode_query || `지점 ${idx + 1}`;

    const meta = document.createElement("p");
    meta.className = "doc-review-item-meta";
    const conf =
      typeof pt.confidence === "number" ? ` · 확신 ${(pt.confidence * 100).toFixed(0)}%` : "";
    meta.textContent = `${pt.reason || "위치 확인 필요"}${conf}${pt.risk_type ? ` · ${pt.risk_type}` : ""}`;

    const label = document.createElement("label");
    label.setAttribute("for", `doc-review-query-${idx}`);
    label.textContent = "지도 검색어 (시작 또는 단일)";

    const input = document.createElement("input");
    input.type = "text";
    input.id = `doc-review-query-${idx}`;
    input.className = "doc-review-query";
    input.value = pt.start_geocode_query || pt.geocode_query || pt.location_text || "";
    input.placeholder = "예: 서울 강남구 선릉로 305";

    const endLabel = document.createElement("label");
    endLabel.setAttribute("for", `doc-review-end-${idx}`);
    endLabel.textContent = "끝 검색어 (구간일 때)";

    const endInput = document.createElement("input");
    endInput.type = "text";
    endInput.id = `doc-review-end-${idx}`;
    endInput.className = "doc-review-query";
    endInput.value = pt.end_geocode_query || "";
    endInput.placeholder = "예: 서울 강남구 역삼로 314";

    const actions = document.createElement("div");
    actions.className = "doc-review-actions";

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "doc-review-confirm";
    confirmBtn.textContent = "지도에 올리기";
    confirmBtn.addEventListener("click", () =>
      confirmPendingDocPoint(pt, input, endInput, confirmBtn, li)
    );

    const skipBtn = document.createElement("button");
    skipBtn.type = "button";
    skipBtn.className = "doc-review-skip";
    skipBtn.textContent = "건너뛰기";
    skipBtn.addEventListener("click", () => {
      li.remove();
      if (!list.children.length) hideDocReviewPanel();
    });

    actions.append(confirmBtn, skipBtn);
    li.append(title, meta, label, input, endLabel, endInput, actions);
    list.appendChild(li);
  });

  panel.hidden = false;
}

async function confirmPendingDocPoint(pt, inputEl, endInputEl, btn, itemEl) {
  const query = (inputEl?.value || "").trim();
  const endQuery = (endInputEl?.value || "").trim();
  if (!query) {
    setDocUploadStatus("검색어를 입력한 뒤 다시 시도해 주세요.", "error");
    return;
  }

  const locationText =
    endQuery && !String(pt.location_text || "").includes("~")
      ? `${query} ~ ${endQuery}`
      : pt.location_text || (endQuery ? `${query} ~ ${endQuery}` : query);

  try {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "올리는 중…";
    }
    await fetchJson("/api/documents/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        location_text: locationText,
        geocode_query: query,
        risk_type: pt.risk_type || "",
        is_risk: pt.is_risk !== false,
        snippet: pt.snippet || "",
        source_doc: pt.source_doc || "",
        page: pt.page ?? null,
        report_date: pt.report_date || null,
        recommendation: pt.recommendation || null,
      }),
    });

    itemEl?.remove();
    const list = document.getElementById("doc-review-list");
    if (list && !list.children.length) hideDocReviewPanel();

    const reran = await maybeRerunRouteAfterDocument();
    if (!reran) await refreshPublicDataAndMap({ focusDocRisk: true });
    setDocUploadStatus(`「${query}${endQuery ? ` ~ ${endQuery}` : ""}」위치를 지도에 올렸어요.`, "ok");
  } catch (err) {
    console.error(err);
    setDocUploadStatus(err.message || "위치 확인에 실패했습니다.", "error");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "지도에 올리기";
    }
  }
}

async function refreshPublicDataAndMap({ focusDocRisk = false } = {}) {
  const publicData = await fetchJson("/api/public-data");
  state.publicData = publicData;
  if (focusDocRisk) state.activePublicLayer = "doc-risk";
  if (state.lastResult) {
    renderMap(state.lastResult, publicData, true);
  } else if (focusDocRisk || state.docMode === "analyzed") {
    renderDocRiskOnlyMap(publicData);
  }
  return publicData;
}

async function maybeRerunRouteAfterDocument() {
  const originQuery = document.getElementById("origin-query")?.value?.trim();
  const destQuery = document.getElementById("dest-query")?.value?.trim();
  if (!originQuery || !destQuery || !state.lastResult) return false;

  const payload = {
    origin: { query: originQuery, name: originQuery },
    destination: { query: destQuery, name: destQuery },
  };
  const [routeData, publicData] = await Promise.all([
    fetchJson("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    fetchJson("/api/public-data"),
  ]);
  state.lastResult = routeData;
  state.publicData = publicData;
  state.activePublicLayer = "doc-risk";
  renderWeather(routeData.weather);
  if (typeof renderTimeContext === "function") renderTimeContext(routeData);
  renderParentReport(routeData);
  renderCandidates(routeData);
  renderReports(routeData);
  renderMap(routeData, publicData);
  return true;
}

function syncRouteSubmitButton() {
  const btn = document.getElementById("submit-btn");
  if (!btn) return;
  btn.disabled = !state.docReady;
  btn.title = state.docReady
    ? ""
    : "먼저 안전 문서를 확인하거나 반영 안함을 선택해 주세요.";
}

function syncDocConfirmButton() {
  const btn = document.getElementById("doc-confirm-btn");
  if (!btn) return;
  btn.disabled = state.docQueue.length === 0;
}

function renderDocQueue() {
  const list = document.getElementById("doc-queue-list");
  if (!list) return;
  list.innerHTML = "";
  state.docQueue.forEach((item) => {
    const li = document.createElement("li");
    li.className = "doc-queue-item";

    const name = document.createElement("span");
    name.className = "doc-queue-name";
    name.textContent = item.name;
    name.title = item.name;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "doc-queue-remove";
    removeBtn.textContent = "취소";
    removeBtn.addEventListener("click", () => removeDocFromQueue(item.id));

    li.append(name, removeBtn);
    list.appendChild(li);
  });
  syncDocConfirmButton();
}

function addDocsToQueue(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;

  let added = 0;
  for (const file of files) {
    if (file.size > 15 * 1024 * 1024) {
      setDocUploadStatus(`「${file.name}」은 15MB를 넘어 제외했어요.`, "error");
      continue;
    }
    const dup = state.docQueue.some(
      (q) => q.name === file.name && q.file.size === file.size
    );
    if (dup) continue;
    state.docQueueSeq += 1;
    state.docQueue.push({
      id: state.docQueueSeq,
      file,
      name: file.name,
    });
    added += 1;
  }

  if (added > 0) {
    // 새 문서를 넣으면 다시 확인이 필요함
    state.docReady = false;
    state.docMode = null;
    syncRouteSubmitButton();
    hideDocReviewPanel();
    setDocUploadStatus(
      `${state.docQueue.length}개 문서가 대기 중이에요. 「확인」을 누르면 분석을 시작해요.`,
      ""
    );
  }
  renderDocQueue();
}

function removeDocFromQueue(id) {
  state.docQueue = state.docQueue.filter((q) => q.id !== id);
  state.docReady = false;
  state.docMode = null;
  syncRouteSubmitButton();
  renderDocQueue();
  if (!state.docQueue.length) {
    setDocUploadStatus("문서를 추가하거나 「반영 안함」을 선택해 주세요.", "");
  } else {
    setDocUploadStatus(
      `${state.docQueue.length}개 문서가 대기 중이에요. 「확인」을 누르면 분석을 시작해요.`,
      ""
    );
  }
}

function skipDocumentReflection() {
  state.docQueue = [];
  state.docReady = true;
  state.docMode = "skipped";
  hideDocReviewPanel();
  renderDocQueue();
  syncRouteSubmitButton();
  setDocUploadStatus(
    "문서를 반영하지 않아요. 이제 「안전 경로 찾기」를 눌러 주세요.",
    "ok"
  );
}

async function ingestOneDocument(file) {
  const form = new FormData();
  form.append("file", file);
  const origin = document.getElementById("origin-query")?.value?.trim() || "";
  const dest = document.getElementById("dest-query")?.value?.trim() || "";
  const hint = [origin, dest].filter(Boolean).join(" / ");
  if (hint) form.append("region_hint", hint);

  const res = await fetch(`${API_BASE}/api/documents/ingest`, {
    method: "POST",
    headers: { ...authHeaders() },
    body: form,
  });
  const raw = await res.text();
  let data = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail =
      (data && (data.detail || data.message)) ||
      raw ||
      `업로드 실패 (${res.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

async function confirmDocumentQueue() {
  const confirmBtn = document.getElementById("doc-confirm-btn");
  const addBtn = document.getElementById("doc-add-btn");
  const skipBtn = document.getElementById("doc-skip-btn");
  if (!state.docQueue.length) {
    setDocUploadStatus("분석할 문서가 없어요. 문서를 추가하거나 「반영 안함」을 눌러 주세요.", "error");
    return;
  }

  const queue = [...state.docQueue];
  let totalCreated = 0;
  let allPending = [];
  let allCreated = [];
  const errors = [];

  try {
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = "분석 중…";
    }
    if (addBtn) addBtn.disabled = true;
    if (skipBtn) skipBtn.disabled = true;
    hideDocReviewPanel();
    hideDocPlacedPanel();

    for (let i = 0; i < queue.length; i += 1) {
      const item = queue[i];
      setDocUploadStatus(
        `문서 분석 중… (${i + 1}/${queue.length}) 「${item.name}」`,
        ""
      );
      try {
        const data = await ingestOneDocument(item.file);
        totalCreated += data?.risk_points_created ?? 0;
        const pending = data?.extracted?.skipped_points || [];
        const created = data?.extracted?.created_points || [];
        allPending = allPending.concat(pending);
        allCreated = allCreated.concat(created);
      } catch (err) {
        console.error(err);
        errors.push(`${item.name}: ${err.message || "실패"}`);
      }
    }

    state.docQueue = [];
    renderDocQueue();

    if (errors.length && totalCreated <= 0 && !allPending.length) {
      state.docReady = false;
      state.docMode = null;
      syncRouteSubmitButton();
      setDocUploadStatus(`분석에 실패했어요. ${errors[0]}`, "error");
      return;
    }

    state.docReady = true;
    state.docMode = "analyzed";
    syncRouteSubmitButton();
    renderDocReviewPanel(allPending);
    renderDocPlacedPanel(allCreated);

    const errHint = errors.length ? ` · 일부 실패 ${errors.length}건` : "";
    if (totalCreated > 0) {
      setDocUploadStatus(
        `이전 핀 지운 뒤 ①텍스트추출 → ②주소변환(도로명주소 우선) → ③구간 ${totalCreated}개 표시${errHint}. 검색 실패한 곳은 아래에서 수정하세요.`,
        "ok"
      );
    } else if (allPending.length > 0) {
      setDocUploadStatus(
        `①~②까지는 됐지만 ③지도 검색에 실패한 곳이 있어요. 아래 검색어를 고치면 올라가요.${errHint}`,
        ""
      );
    } else {
      setDocUploadStatus(
        `문서 분석은 끝났지만 찍을 지점이 거의 없어요${errHint}. 그래도 「안전 경로 찾기」는 가능해요.`,
        ""
      );
    }

    await refreshPublicDataAndMap({ focusDocRisk: true });
  } catch (err) {
    console.error(err);
    state.docReady = false;
    state.docMode = null;
    syncRouteSubmitButton();
    setDocUploadStatus(err.message || "문서 분석에 실패했습니다.", "error");
  } finally {
    if (confirmBtn) {
      confirmBtn.textContent = "확인 (문서 분석)";
      syncDocConfirmButton();
    }
    if (addBtn) addBtn.disabled = false;
    if (skipBtn) skipBtn.disabled = false;
  }
}

function bindDocumentUpload() {
  const addBtn = document.getElementById("doc-add-btn");
  const skipBtn = document.getElementById("doc-skip-btn");
  const confirmBtn = document.getElementById("doc-confirm-btn");
  const input = document.getElementById("doc-upload-input");

  syncRouteSubmitButton();
  syncDocConfirmButton();
  renderDocQueue();

  addBtn?.addEventListener("click", () => input?.click());
  skipBtn?.addEventListener("click", skipDocumentReflection);
  confirmBtn?.addEventListener("click", () => confirmDocumentQueue());
  input?.addEventListener("change", () => {
    if (input.files?.length) addDocsToQueue(input.files);
    input.value = "";
  });
}

function renderWeather(weather) {
  const el = document.getElementById("weather-badge");
  if (!el) return;
  if (!weather) {
    el.textContent = "";
    el.style.display = "none";
    return;
  }
  const parts = [weather.description];
  if (weather.temperature_c) parts.push(`${weather.temperature_c}°C`);
  if (weather.humidity_pct) parts.push(`습도 ${weather.humidity_pct}%`);
  if (weather.is_rain && weather.rain_mm && weather.rain_mm !== "0") parts.push(`강수 ${weather.rain_mm}mm`);
  const emoji = weather.is_rain ? "🌧️" : "🌡️";
  el.textContent = `${emoji} 목적지 날씨 · ${parts.filter(Boolean).join(" · ")}`;
  el.style.display = "inline-block";
}

function setMode(mode) {
  state.mode = mode;
  document.body.dataset.mode = mode;

  document.querySelectorAll(".mode-button").forEach((button) => {
    const active = button.dataset.mode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });

  const kidMode = mode === "kid";
  document.getElementById("route-label").textContent = kidMode
    ? "부모님이 골라준 안전한 길"
    : "부모님이 추천한 길";
  document.getElementById("mode-message").textContent = kidMode
    ? "부모님이 골라준 길을 따라 안전하게 걸어가요."
    : "안전 점수와 주변 시설을 비교해 가장 안전한 길을 골랐어요.";
  document.getElementById("guide-label").textContent = kidMode
    ? "오늘의 추천 길"
    : "안전 설명";
  document.getElementById("results-label").textContent = kidMode
    ? "오늘의 추천 길"
    : "안전한 길 비교";

  if (!kidMode && state.lastResult) {
    renderParentReport(state.lastResult);
  }
}

function setTheme(theme) {
  const isDark = theme === "dark";
  document.body.classList.toggle("theme-dark", isDark);
  const button = document.getElementById("theme-toggle");
  button.textContent = isDark ? "라이트 모드" : "다크 모드";
  button.setAttribute("aria-pressed", String(isDark));
  localStorage.setItem("kids-theme", theme);
}

function bindAppUi() {
  document.getElementById("demo-scenario-select")?.addEventListener("change", fillDemoCoordinates);
  document.getElementById("swap-locations")?.addEventListener("click", swapLocations);
  document.getElementById("route-form")?.addEventListener("submit", handleSubmit);
  bindDocumentUpload();
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    setTheme(document.body.classList.contains("theme-dark") ? "light" : "dark");
  });
  document.getElementById("candidates-list")?.addEventListener("click", (event) => {
    // 상세보기 토글은 카드 재렌더로 닫히지 않게 처리
    if (event.target.closest(".candidate-details")) {
      const card = event.target.closest(".candidate-card[data-route-id]");
      if (card) selectRoute(card.dataset.routeId, { preserveDetails: true });
      return;
    }
    const card = event.target.closest(".candidate-card[data-route-id]");
    if (card) selectRoute(card.dataset.routeId);
  });
  document.getElementById("candidates-list")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".candidate-card[data-route-id]");
    if (!card) return;
    event.preventDefault();
    selectRoute(card.dataset.routeId);
  });
  document.getElementById("kid-card-close")?.addEventListener("click", closeKidCardMode);
  document.getElementById("kid-card-share-kakao")?.addEventListener("click", () => shareKidGuide("kakao"));
  document.getElementById("kid-card-share-copy")?.addEventListener("click", () => shareKidGuide("copy"));
  document.getElementById("kid-card-prev")?.addEventListener("click", () => stepKidCard(-1));
  document.getElementById("kid-card-next")?.addEventListener("click", () => stepKidCard(1));
  startLiveClock();
  setMode(state.mode);
  setTheme(localStorage.getItem("kids-theme") || "light");
  fillDemoCoordinates();
}

async function init() {
  document.getElementById("google-login-btn")?.addEventListener("click", startGoogleLogin);
  document.getElementById("logout-btn")?.addEventListener("click", logout);

  const user = await requireAuth();
  if (!user) return;

  try {
    bindAppUi();
  } catch (err) {
    console.error("화면 연결 중 오류가 났습니다. 지도는 계속 불러옵니다.", err);
  }

  try {
    state.config = await fetchJson("/api/config");
  } catch (err) {
    console.warn("백엔드 설정을 불러오지 못했습니다. 백엔드가 실행 중인지 확인하세요.", err);
    state.config = { demo_center: { lat: 37.5013, lng: 127.0396 } };
  }

  await tryInitTmap();
  renderLegend();
}

init();
