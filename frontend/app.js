// 로컬/file://: http://127.0.0.1:8000 / 배포(Vercel 등): 같은 도메인 /api → 백엔드 프록시
function resolveApiBase() {
  if (window.API_BASE !== undefined && window.API_BASE !== null && window.API_BASE !== "") {
    return window.API_BASE;
  }
  const host = window.location.hostname;
  const isLocal =
    !host ||
    host === "localhost" ||
    host === "127.0.0.1" ||
    window.location.protocol === "file:";
  // Vercel·커스텀 도메인 모두 상대경로(/api) 사용 → vercel.json rewrite로 Render 연결
  if (!isLocal) {
    return "";
  }
  return "http://127.0.0.1:8000";
}
const API_BASE = resolveApiBase();

const CATEGORY_COLORS = {
  cctv: "#2f7dd1",
  hotspot: "#d64545",
  docRisk: "#e08a2c",
  docSafety: "#2e9e5b",
  guardian: "#8e44ad",
  streetlight: "#e0a400",
  speedCamera: "#2c3e50",
  safetyBell: "#9b59b6",
  emergency112: "#e74c3c",
  safetyCctv: "#1a6fbf",
  safetyStreetlight: "#f5b800",
};

const PUBLIC_DATA_LEGEND = [
  ["safety-cctv", "safetyCctv", "안심귀갓길 CCTV"],
  ["safety-streetlight", "safetyStreetlight", "안심귀갓길 보안등"],
  ["safety-bell", "safetyBell", "안심벨"],
  ["emergency-112", "emergency112", "112신고"],
  ["cctv", "cctv", "어린이보호구역/CCTV"],
  ["hotspot", "hotspot", "교통사고다발지역"],
  ["guardian", "guardian", "아동안전지킴이집"],
  ["streetlight", "streetlight", "보안등/가로등"],
  ["speed-camera", "speedCamera", "무인단속카메라"],
  ["doc-risk", "docRisk", "문서 기반 위험지적"],
  ["doc-safety", "docSafety", "문서 기반 안전조치완료"],
];

const DEMO_SCENARIOS = {
  morning_school: {
    origin: "대림역삼아파트",
    destination: "역삼초등학교",
    age: 8,
    note: "직선 경로는 사고다발지역 2곳과 문서상 무단횡단 위험구간을 지나 안전점수가 낮고, 큰길 우회 경로가 CCTV/보호구역 덕분에 추천됩니다.",
  },
  night_academy: {
    origin: "세모수학",
    destination: "대림역삼아파트",
    age: 11,
    note: "이 일대는 범죄위험 근사지수가 전반적으로 높은 지역이지만, 그중에서도 CCTV·보안등이 있는 경로를 골라 추천합니다.",
  },
  school_to_academy: {
    origin: "역삼초등학교",
    destination: "세모수학",
    age: 8,
    note: "학교 수업 후 학원으로 이동하는 길입니다. CCTV와 보안등이 가까운 경로를 비교해 보여줍니다.",
  },
};

const state = {
  config: null,
  lastResult: null,
  publicData: null,
  leafletReady: false,
  leafletMap: null,
  leafletLayers: null,
  mode: "parent",
  selectedRouteId: null,
  activePublicLayer: null,
  kidCardSteps: [],
  kidCardIndex: 0,
  clockTimer: null,
};

async function fetchJson(path, options) {
  const url = `${API_BASE}${path}`;
  let res;
  try {
    res = await fetch(url, options);
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
  if (score >= 45) return "#e08a2c";
  return "#d64545";
}

function routeDisplayName(routeId) {
  if (routeId.includes("direct")) return "기본 경로";
  if (routeId.endsWith("-a") || routeId.includes("grid-a")) return "우회 경로 A";
  if (routeId.endsWith("-b") || routeId.includes("grid-b")) return "우회 경로 B";
  return "안전 경로";
}

function routeDisplaySortKey(routeId) {
  if (routeId.includes("direct")) return 0;
  if (routeId.endsWith("-a") || routeId.includes("grid-a")) return 1;
  if (routeId.endsWith("-b") || routeId.includes("grid-b")) return 2;
  return 3;
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
    .filter(
      (candidate) =>
        candidate.id !== recommended.id && candidate.safety_score < recommended.safety_score
    )
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
  const text = routeData && routeData.parent_report;
  if (!text) {
    el.textContent = "경로를 찾으면 시간대 맞춤 안전 리포트가 표시됩니다.";
    el.classList.add("placeholder");
    return;
  }
  el.textContent = text;
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
      const docsHtml = c.features.matched_documents
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
      return `
        <div class="candidate-card ${isRecommended ? "recommended" : ""} ${isActive ? "selected" : ""}" data-route-id="${c.id}" role="button" tabindex="0" aria-pressed="${isActive}">
          <h4>
            <span>${routeName}${isRecommended ? '<span class="recommended-tag">★ 가장 안전한 길</span>' : ""}</span>
            <span class="score-pill" style="background:${scoreColor(c.safety_score)}">${c.safety_score}점</span>
          </h4>
          <div class="star-rating" title="안전 등급 ${c.star_rating}/3">${stars}</div>
          ${isActive ? `<div class="candidate-time">${routeTimeRange(c.duration_s)}</div>` : ""}
          <div class="candidate-meta candidate-summary">
            <span>거리: ${(c.distance_m / 1000).toFixed(2)}km</span>
            <span>예상 소요: ${Math.round(c.duration_s / 60)}분</span>
          </div>
          ${stampsHtml ? `<div class="stamps-row">${stampsHtml}</div>` : ""}
          <details class="candidate-details">
            <summary>안전 점수 자세히 보기</summary>
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
    return;
  }

  state.kidCardSteps = resolveNavigationSteps(recommended);
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
    board.innerHTML = "";
    return;
  }
  const stars = "⭐".repeat(recommended.star_rating);
  board.innerHTML = `
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
  document.getElementById("kid-card-overlay").hidden = false;
  renderKidCard(0);
}

function closeKidCardMode() {
  document.getElementById("kid-card-overlay").hidden = true;
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

  document.getElementById("kid-card-progress").textContent = `${index + 1} / ${total}`;
  document.getElementById("kid-card").classList.toggle("arrived", isArrive);
  document.getElementById("kid-card-icon").textContent = isArrive ? "🎉" : icon;
  document.getElementById("kid-card-text").textContent = isArrive ? "도착! 잘했어요" : navigationKeywordPlain(step);
  document.getElementById("kid-card-friendly").textContent = isArrive || !stepText ? "" : `👣 ${stepText} 걸어가요`;
  document.getElementById("kid-card-distance").textContent = !isArrive && step.distance_m > 0 ? `${Math.round(step.distance_m)}m` : "";
  document.getElementById("kid-card-landmark").textContent = isArrive || !landmark ? "" : `📍 ${landmark}`;
  document.getElementById("kid-card-prev").disabled = index === 0;
  document.getElementById("kid-card-next").hidden = isArrive;

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
    <span class="legend-route-help">실선(굵음) = 추천 경로, 점선 = 다른 후보</span>
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
  if (state.lastResult && state.publicData) renderMap(state.lastResult, state.publicData, false);
}

function shouldShowPublicLayer(layer) {
  return state.activePublicLayer === layer;
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
  return points.filter((point) =>
    selected.coordinates.some((coordinate) => distanceMeters(point, coordinate) <= radiusM)
  );
}

function renderSvgMap(routeData, publicData) {
  const svg = document.getElementById("svg-map");
  const size = 600;
  const padding = 40;
  svg.innerHTML = "";

  const childZones = pointsNearRecommendedRoute(publicData.child_zones || [], routeData);
  const accidentHotspots = pointsNearRecommendedRoute(publicData.accident_hotspots || [], routeData);
  const guardianHouses = pointsNearRecommendedRoute(publicData.guardian_houses || [], routeData);
  const streetlights = pointsNearRecommendedRoute(publicData.streetlights || [], routeData);
  const speedCameras = pointsNearRecommendedRoute(publicData.speed_cameras || [], routeData);
  const cctvs = pointsNearRecommendedRoute(publicData.cctvs || [], routeData);
  const sf = safetyFacilitiesNearRoute(publicData, routeData);
  const documentPoints = pointsNearRecommendedRoute(publicData.doc_risk_points || [], routeData);
  const allPoints = [];
  routeData.candidates.forEach((c) => c.coordinates.forEach((pt) => allPoints.push(pt)));
  [childZones, accidentHotspots, guardianHouses, streetlights, speedCameras, cctvs, sf.all, documentPoints]
    .forEach((points) => points.forEach((point) => allPoints.push(point)));
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

  // 경로 폴리라인
  routeData.candidates.forEach((c) => {
    const recommended = c.id === activeRouteId(routeData);
    const pts = c.coordinates.map((pt) => project(pt, bounds, size, padding));
    const path = document.createElementNS(ns, "polyline");
    path.setAttribute("points", pts.map((p) => `${p.x},${p.y}`).join(" "));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", scoreColor(c.safety_score));
    path.setAttribute("stroke-width", recommended ? 5 : 3);
    path.setAttribute("stroke-opacity", recommended ? 0.95 : 0.55);
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-dasharray", recommended ? "" : "6,5");
    svg.appendChild(path);
  });

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
    cctvs.forEach((cctv) =>
      drawMarker(cctv, CATEGORY_COLORS.cctv, "circle", `CCTV ${cctv.camera_count}대 · ${cctv.purpose || "안전"}`)
    );
  }
  if (shouldShowPublicLayer("safety-cctv")) sf.cctv.forEach((f) =>
    drawMarker(f, CATEGORY_COLORS.safetyCctv, "circle", `📹 ${f.label} ${f.install_count > 1 ? `x${f.install_count}` : ""} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("safety-streetlight")) sf.streetlight.forEach((f) =>
    drawMarker(f, CATEGORY_COLORS.safetyStreetlight, "circle", `💡 ${f.label} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("safety-bell")) sf.safetyBell.forEach((f) =>
    drawMarker(f, CATEGORY_COLORS.safetyBell, "diamond", `🔔 ${f.label} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("emergency-112")) sf.emergency112.forEach((f) =>
    drawMarker(f, CATEGORY_COLORS.emergency112, "triangle", `🚨 ${f.label} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("hotspot")) accidentHotspots.forEach((h) =>
    drawMarker(h, CATEGORY_COLORS.hotspot, "triangle", `${h.name || "사고다발지역"} (${h.occurrence_count}건)`)
  );
  if (shouldShowPublicLayer("guardian")) guardianHouses.forEach((g) =>
    drawMarker(g, CATEGORY_COLORS.guardian, "diamond", `🏪 ${g.name || "아동안전지킴이집"}`)
  );
  if (shouldShowPublicLayer("streetlight")) streetlights.forEach((s) =>
    drawMarker(s, CATEGORY_COLORS.streetlight, "circle", `💡 ${s.light_type || "보안등"}`)
  );
  if (shouldShowPublicLayer("speed-camera")) speedCameras.forEach((c) =>
    drawMarker(c, CATEGORY_COLORS.speedCamera, "square", `📷 ${c.name || "무인단속카메라"} (제한 ${c.speed_limit_kmh || "?"}km/h)`)
  );
  if (shouldShowPublicLayer("doc-risk")) documentPoints.filter((d) => d.is_risk).forEach((d) =>
    drawMarker(d, CATEGORY_COLORS.docRisk, "square", `[문서근거] ${d.risk_type} (${d.source_doc})`)
  );
  if (shouldShowPublicLayer("doc-safety")) documentPoints.filter((d) => !d.is_risk).forEach((d) =>
    drawMarker(d, CATEGORY_COLORS.docSafety, "square", `[문서근거] ${d.risk_type} (${d.source_doc})`)
  );

  // 출발/목적지 라벨
  [routeData.origin, routeData.destination].forEach((wp, idx) => {
    const p = project(wp, bounds, size, padding);
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", p.x);
    text.setAttribute("y", p.y - 12);
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("font-size", "13");
    text.setAttribute("font-weight", "700");
    text.setAttribute("fill", "#1c2733");
    text.textContent = idx === 0 ? `🏠 ${wp.name || "출발"}` : `🏫 ${wp.name || "목적지"}`;
    svg.appendChild(text);
  });
}

// ---------- Leaflet + OpenStreetMap (실제 지도, API 키 불필요) ----------

function loadLeaflet() {
  return new Promise((resolve, reject) => {
    if (window.L) return resolve();
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(link);
    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Leaflet 로드 실패 (오프라인 상태일 수 있음)"));
    document.head.appendChild(script);
  });
}

async function tryInitLeaflet() {
  try {
    await loadLeaflet();
    const container = document.getElementById("leaflet-map");
    container.style.display = "block";
    document.getElementById("svg-map").style.display = "none";
    state.leafletMap = window.L.map(container, { scrollWheelZoom: true }).setView(
      [state.config.demo_center.lat, state.config.demo_center.lng],
      16
    );
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(state.leafletMap);
    state.leafletLayers = window.L.layerGroup().addTo(state.leafletMap);
    state.leafletReady = true;
  } catch (err) {
    console.warn("Leaflet 지도 로드 실패, SVG 스키매틱 지도로 대체합니다.", err);
    state.leafletReady = false;
  }
}

function renderLeafletRoutes(routeData, publicData) {
  if (!state.leafletMap || !state.leafletLayers) return;
  const L = window.L;
  state.leafletLayers.clearLayers();
  const bounds = [];
  const childZones = pointsNearRecommendedRoute(publicData.child_zones || [], routeData);
  const accidentHotspots = pointsNearRecommendedRoute(publicData.accident_hotspots || [], routeData);
  const guardianHouses = pointsNearRecommendedRoute(publicData.guardian_houses || [], routeData);
  const streetlights = pointsNearRecommendedRoute(publicData.streetlights || [], routeData);
  const speedCameras = pointsNearRecommendedRoute(publicData.speed_cameras || [], routeData);
  const cctvs = pointsNearRecommendedRoute(publicData.cctvs || [], routeData);
  const sf = safetyFacilitiesNearRoute(publicData, routeData);
  const documentPoints = pointsNearRecommendedRoute(publicData.doc_risk_points || [], routeData);

  routeData.candidates.forEach((c) => {
    const recommended = c.id === activeRouteId(routeData);
    const latlngs = c.coordinates.map((pt) => [pt.lat, pt.lng]);
    latlngs.forEach((p) => bounds.push(p));
    L.polyline(latlngs, {
      color: scoreColor(c.safety_score),
      weight: recommended ? 6 : 3,
      opacity: recommended ? 0.95 : 0.55,
      dashArray: recommended ? null : "6,6",
    }).addTo(state.leafletLayers);
  });

  function circleMarker(pt, color, title) {
    bounds.push([pt.lat, pt.lng]);
    L.circleMarker([pt.lat, pt.lng], {
      radius: 7,
      color: "white",
      weight: 1.5,
      fillColor: color,
      fillOpacity: 0.9,
    })
      .bindTooltip(title)
      .addTo(state.leafletLayers);
  }

  function emojiMarker(pt, emoji, title) {
    bounds.push([pt.lat, pt.lng]);
    L.marker([pt.lat, pt.lng], {
      icon: L.divIcon({
        className: "safety-facility-icon",
        html: `<span aria-hidden="true">${emoji}</span>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13],
      }),
    })
      .bindTooltip(title)
      .addTo(state.leafletLayers);
  }

  if (shouldShowPublicLayer("cctv")) {
    childZones.forEach((z) =>
      circleMarker(z, CATEGORY_COLORS.cctv, `${z.name || "어린이보호구역"} (CCTV ${z.cctv_count}대)`)
    );
    cctvs.forEach((cctv) =>
      circleMarker(cctv, CATEGORY_COLORS.cctv, `CCTV ${cctv.camera_count}대 · ${cctv.purpose || "안전"} · ${cctv.address || ""}`)
    );
  }
  if (shouldShowPublicLayer("safety-cctv")) sf.cctv.forEach((f) =>
    circleMarker(f, CATEGORY_COLORS.safetyCctv, `📹 ${f.label} ${f.install_count > 1 ? `x${f.install_count}` : ""} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("safety-streetlight")) sf.streetlight.forEach((f) =>
    circleMarker(f, CATEGORY_COLORS.safetyStreetlight, `💡 ${f.label} · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("safety-bell")) sf.safetyBell.forEach((f) =>
    emojiMarker(f, "🔔", `안심벨 · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("emergency-112")) sf.emergency112.forEach((f) =>
    emojiMarker(f, "🚨", `112신고 · ${f.dong || f.district || ""}`)
  );
  if (shouldShowPublicLayer("hotspot")) accidentHotspots.forEach((h) =>
    circleMarker(h, CATEGORY_COLORS.hotspot, `${h.name || "사고다발지역"} (${h.occurrence_count}건)`)
  );
  if (shouldShowPublicLayer("guardian")) guardianHouses.forEach((g) =>
    circleMarker(g, CATEGORY_COLORS.guardian, `🏪 ${g.name || "아동안전지킴이집"}`)
  );
  if (shouldShowPublicLayer("streetlight")) streetlights.forEach((s) =>
    circleMarker(s, CATEGORY_COLORS.streetlight, `💡 ${s.light_type || "보안등"}`)
  );
  if (shouldShowPublicLayer("speed-camera")) speedCameras.forEach((c) =>
    circleMarker(c, CATEGORY_COLORS.speedCamera, `📷 ${c.name || "무인단속카메라"} (제한 ${c.speed_limit_kmh || "?"}km/h)`)
  );
  if (shouldShowPublicLayer("doc-risk")) documentPoints.filter((d) => d.is_risk).forEach((d) =>
    circleMarker(d, CATEGORY_COLORS.docRisk, `[문서근거] ${d.risk_type} (${d.source_doc})`)
  );
  if (shouldShowPublicLayer("doc-safety")) documentPoints.filter((d) => !d.is_risk).forEach((d) =>
    circleMarker(d, CATEGORY_COLORS.docSafety, `[문서근거] ${d.risk_type} (${d.source_doc})`)
  );

  function labelMarker(wp, emoji, label) {
    bounds.push([wp.lat, wp.lng]);
    L.marker([wp.lat, wp.lng], {
      icon: L.divIcon({
        className: "map-label-icon",
        html: `<span>${emoji} ${label}</span>`,
        iconSize: [0, 0],
      }),
    }).addTo(state.leafletLayers);
  }
  labelMarker(routeData.origin, "🏠", routeData.origin.name || "출발");
  labelMarker(routeData.destination, "🏫", routeData.destination.name || "목적지");

  if (bounds.length > 0) {
    state.leafletMap.fitBounds(bounds, { padding: [24, 24] });
  }
}

function renderMap(routeData, publicData, refreshLegend = true) {
  if (state.leafletReady) {
    renderLeafletRoutes(routeData, publicData);
  } else {
    document.getElementById("svg-map").style.display = "block";
    document.getElementById("leaflet-map").style.display = "none";
    renderSvgMap(routeData, publicData);
  }
  if (refreshLegend) renderLegend();
}

function selectRoute(routeId) {
  if (!state.lastResult || !state.publicData) return;
  state.selectedRouteId = routeId;
  renderCandidates(state.lastResult);
  renderReports(state.lastResult);
  renderParentReport(state.lastResult);
  renderTimeContext(state.lastResult);
  renderMap(state.lastResult, state.publicData);
}

async function handleSubmit(event) {
  event.preventDefault();
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
      // audience_age: parseInt(document.getElementById("audience-age").value, 10) || 8,
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

    console.log(
      "[경로안내] API 응답:",
      routeData.candidates.map((c) => ({
        id: c.id,
        source: c.source,
        steps: resolveNavigationSteps(c).length,
        preview: resolveNavigationSteps(c).slice(0, 3).map((s) => s.description),
      }))
    );

    renderWeather(routeData.weather);
    renderTimeContext(routeData);
    renderParentReport(routeData);
    renderCandidates(routeData);
    renderReports(routeData);
    renderMap(routeData, publicData);
  } catch (err) {
    alert(`경로 계산 중 오류가 발생했습니다: ${err.message}`);
    console.error(err);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "안전 경로 찾기";
  }
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

async function init() {
  document.getElementById("fill-demo-btn").addEventListener("click", fillDemoCoordinates);
  document.getElementById("demo-scenario-select").addEventListener("change", fillDemoCoordinates);
  document.getElementById("swap-locations").addEventListener("click", swapLocations);
  document.getElementById("route-form").addEventListener("submit", handleSubmit);
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });
  document.getElementById("theme-toggle").addEventListener("click", () => {
    setTheme(document.body.classList.contains("theme-dark") ? "light" : "dark");
  });
  document.getElementById("candidates-list").addEventListener("click", (event) => {
    const card = event.target.closest(".candidate-card[data-route-id]");
    if (card) selectRoute(card.dataset.routeId);
  });
  document.getElementById("candidates-list").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".candidate-card[data-route-id]");
    if (!card) return;
    event.preventDefault();
    selectRoute(card.dataset.routeId);
  });
  document.getElementById("kid-card-close").addEventListener("click", closeKidCardMode);
  document.getElementById("kid-card-prev").addEventListener("click", () => stepKidCard(-1));
  document.getElementById("kid-card-next").addEventListener("click", () => stepKidCard(1));
  startLiveClock();
  setMode(state.mode);
  setTheme(localStorage.getItem("kids-theme") || "light");
  fillDemoCoordinates();

  try {
    state.config = await fetchJson("/api/config");
  } catch (err) {
    console.warn("백엔드 설정을 불러오지 못했습니다. 백엔드가 실행 중인지 확인하세요.", err);
    state.config = { demo_center: { lat: 37.5013, lng: 127.0396 } };
  }

  await tryInitLeaflet();
  renderLegend();
}

init();
