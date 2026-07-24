// API_BASE는 auth.js에서 정의 (로컬 8000 / 배포 시 /api 프록시)

const CATEGORY_COLORS = {
  cctv: "#16A34A",
  hotspot: "#DC2626",
  docRisk: "#9333EA",
  docRiskEstimated: "#C084FC",
  guardian: "#DB2777",
  safetyCctv: "#0891B2",
  safetyStreetlight: "#F59E0B",
};

/** 통학 경로 전용 — 파란 실선 + 흰색 외곽선(헤일로). */
const ROUTE_LINE = {
  color: "#2563EB",
  weight: 6,
  haloColor: "#ffffff",
  haloWeight: 10,
  opacity: 1,
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
    origin: "도곡렉슬아파트",
    destination: "도곡초등학교",
    originAddr: "선릉로 221",
    destinationAddr: "선릉로64길 33",
    age: 8,
    note: "등교: 도곡렉슬아파트(선릉로 221) → 도곡초등학교(선릉로64길 33).",
  },
  school_to_academy: {
    origin: "도곡초등학교",
    destination: "게이트대치어학원",
    originAddr: "선릉로64길 33",
    destinationAddr: "도곡로 313",
    age: 8,
    note: "학원: 도곡초등학교(선릉로64길 33) → 게이트대치어학원(도곡로 313).",
  },
  night_academy: {
    origin: "게이트대치어학원",
    destination: "도곡렉슬아파트",
    originAddr: "도곡로 313",
    destinationAddr: "선릉로 221",
    age: 11,
    forceNight: true,
    note: "야간 하원: 게이트대치어학원(도곡로 313) → 도곡렉슬아파트(선릉로 221). 야간 가중치로 채점합니다.",
  },
  academy_detour: {
    origin: "깊은생각수학학원",
    destination: "도곡초등학교",
    originAddr: "도곡로 445",
    destinationAddr: "선릉로64길 33",
    age: 8,
    note: "우회: 깊은생각수학학원(도곡로 445) → 도곡초등학교(선릉로64길 33).",
  },
};

const state = {
  config: null,
  lastResult: null,
  publicData: null,
  tmapReady: false,
  tmap: null,
  tmapOverlays: [],
  lastMapFitKey: null,
  infoWindow: null,
  mode: "parent",
  selectedRouteId: null,
  activePublicLayer: null,
  kidCardSteps: [],
  kidCardIndex: 0,
  clockTimer: null,
  demoForceNight: false,
  /** "auto" | "day" | "night" — day/night는 08:00/21:00 고정으로 서버 재계산 */
  timeMode: "auto",
  // 안전 문서: 큐 → 확인(분석) 또는 반영 안함 → 경로 찾기 가능
  docQueue: [],
  docReady: false,
  docMode: null, // "analyzed" | "skipped" | null
  docQueueSeq: 0,
};

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

function setPlaceAddrHints(originAddr = "", destAddr = "") {
  const originHint = document.getElementById("origin-addr-hint");
  const destHint = document.getElementById("dest-addr-hint");
  if (originHint) {
    originHint.textContent = originAddr || "";
    originHint.hidden = !originAddr;
  }
  if (destHint) {
    destHint.textContent = destAddr || "";
    destHint.hidden = !destAddr;
  }
}

function clearPlaceAddrHints() {
  setPlaceAddrHints("", "");
}

function fillDemoCoordinates() {
  const select = document.getElementById("demo-scenario-select");
  const scenario = DEMO_SCENARIOS[select.value] || DEMO_SCENARIOS.morning_school;

  document.getElementById("origin-query").value = scenario.origin;
  document.getElementById("dest-query").value = scenario.destination;
  setPlaceAddrHints(scenario.originAddr || "", scenario.destinationAddr || "");
  syncFloatSearchFields("main");
  state.demoForceNight = Boolean(scenario.forceNight);
  if (scenario.forceNight) {
    setTimeMode("night", { rerun: false });
  }
  // 아이 나이 입력란을 다시 활성화하면 함께 복원합니다.
  // document.getElementById("audience-age").value = scenario.age;

  const hint = document.getElementById("scenario-hint");
  if (hint) hint.textContent = scenario.note;
}

function swapLocations() {
  const origin = document.getElementById("origin-query");
  const destination = document.getElementById("dest-query");
  const originHint = document.getElementById("origin-addr-hint");
  const destHint = document.getElementById("dest-addr-hint");
  [origin.value, destination.value] = [destination.value, origin.value];
  if (originHint && destHint) {
    const oText = originHint.textContent;
    const oHidden = originHint.hidden;
    originHint.textContent = destHint.textContent;
    originHint.hidden = destHint.hidden;
    destHint.textContent = oText;
    destHint.hidden = oHidden;
  }
  syncFloatSearchFields("main");
  origin.focus();
}

function syncFloatSearchFields(source = "main") {
  const origin = document.getElementById("origin-query");
  const dest = document.getElementById("dest-query");
  const floatOrigin = document.getElementById("float-origin-query");
  const floatDest = document.getElementById("float-dest-query");
  if (!origin || !dest || !floatOrigin || !floatDest) return;
  if (source === "float") {
    origin.value = floatOrigin.value;
    dest.value = floatDest.value;
  } else {
    floatOrigin.value = origin.value;
    floatDest.value = dest.value;
  }
}

function syncFloatSubmitButton() {
  const btn = document.getElementById("submit-btn");
  const floatBtn = document.getElementById("float-submit-btn");
  if (!btn || !floatBtn) return;
  floatBtn.disabled = btn.disabled;
  floatBtn.title = btn.title || "";
  floatBtn.textContent = btn.textContent || "안전 경로 찾기";
}

function scoreColor(score) {
  if (score >= 70) return "#2e9e5b";
  if (score >= 55) return "#e08a2c";
  return "#d64545";
}

/** 강남구 초등 통학로 캘리브 분위수 (점수 → 누적 %). */
const GANGNAM_SCORE_PERCENTILES = [
  [42.1, 0],
  [48.8, 10],
  [53.7, 25],
  [60.3, 50],
  [65.6, 75],
  [78.1, 90],
  [96.0, 100],
];
const GANGNAM_SCORE_MEDIAN = 60;

function scorePercentile(score) {
  const s = Number(score);
  if (!Number.isFinite(s)) return null;
  const table = GANGNAM_SCORE_PERCENTILES;
  if (s <= table[0][0]) return table[0][1];
  if (s >= table[table.length - 1][0]) return table[table.length - 1][1];
  for (let i = 0; i < table.length - 1; i++) {
    const [x0, y0] = table[i];
    const [x1, y1] = table[i + 1];
    if (s >= x0 && s <= x1) {
      const t = (s - x0) / (x1 - x0 || 1);
      return y0 + t * (y1 - y0);
    }
  }
  return null;
}

function safetyGradeInfo(score) {
  const s = Number(score);
  if (s >= 70) return { label: "안전", className: "grade-safe" };
  if (s >= 55) return { label: "보통", className: "grade-mid" };
  return { label: "주의", className: "grade-caution" };
}

function scoreBenchmarkLine(score) {
  const s = Number(score);
  if (!Number.isFinite(s)) return "";
  return `안전점수 ${s}점 · 강남 초등 통학로 중앙값 ${GANGNAM_SCORE_MEDIAN}점`;
}

function scoreTopPercentLine(score) {
  const pct = scorePercentile(score);
  if (pct == null) return "";
  const top = Math.max(0, Math.min(100, Math.round(100 - pct)));
  if (top <= 0) return "강남 통학로 최상위";
  return `강남 통학로 상위 ${top}%`;
}

function gradeBadgeHtml(score) {
  const g = safetyGradeInfo(score);
  return `<span class="grade-badge ${g.className}" title="70↑ 안전 · 55~70 보통 · 55↓ 주의">${g.label}</span>`;
}

/** 추천 vs 차순위 점수·거리 격차에 따른 정직한 비교 문구. */
function scoreGapCompareMessage(candidate, routeData) {
  if (!routeData?.candidates?.length || !candidate) return null;
  const others = routeData.candidates.filter((c) => c.id !== candidate.id);
  if (!others.length) return null;
  const bestOther = [...others].sort((a, b) => b.safety_score - a.safety_score)[0];
  const gap = Number(candidate.safety_score) - Number(bestOther.safety_score);
  if (gap >= 8) return "이 경로가 더 안전합니다.";
  if (gap >= 4) return "안전도가 약간 높습니다.";

  // 점수 비슷할 때: 실제 거리로 이유 구분 (짧은 쪽이 아닌데 "짧은 길"이라고 쓰지 않음)
  const candDist = Number(candidate.distance_m) || 0;
  const otherDist = Number(bestOther.distance_m) || 0;
  const shorterByM = otherDist - candDist; // +면 추천이 더 짧음
  if (candDist > 0 && otherDist > 0 && shorterByM >= 15) {
    return "두 경로의 안전도가 비슷합니다. 짧은 쪽을 추천합니다.";
  }
  if (gap > 0.05) {
    return "두 경로의 안전도가 비슷합니다. 조금 더 안전한 쪽을 추천합니다.";
  }
  if (candDist > 0 && otherDist > 0 && shorterByM <= -15) {
    return "두 경로의 안전도가 비슷합니다. 조금 더 안전한 쪽을 추천합니다.";
  }
  return "두 경로의 안전도가 비슷합니다.";
}

/** 추천 태그 부제 (점수 격차·거리 사실에 맞춤). */
function recommendTagForGap(gapMsg, displayCount) {
  if (displayCount < 2) {
    return '<span class="recommended-tag">추천 경로</span>';
  }
  if (gapMsg && gapMsg.includes("비슷") && gapMsg.includes("짧은")) {
    return '<span class="recommended-tag">★ 추천 (안전도 비슷 · 짧은 길)</span>';
  }
  if (gapMsg && gapMsg.includes("비슷") && gapMsg.includes("안전한")) {
    return '<span class="recommended-tag">★ 추천 (안전도 비슷 · 조금 더 안전)</span>';
  }
  if (gapMsg && gapMsg.includes("비슷")) {
    return '<span class="recommended-tag">★ 추천 (안전도 비슷)</span>';
  }
  if (gapMsg && gapMsg.includes("약간")) {
    return '<span class="recommended-tag">★ 조금 더 안전</span>';
  }
  return '<span class="recommended-tag">★ 가장 안전한 길</span>';
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 업로드 원본 문서 URL (파일명 클릭 시 열기) */
function documentFileUrl(filename) {
  const name = String(filename || "").trim();
  if (!name) return "";
  return `${API_BASE}/api/documents/files/${encodeURIComponent(name)}`;
}

function documentLinkHtml(filename, label = "") {
  const name = String(filename || "").trim();
  const text = escapeHtml(label || name || "업로드 문서");
  if (!name) return text;
  const href = escapeHtml(documentFileUrl(name));
  return `<a class="safety-doc-link" href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
}

/** 데이터에 있는 사실만으로 부모용 설명 구성 (Solar 없음, 단정·과장 금지) */
function buildGroundedWhySummary(candidate, routeData = null) {
  const features = candidate?.features || {};
  const riskDocs = (features.matched_documents || []).filter((d) => d.is_risk);
  const km = ((candidate.distance_m || 0) / 1000).toFixed(2);
  const mins = Math.max(1, Math.round((candidate.duration_s || 0) / 60));
  const isRecommended = routeData && candidate.id === routeData.recommended_id;
  const isDetour =
    String(candidate.id || "").includes("doc-avoid") ||
    String(candidate.id || "").includes("hotspot-avoid") ||
    String(candidate.id || "").includes("avoid-");

  const ansimCctv = features.safety_facility_cctv_count || 0;
  const zoneCctv = features.cctv_count || 0;
  const totalCctv = ansimCctv + zoneCctv;
  const ansimLight = features.safety_facility_streetlight_count || 0;
  const zonePct = features.child_zone_coverage_pct || 0;
  const guardian = features.guardian_house_count || 0;
  const hotspot = features.accident_hotspot_count || 0;
  const cameras = features.speed_camera_count || 0;
  const bells = features.safety_bell_count || 0;
  const docCount = features.doc_risk_count || riskDocs.length || 0;

  // 부모에게 "그래서 뭐가 좋은지"가 보이게 — 수치는 반드시 포함
  const goodPoints = [];
  if (zonePct > 0) {
    goodPoints.push(
      `스쿨존(어린이보호구역)을 ${zonePct}% 지납니다. 이 구간은 차량 속도가 제한됩니다.`
    );
  }
  if (totalCctv > 0) {
    goodPoints.push(
      `CCTV가 ${totalCctv}대 있습니다` +
        (ansimCctv > 0 || zoneCctv > 0
          ? ` (안심귀갓길 ${ansimCctv}대, 보호구역 ${zoneCctv}대). 아이 주변을 지켜보는 시설이 있습니다.`
          : `.`)
    );
  }
  if (ansimLight > 0) {
    goodPoints.push(
      `안심귀갓길 보안등이 ${ansimLight}개입니다. 어두운 시간대에 도움이 됩니다.`
    );
  }
  if (guardian > 0) {
    goodPoints.push(
      `아동안전지킴이집이 ${guardian}곳 있습니다. 아이가 위급할 때 가까운 가게·시설에 도움을 요청하도록 미리 알려 줄 수 있습니다.`
    );
  }
  if (cameras > 0) {
    goodPoints.push(`무인 단속카메라가 ${cameras}곳 있어 과속 단속이 이뤄지는 구간이 있습니다.`);
  }
  if (bells > 0) {
    goodPoints.push(`안심벨이 ${bells}개 있습니다. 아이가 혼자 다닐 때 쓸 수 있다고 알려 두면 좋습니다.`);
  }

  const watchPoints = [];
  if (hotspot > 0) {
    watchPoints.push(
      `사고다발지역이 ${hotspot}곳 경로 근처에 있습니다. 아이에게 그 구간에서는 뛰지 말고, 횡단보도에서 좌우를 꼭 보라고 말해 주세요.`
    );
  }
  if (docCount > 0) {
    if (riskDocs.length) {
      const byDoc = new Map();
      for (const d of riskDocs) {
        const key = d.source_doc || "업로드 문서";
        if (!byDoc.has(key)) byDoc.set(key, d);
      }
      for (const [src, first] of byDoc) {
        const kind = first.risk_type || "주의 구간";
        const link = documentLinkHtml(src);
        watchPoints.push({
          text: `올린 문서(${src})에 「${kind}」이 있습니다. 지도의 빨간 구간을 피한 우회 경로로 바꿔 아이에게 보내 주세요.`,
          html:
            `올린 문서(${link})에 「${escapeHtml(kind)}」이 있습니다. ` +
            `지도의 빨간 구간을 피한 우회 경로로 바꿔 아이에게 보내 주세요.`,
        });
      }
    } else {
      watchPoints.push(
        `문서에서 찾은 위험 지점이 ${docCount}곳 있습니다. 지도 표시를 확인한 뒤, 안전한 후보로 길을 정해 주세요.`
      );
    }
  }
  if (routeData?.weather?.is_rain) {
    watchPoints.push(
      `지금 목적지 날씨는 ${routeData.weather.description || "비"}입니다. 바닥이 미끄러울 수 있으니 아이에게 천천히 가라고 말해 주세요.`
    );
  }

  // 첫 문단: "왜 이 길인지" — 부모가 아이 혼자 갈 길을 고를 때
  const title = isRecommended ? "추천하는 이유" : isDetour ? "우회 경로인 이유" : "이 경로 요약";
  let paragraphs = [];

  const gapMsg = isRecommended ? scoreGapCompareMessage(candidate, routeData) : null;
  const multiCandidate = (routeData?.candidates?.length || 0) > 1;
  if (gapMsg) {
    paragraphs.push(
      `${gapMsg} 약 ${km}km · ${mins}분, 안전점수 ${candidate.safety_score}점입니다.`
    );
  } else if (isDetour && (hotspot > 0 || docCount > 0)) {
    paragraphs.push(
      `위험·공사 구간을 피해 아이가 혼자 가도록 잡은 길입니다. 거리는 약 ${km}km, ${mins}분 정도입니다. (안전점수 ${candidate.safety_score}점)`
    );
  } else if (!multiCandidate) {
    paragraphs.push(
      `이 경로의 안전 요소를 정리했습니다. 약 ${km}km · ${mins}분, 안전점수 ${candidate.safety_score}점입니다.`
    );
  } else if (goodPoints.length >= 2) {
    paragraphs.push(
      `아이가 혼자 다닐 때 주변 시설이 더 많은 쪽을 골랐습니다. 약 ${km}km · ${mins}분, 안전점수 ${candidate.safety_score}점입니다.`
    );
  } else if (goodPoints.length === 1) {
    paragraphs.push(
      `아이가 혼자 걸을 때 약 ${km}km · ${mins}분 걸리는 길입니다. (안전점수 ${candidate.safety_score}점) 아래 ‘도움이 되는 점’을 확인해 주세요.`
    );
  } else {
    paragraphs.push(
      `약 ${km}km · ${mins}분, 안전점수 ${candidate.safety_score}점입니다. 시설 수치가 많지 않으니 ‘확인할 점’을 보고 길을 정해 주세요.`
    );
  }

  if (watchPoints.length && goodPoints.length) {
    paragraphs.push(
      `좋은 점이 있어도 주의할 구간이 있습니다. 아래를 읽고, 출발 전에 아이에게 어디에 조심하라고 말해 주세요.`
    );
  } else if (watchPoints.length) {
    paragraphs.push(`아래 ‘확인할 점’을 본 뒤 길을 정하고, 아이에게 미리 알려 주세요.`);
  } else if (goodPoints.length) {
    paragraphs.push(
      `특별히 표시된 큰 위험은 거의 없습니다. 그래도 아이에게 횡단보도에서는 좌우를 확인하라고 말해 주세요.`
    );
  }

  return { title, paragraphs, goodPoints, watchPoints };
}

/** 부모용 안전 리포트 모델 */
function parseSolarParentReport(raw) {
  if (!raw || typeof raw !== "string") return null;
  let text = raw.trim();
  if (!text) return null;
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) text = fence[1].trim();
  const tryParse = (s) => {
    try {
      const obj = JSON.parse(s);
      if (obj && typeof obj.summary === "string") {
        return {
          summary: String(obj.summary || "").trim(),
          good_points: Array.isArray(obj.good_points)
            ? obj.good_points.map((x) => String(x).trim()).filter(Boolean).slice(0, 4)
            : [],
          caution_points: Array.isArray(obj.caution_points)
            ? obj.caution_points.map((x) => String(x).trim()).filter(Boolean)
            : [],
          night_note: String(obj.night_note || "").trim(),
        };
      }
    } catch {
      return null;
    }
    return null;
  };
  const direct = tryParse(text);
  if (direct) return direct;
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start >= 0 && end > start) return tryParse(text.slice(start, end + 1));
  return null;
}

function buildParentSafetyModel(candidate, routeData = null) {
  const features = candidate?.features || {};
  const weather = routeData?.weather || null;
  const riskDocs = (features.matched_documents || []).filter((d) => d.is_risk);
  const km = ((candidate.distance_m || 0) / 1000).toFixed(2);
  const mins = Math.max(1, Math.round((candidate.duration_s || 0) / 60));
  const isRecommended = routeData && candidate.id === routeData.recommended_id;
  const isDetour =
    String(candidate.id || "").includes("doc-avoid") ||
    String(candidate.id || "").includes("hotspot-avoid") ||
    String(candidate.id || "").includes("avoid-");

  const why = buildGroundedWhySummary(candidate, routeData);
  // Solar 문장은 추천 경로 기준으로만 생성됨 — 다른 후보 선택 시 해당 후보 수치로 재구성
  const solarForThis =
    routeData && candidate.id === routeData.recommended_id
      ? routeData.solarParent || parseSolarParentReport(routeData.parent_report)
      : null;
  const solar = solarForThis;

  const safeFacilityDefs = [
    { label: "안심귀갓길 CCTV", count: features.safety_facility_cctv_count || 0, unit: "대" },
    { label: "어린이보호구역 CCTV", count: features.cctv_count || 0, unit: "대" },
    { label: "안심귀갓길 보안등", count: features.safety_facility_streetlight_count || 0, unit: "개" },
    { label: "안심벨", count: features.safety_bell_count || 0, unit: "개" },
    { label: "112 신고장치", count: features.emergency112_count || 0, unit: "개" },
    { label: "어린이보호구역 통과", count: Number(features.child_zone_coverage_pct) || 0, unit: "%" },
    { label: "아동안전지킴이집", count: features.guardian_house_count || 0, unit: "곳" },
    { label: "무인 단속카메라", count: features.speed_camera_count || 0, unit: "곳" },
  ];
  const safeRows = safeFacilityDefs
    .filter((d) => d.count > 0)
    .map((d) => ({
      label: d.label,
      value: d.unit === "%" ? `${d.count}%` : `${d.count}${d.unit}`,
    }));
  const absentFacilityLabels = safeFacilityDefs.filter((d) => d.count <= 0).map((d) => d.label);

  const cautionRows = [
    { label: "사고다발지역", value: `${features.accident_hotspot_count || 0}곳` },
    { label: "문서 위험 지점", value: `${features.doc_risk_count || riskDocs.length || 0}곳` },
  ];
  if (riskDocs.length) {
    const byDoc = new Map();
    for (const d of riskDocs) {
      const key = d.source_doc || "업로드 문서";
      if (!byDoc.has(key)) byDoc.set(key, d);
    }
    for (const [src, first] of byDoc) {
      const kind = first.risk_type || "주의";
      cautionRows.push({
        label: "문서",
        value: `${kind} · ${src}`,
        html: `${escapeHtml(kind)} · ${documentLinkHtml(src)}`,
      });
    }
  }
  if (weather?.is_rain) {
    cautionRows.push({ label: "날씨", value: weather.description || "비" });
  }

  let routeTag = "선택 경로";
  if (isRecommended) routeTag = "추천 경로";
  else if (isDetour) routeTag = "우회 경로";

  const paragraphs = solar?.summary
    ? [solar.summary, solar.night_note].filter(Boolean)
    : why.paragraphs;
  const goodPoints = solar ? solar.good_points || [] : why.goodPoints;
  const watchPoints = solar ? solar.caution_points || [] : why.watchPoints;

  return {
    routeTag,
    score: candidate.safety_score,
    distance: `${km}km`,
    duration: `${mins}분`,
    stars: candidate.star_rating || 0,
    whyTitle: why.title,
    paragraphs,
    whySummary: paragraphs.join(" "),
    goodPoints,
    watchPoints,
    safeRows,
    absentFacilityLabels,
    cautionRows,
  };
}

function renderSafetyRows(rows) {
  return rows
    .map(
      (row) => `
      <tr>
        <th scope="row">${escapeHtml(row.label)}</th>
        <td>${row.html || escapeHtml(row.value)}</td>
      </tr>`
    )
    .join("");
}

function renderFacilityTableBody(presentRows, absentLabels) {
  let html = renderSafetyRows(presentRows || []);
  if (absentLabels?.length) {
    html += `
      <tr class="safety-absent-sep">
        <td colspan="2">─ 이 경로에 없는 시설 ─</td>
      </tr>
      <tr class="safety-absent-list">
        <td colspan="2">${escapeHtml(absentLabels.join(", "))}</td>
      </tr>`;
  }
  return html;
}

function renderBulletList(items, emptyText) {
  if (!items?.length) {
    return `<p class="safety-empty">${escapeHtml(emptyText)}</p>`;
  }
  return `<ul class="safety-bullets">${items
    .map((t) => {
      if (t && typeof t === "object" && t.html) {
        return `<li>${t.html}</li>`;
      }
      return `<li>${escapeHtml(t)}</li>`;
    })
    .join("")}</ul>`;
}

function renderParentSafetyHtml(model) {
  if (!model) return "";
  const paras = (model.paragraphs || [model.whySummary])
    .filter(Boolean)
    .map((p) => `<p class="safety-lead">${escapeHtml(p)}</p>`)
    .join("");

  return `
    <div class="safety-brief">
      <header class="safety-head">
        <p class="safety-kicker">${escapeHtml(model.routeTag)}</p>
        <h4 class="safety-title">${escapeHtml(model.whyTitle || "왜 이 길인가요?")}</h4>
        <p class="safety-meta">
          ${gradeBadgeHtml(model.score)}
          <strong>${escapeHtml(scoreBenchmarkLine(model.score))}</strong>
          <span aria-hidden="true">·</span> ${escapeHtml(scoreTopPercentLine(model.score))}
          <span aria-hidden="true">·</span> ${escapeHtml(model.distance)}
          <span aria-hidden="true">·</span> 약 ${escapeHtml(model.duration)}
        </p>
      </header>

      <div class="safety-lead-block">${paras}</div>

      <section class="safety-block" aria-labelledby="safety-good-label">
        <h5 id="safety-good-label" class="safety-block-title">도움이 되는 점</h5>
        ${renderBulletList(model.goodPoints, "표시할 안전 시설 수치가 거의 없습니다.")}
      </section>

      <section class="safety-block is-caution" aria-labelledby="safety-watch-label">
        <h5 id="safety-watch-label" class="safety-block-title">확인할 점 (아이에게 미리 말해 줄 것)</h5>
        ${renderBulletList(
          model.watchPoints,
          "특별히 표시된 주의 구간은 없습니다. 아이에게 횡단보도에서는 좌우를 확인하라고 말해 주세요."
        )}
      </section>

      <details class="safety-more">
        <summary>시설·주의 수치 표</summary>
        <div class="safety-tables">
          <table class="safety-table">
            <caption>경로 주변 안전 시설</caption>
            <tbody>${renderFacilityTableBody(model.safeRows, model.absentFacilityLabels)}</tbody>
          </table>
          <table class="safety-table">
            <caption>주의 수치</caption>
            <tbody>${renderSafetyRows(model.cautionRows)}</tbody>
          </table>
        </div>
      </details>
    </div>`;
}

function scoreExplanation(candidate, routeData = null) {
  const why = buildGroundedWhySummary(candidate, routeData);
  return why.paragraphs.join(" ");
}

function buildSelectedRouteSafetyText(candidate, routeData) {
  if (!candidate) return "";
  const model = buildParentSafetyModel(candidate, routeData);
  return [
    `${model.whyTitle} (${model.routeTag})`,
    `안전 ${model.score}점 (${scoreBenchmarkLine(model.score)} · ${scoreTopPercentLine(model.score)} · ${safetyGradeInfo(model.score).label}) · ${model.distance} · ${model.duration}`,
    "",
    ...model.paragraphs,
    "",
    "도움이 되는 점",
    ...(model.goodPoints.length ? model.goodPoints.map((g) => `- ${g}`) : ["- 없음"]),
    "",
    "확인할 점",
    ...(model.watchPoints.length
      ? model.watchPoints.map((g) => `- ${typeof g === "object" ? g.text || "" : g}`)
      : ["- 없음"]),
  ].join("\n");
}

function isDetourRouteId(routeId) {
  const id = String(routeId || "").toLowerCase();
  return id.includes("avoid") || id.includes("via") || id.includes("detour");
}

function isBaseRouteId(routeId) {
  const id = String(routeId || "").toLowerCase();
  return (id.includes("main") || id.includes("direct")) && !isDetourRouteId(id);
}

function routeDisplayName(routeId, candidate = null) {
  if (candidate?.display_label) return candidate.display_label;
  if (isDetourRouteId(routeId)) return "안전 우회";
  if (isBaseRouteId(routeId)) return "기본 경로";
  if (routeId.includes("seolleung-sidewalk") || routeId.includes("sidewalk")) return "선릉로 보도 경로";
  if (routeId.includes("opt0") || routeId.includes("opt4") || routeId.includes("opt10") || routeId.includes("pedestrian-alt")) {
    return "다른 경로";
  }
  if (routeId.endsWith("-a") || routeId.includes("grid-a")) return "안전 우회";
  if (routeId.endsWith("-b") || routeId.includes("grid-b")) return "안전 우회";
  return "보행자 경로";
}

function detourCompareNote(candidate, routeData) {
  if (!isDetourRouteId(candidate?.id) || !routeData?.candidates?.length) return "";
  const base =
    routeData.candidates.find((c) => isBaseRouteId(c.id)) ||
    routeData.candidates.find((c) => !isDetourRouteId(c.id));
  if (!base) return "";
  const parts = [];
  const baseHot = base.features?.accident_hotspot_count || 0;
  const detHot = candidate.features?.accident_hotspot_count || 0;
  const avoidedHot = Math.max(0, baseHot - detHot);
  if (avoidedHot > 0) parts.push(`교통사고다발지역 ${avoidedHot}곳 회피`);
  const baseDoc = base.features?.doc_risk_count || 0;
  const detDoc = candidate.features?.doc_risk_count || 0;
  const avoidedDoc = Math.max(0, baseDoc - detDoc);
  if (avoidedDoc > 0) parts.push(`문서 위험 ${avoidedDoc}곳 회피`);
  const extra = Math.max(0, Math.round((candidate.distance_m || 0) - (base.distance_m || 0)));
  if (extra > 0) parts.push(`${extra}m 더 걸음`);
  return parts.join(" · ");
}

function routeDisplaySortKey(routeId) {
  if (routeId.includes("seolleung-sidewalk") || routeId.includes("sidewalk")) return 0;
  if (isBaseRouteId(routeId) || routeId.includes("pedestrian-main") || routeId.includes("direct")) return 0;
  if (routeId.includes("opt0")) return 1;
  if (routeId.includes("opt4") || routeId.includes("pedestrian-alt")) return 2;
  if (routeId.includes("opt10")) return 3;
  if (isDetourRouteId(routeId)) return 4;
  if (routeId.endsWith("-a") || routeId.includes("grid-a")) return 5;
  if (routeId.endsWith("-b") || routeId.includes("grid-b")) return 6;
  return 7;
}

function isDuplicateRouteCard(first, second) {
  // 기본 vs 우회는 거리가 비슷해도 별도 카드로 유지
  if (isDetourRouteId(first.id) !== isDetourRouteId(second.id)) return false;
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

  // 점수순 (추천이 최상단이 되도록 동점이면 추천 우선)
  const ordered = [...uniqueCandidates].sort((first, second) => {
    if (first.id === recommended.id) return -1;
    if (second.id === recommended.id) return 1;
    return (
      second.safety_score - first.safety_score ||
      routeDisplaySortKey(first.id) - routeDisplaySortKey(second.id)
    );
  });
  return ordered;
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
  if (isArrive) return "아이에게 이 길 안내 링크를 보내 주세요";

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

function resetProgressStamps() {}

function updateKidProgressSummaryOnBoard() {
  const board = document.getElementById("kid-stamp-board");
  if (!board) return;
  board.querySelector(".kid-progress-summary")?.remove();
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
    streetlight: f.safety_facility_streetlight_count || 0,
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

function departureBaseDate(routeData) {
  const iso = routeData?.time_context?.current_time_iso;
  if (iso) {
    const d = new Date(iso);
    if (!Number.isNaN(d.getTime())) return d;
  }
  return new Date();
}

function etaMessageForDuration(durationS, routeData = null) {
  if (!durationS || durationS <= 0) return "";
  const departure = departureBaseDate(routeData);
  const arrival = new Date(departure.getTime() + durationS * 1000);
  if (routeData?.time_context?.is_time_fixed) {
    return `${formatKoreanTime(departure)} 출발 → ${formatKoreanTime(arrival)} 도착`;
  }
  return `지금 출발하면 약 ${formatKoreanTime(arrival)} 도착`;
}

function routeTimeRange(durationS, routeData = null) {
  if (!durationS || durationS <= 0) return "";
  const departure = departureBaseDate(routeData);
  const arrival = new Date(departure.getTime() + durationS * 1000);
  return `${formatKoreanTime(departure)} 출발 → ${formatKoreanTime(arrival)} 도착`;
}

function updateEtaForSelectedRoute(routeData) {
  const selected = activeRoute(routeData);
  const eta = document.getElementById("time-eta");
  if (!selected || !eta) return;
  const fromApi = routeData?.time_context?.eta_message;
  // 추천 경로와 동일 길이면 API 문구 우선, 후보 변경 시 고정 시각 기준으로 재계산
  const recommended = routeData?.candidates?.find((c) => c.id === routeData.recommended_id);
  const sameAsRecommended =
    recommended && Math.abs((selected.duration_s || 0) - (recommended.duration_s || 0)) < 0.5;
  const msg =
    sameAsRecommended && fromApi ? fromApi : etaMessageForDuration(selected.duration_s, routeData);
  eta.textContent = msg ? ` · ${msg}` : "";
}

function renderTimeContext(routeData) {
  const banner = document.getElementById("time-banner");
  const icon = document.getElementById("time-banner-icon");
  const rec = document.getElementById("time-recommendation");
  const fixedLabel = document.getElementById("time-fixed-label");
  const tc = routeData && routeData.time_context;
  if (!banner || !tc) {
    if (banner) banner.hidden = true;
    return;
  }

  banner.hidden = false;
  banner.classList.toggle("night", tc.is_night);
  if (icon) icon.textContent = tc.period_emoji || (tc.is_night ? "🌙" : "☀️");
  if (rec) rec.textContent = tc.recommendation_message || "";
  if (fixedLabel) {
    // 낮·밤 수동 선택일 때만 "○ 기준으로 보는 중" 표시 (자동은 실제 시각이라 생략)
    const basisLabel =
      state.timeMode === "day" || state.timeMode === "night"
        ? (tc.fixed_time_label ||
            (tc.is_night || state.timeMode === "night"
              ? "밤 기준으로 보는 중"
              : "낮 기준으로 보는 중")).trim()
        : "";
    if (basisLabel) {
      fixedLabel.hidden = false;
      fixedLabel.textContent = basisLabel;
      fixedLabel.style.display = "";
    } else {
      fixedLabel.hidden = true;
      fixedLabel.textContent = "";
      fixedLabel.style.display = "none";
    }
  }
  updateEtaForSelectedRoute(routeData);

  const modeMsg = document.getElementById("mode-message");
  if (modeMsg && tc.recommendation_message) {
    modeMsg.textContent = tc.recommendation_message;
  }
}

function syncTimeModeButtons() {
  document.querySelectorAll("[data-time-mode]").forEach((btn) => {
    const active = btn.dataset.timeMode === state.timeMode;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", String(active));
  });
}

function applyTimeModeToPayload(payload) {
  if (state.timeMode === "day" || state.timeMode === "night") {
    payload.time_mode = state.timeMode;
  }
  // auto: time_mode/force_night 생략 → 서버 기본(실제 시각)과 동일
}

async function setTimeMode(mode, { rerun = true } = {}) {
  const next = mode === "day" || mode === "night" ? mode : "auto";
  if (state.timeMode === next) {
    syncTimeModeButtons();
    return;
  }
  state.timeMode = next;
  if (next !== "night") state.demoForceNight = false;
  syncTimeModeButtons();

  if (!rerun) return;
  if (!state.docReady || !state.lastResult) return;
  const originQuery = document.getElementById("origin-query")?.value?.trim();
  const destQuery = document.getElementById("dest-query")?.value?.trim();
  if (!originQuery || !destQuery) return;

  const submitBtn = document.getElementById("submit-btn");
  const prevText = submitBtn?.textContent;
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "시간대 재계산 중...";
  }
  try {
    await fetchAndRenderRoute({ originQuery, destQuery });
  } catch (err) {
    console.error(err);
    alert(err.message || "시간대 재계산에 실패했습니다.");
  } finally {
    if (submitBtn) {
      submitBtn.disabled = !state.docReady;
      submitBtn.textContent = prevText || "안전 경로 찾기";
    }
    syncFloatSubmitButton();
  }
}

function setRouteProgress(message) {
  const btn = document.getElementById("submit-btn");
  // 버튼 문구는 「안전 경로 찾기」 유지 — 진행 멘트는 버튼 아래에만 표시
  if (btn) btn.textContent = "안전 경로 찾기";
  const el = document.getElementById("route-progress");
  if (el) {
    el.textContent = message || "";
    el.hidden = !message;
  }
  syncFloatSubmitButton();
}

function clearRouteProgressTimers(timers) {
  (timers || []).forEach((id) => clearTimeout(id));
}

function setParentReportPending() {
  const el = document.getElementById("parent-report");
  if (!el) return;
  el.className = "ai-text placeholder pending";
  el.textContent = "안전 리포트를 작성하고 있어요";
}

async function pollRouteReports(resultKey, { maxWaitMs = 90_000, intervalMs = 800 } = {}) {
  if (!resultKey) return null;
  const started = Date.now();
  while (Date.now() - started < maxWaitMs) {
    try {
      const data = await fetchJson(`/api/route/reports/${encodeURIComponent(resultKey)}`);
      if (data && data.status === "ready") return data;
    } catch (err) {
      console.warn("[리포트]", err.message || err);
      return null;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return null;
}

async function fillReportsAfterRoute(routeData) {
  setParentReportPending();
  const key = routeData?.result_key;
  const reportsPromise =
    routeData?.reports_status === "ready" && routeData?.parent_report
      ? Promise.resolve({
          status: "ready",
          parent_report: routeData.parent_report,
          kid_report: routeData.kid_report,
        })
      : pollRouteReports(key);

  const reports = await reportsPromise;
  if (reports?.status === "ready") {
    routeData.parent_report = reports.parent_report || routeData.parent_report || "";
    routeData.parent_report_v2 = reports.parent_report_v2 || "";
    routeData.kid_report = reports.kid_report || "";
    routeData.reports_status = "ready";
    routeData.solarParent = parseSolarParentReport(routeData.parent_report);
    if (state.lastResult?.result_key === key) {
      state.lastResult.parent_report = routeData.parent_report;
      state.lastResult.kid_report = routeData.kid_report;
      state.lastResult.reports_status = "ready";
      state.lastResult.solarParent = routeData.solarParent;
    }
  }
  renderParentReport(routeData);
}

async function fetchAndRenderRoute({ originQuery, destQuery, progressTimers = [] }) {
  const payload = {
    origin: { query: originQuery, name: originQuery },
    destination: { query: destQuery, name: destQuery },
  };
  applyTimeModeToPayload(payload);

  setRouteProgress("경로를 찾고 있어요");
  progressTimers.push(
    setTimeout(() => setRouteProgress("안전 시설을 확인하고 있어요"), 2200)
  );

  const [routeData, publicData] = await Promise.all([
    fetchJson("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    fetchJson("/api/public-data"),
  ]);

  clearRouteProgressTimers(progressTimers);
  setRouteProgress("안전 리포트를 작성하고 있어요");

  state.lastResult = routeData;
  state.publicData = publicData;
  state.selectedRouteId = null;

  renderWeather(routeData.weather);
  renderTimeContext(routeData);
  renderCandidates(routeData);
  renderReports(routeData);
  renderMap(routeData, publicData);
  setParentReportPending();

  // 리포트는 논블로킹 — 지도·점수는 이미 표시됨
  fillReportsAfterRoute(routeData).catch((err) => console.warn("[리포트]", err));

  setRouteProgress("");
  return routeData;
}


function renderParentReport(routeData) {
  const el = document.getElementById("parent-report");
  if (!el) return;
  const selected = activeRoute(routeData);
  if (!selected) {
    el.className = "ai-text placeholder";
    el.textContent =
      "경로를 고르면, 아이가 혼자 가도 괜찮은지와 미리 말해 줄 주의점을 여기에 보여 줍니다.";
    return;
  }
  const model = buildParentSafetyModel(selected, routeData);
  el.className = "ai-text safety-report";
  el.innerHTML = renderParentSafetyHtml(model);
}

function startLiveClock() {
  updateLiveClock();
  if (state.clockTimer) clearInterval(state.clockTimer);
  state.clockTimer = setInterval(updateLiveClock, 30_000);
}

function renderCandidates(data) {
  const el = document.getElementById("candidates-list");
  const displayCandidates = candidatesForDisplay(data);
  const cardsHtml = displayCandidates
    .map((c) => {
      const isRecommended = c.id === data.recommended_id || c.id === displayCandidates[0]?.id;
      const isActive = c.id === activeRouteId(data);
      const isDetour = isDetourRouteId(c.id);
      const routeName = routeDisplayName(c.id, c);
      const gapMsg = isRecommended ? scoreGapCompareMessage(c, data) : null;
      let recommendTag = "";
      if (isRecommended) {
        recommendTag = recommendTagForGap(gapMsg, displayCandidates.length);
      }
      const docsHtml = (c.features.matched_documents || [])
        .map((d) => {
          const src = d.source_doc || "";
          const srcHtml = src ? documentLinkHtml(src) : escapeHtml("문서");
          return `<div class="doc-evidence">${d.is_risk ? "⚠️" : "✅"} <strong>${escapeHtml(
            d.risk_type
          )}</strong> (${srcHtml}, 경로에서 ${Math.round(d.distance_m)}m) — "${escapeHtml(
            d.snippet
          )}"</div>`;
        })
        .join("");
      const stampsHtml = (c.stamps || [])
        .map(
          (s) =>
            `<span class="stamp-chip" title="${s.description}">${s.emoji} ${s.label}${s.count > 1 ? ` x${s.count}` : ""}</span>`
        )
        .join("");
      const topLine = scoreTopPercentLine(c.safety_score);
      const detourNote = isDetour ? detourCompareNote(c, data) : "";
      const timeRange = routeTimeRange(c.duration_s, data);
      return `
        <div class="candidate-card ${isRecommended ? "recommended" : ""} ${isActive ? "selected" : ""}" data-route-id="${c.id}" role="button" tabindex="0" aria-pressed="${isActive}">
          <h4>
            <span class="candidate-title-block">
              <span class="candidate-route-name">${escapeHtml(routeName)}</span>
              ${recommendTag}
            </span>
            <span class="score-pill-wrap">
              ${gradeBadgeHtml(c.safety_score)}
              <span class="score-pill" style="background:${scoreColor(c.safety_score)}">${c.safety_score}점</span>
            </span>
          </h4>
          <div class="score-benchmark">${escapeHtml(scoreBenchmarkLine(c.safety_score))}</div>
          ${topLine ? `<div class="score-percentile">${escapeHtml(topLine)}</div>` : ""}
          ${detourNote ? `<div class="detour-compare-note">${escapeHtml(detourNote)}</div>` : ""}
          ${gapMsg && isRecommended ? `<div class="score-gap-note">${gapMsg}</div>` : ""}
          ${timeRange ? `<div class="candidate-time">${timeRange}</div>` : ""}
          <div class="candidate-meta candidate-summary">
            <span>거리: ${(c.distance_m / 1000).toFixed(2)}km</span>
            <span>예상 소요: ${Math.round(c.duration_s / 60)}분</span>
          </div>
          ${c.access_warning ? `<div class="access-warning" role="status">${c.access_warning}</div>` : ""}
          ${stampsHtml ? `<div class="stamps-row">${stampsHtml}</div>` : ""}
          ${
            docsHtml
              ? `<details class="candidate-details"><summary>문서 근거</summary>${docsHtml}</details>`
              : `<p class="candidate-report-hint">선택하면 아래 「안전 리포트」에 근거가 표시됩니다.</p>`
          }
        </div>`;
    })
    .join("");

  const compareNote =
    displayCandidates.length === 1
      ? data.compare_note || "이 구간은 안전한 대안 경로가 없어 1개만 표시합니다."
      : "";
  const noteHtml = compareNote
    ? `<p class="single-candidate-note" role="status">${escapeHtml(compareNote)}</p>`
    : "";

  el.innerHTML = cardsHtml + noteHtml;
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
    <span class="route-keyword score">${gradeBadgeHtml(recommended.safety_score)} 안전 ${recommended.safety_score}점</span>
    <span class="route-keyword">${escapeHtml(scoreTopPercentLine(recommended.safety_score))}</span>
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
  board.innerHTML = `
    <div class="kid-progress-summary">🚶 길 스탬프는 「아이가 보기 쉽게」에서 받아요</div>
    <div class="stamp-board-title">🎉 오늘의 안전 스탬프 ${gradeBadgeHtml(recommended.safety_score)}</div>
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
  updateKidProgressSummaryOnBoard();
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
  if (cachedKidGuideShareUrl) return cachedKidGuideShareUrl;
  const payload = buildKidGuideSharePayload();
  cachedKidGuideShareUrl = await createKidGuideShareOnServer(payload, API_BASE, authHeaders());
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

function setKidCardIcon(iconEl, { isArrive, icon, kind }) {
  if (!iconEl) return;
  iconEl.classList.toggle("is-cross", !isArrive && kind === "cross");
  iconEl.classList.toggle("is-arrive", isArrive);
  if (!isArrive && kind === "cross") {
    iconEl.innerHTML =
      '<span class="kid-card-sign" aria-hidden="true"><span class="kid-card-sign-inner">🚸</span></span>';
    return;
  }
  iconEl.textContent = isArrive ? "🎉" : icon;
}

function renderKidCard(direction = 0) {
  const steps = state.kidCardSteps;
  const total = steps.length;
  const index = Math.min(state.kidCardIndex, total - 1);
  const step = steps[index];
  const isArrive = index === total - 1;
  const [icon, kind] = navigationIcon(step);
  const { text: stepText } = kidStepText(step.distance_m);
  const landmark = landmarkPhrase(step);
  const plain = navigationKeywordPlain(step);
  const weather = state.lastResult?.weather || null;
  const tip = kidSafetyTip(step, { isArrive, weather });
  const meters = !isArrive && step.distance_m > 0 ? `${Math.round(step.distance_m)}m` : "";
  const friendly = !isArrive && stepText ? `👣 ${stepText} 걸어가요` : "";

  document.getElementById("kid-card-progress").textContent = `${index + 1} / ${total}`;
  document.getElementById("kid-card").classList.toggle("arrived", isArrive);
  setKidCardIcon(document.getElementById("kid-card-icon"), { isArrive, icon, kind });
  document.getElementById("kid-card-text").textContent = isArrive ? "도착! 잘했어요" : plain;

  const friendlyEl = document.getElementById("kid-card-friendly");
  if (friendlyEl) friendlyEl.textContent = friendly;

  const tipEl = document.getElementById("kid-card-tip");
  if (tipEl) tipEl.textContent = tip || "";

  const distanceEl = document.getElementById("kid-card-distance");
  if (distanceEl) distanceEl.textContent = meters;

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

  // 공유(카톡·링크 복사)는 마지막(도착) 카드에만
  const shareRow = document.getElementById("kid-card-share-row");
  if (shareRow) shareRow.hidden = !isArrive;

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
  const coarse = isCoarsePointerUi();
  el.innerHTML = `
    <span class="legend-instruction">${
      coarse
        ? "공공데이터 항목을 탭하면 강조됩니다. 다시 탭하면 해제됩니다."
        : "공공데이터 항목에 커서를 올리면 강조됩니다."
    }</span>
    ${PUBLIC_DATA_LEGEND.map(([layer, color, label]) => {
      const active = state.activePublicLayer === layer ? " is-active" : "";
      return `<button type="button" class="legend-item${active}" data-public-layer="${layer}"><span class="dot" style="background:${CATEGORY_COLORS[color]}"></span>${label}</button>`;
    }).join("")}
  `;
  el.querySelectorAll("[data-public-layer]").forEach((item) => {
    const layer = item.dataset.publicLayer;
    if (coarse) {
      item.addEventListener("click", (event) => {
        event.preventDefault();
        setActivePublicLayer(state.activePublicLayer === layer ? null : layer);
      });
    } else {
      item.addEventListener("pointerenter", () => setActivePublicLayer(layer));
      item.addEventListener("focus", () => setActivePublicLayer(layer));
      item.addEventListener("pointerleave", () => setActivePublicLayer(null));
      item.addEventListener("blur", () => setActivePublicLayer(null));
    }
  });
}

function isCoarsePointerUi() {
  try {
    return window.matchMedia("(hover: none), (pointer: coarse)").matches;
  } catch {
    return false;
  }
}

function setActivePublicLayer(layer) {
  if (state.activePublicLayer === layer) return;
  state.activePublicLayer = layer;
  if (state.lastResult && state.publicData) {
    renderMap(state.lastResult, state.publicData, false);
  } else if (state.publicData && state.docMode === "analyzed") {
    renderDocRiskOnlyMap(state.publicData);
  }
  // 범례 활성 표시만 갱신 (전체 리렌더 없이)
  document.querySelectorAll("#legend .legend-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.publicLayer === state.activePublicLayer);
  });
}

function isLayerEmphasized(layer) {
  return state.activePublicLayer === layer;
}

const LAYER_ALERT_NEAR_M = 40;

function minDistanceToActiveRoute(pt, routeData) {
  const selected = activeRoute(routeData);
  if (!selected?.coordinates?.length || !pt) return Infinity;
  let best = Infinity;
  for (const c of selected.coordinates) {
    const d = distanceMeters(pt, c);
    if (d < best) best = d;
  }
  return best;
}

function isPointNearActiveRoute(pt, routeData, radiusM = LAYER_ALERT_NEAR_M) {
  return minDistanceToActiveRoute(pt, routeData) <= radiusM;
}

function isDocRiskNearActiveRoute(d, routeData, radiusM = LAYER_ALERT_NEAR_M) {
  const samples = [];
  if (Number.isFinite(d?.lat) && Number.isFinite(d?.lng)) samples.push({ lat: d.lat, lng: d.lng });
  if (docRiskHasSegment(d)) samples.push({ lat: d.end_lat, lng: d.end_lng });
  const poly = Array.isArray(d?.polyline) ? d.polyline : [];
  const step = Math.max(1, Math.floor(poly.length / 10) || 1);
  for (let i = 0; i < poly.length; i += step) {
    if (Number.isFinite(poly[i]?.lat) && Number.isFinite(poly[i]?.lng)) samples.push(poly[i]);
  }
  return samples.some((p) => isPointNearActiveRoute(p, routeData, radiusM));
}

function layerDrawStyle(layer, { nearRoute = false } = {}) {
  const emphasized = isLayerEmphasized(layer);
  const strong = emphasized || nearRoute;
  const isDoc = layer === "doc-risk";
  return {
    strong,
    emphasized,
    opacity: strong ? 1 : 0.3,
    // 문서 위험: 점선 3px 기준 / 시설: 점만
    weight: isDoc ? (strong ? 4 : 3) : 0,
    iconSize: strong ? 18 : 11,
    showLabel: emphasized,
  };
}

/** Tmap 통학 경로: 흰 헤일로 위에 파란 실선. */
function drawTmapCommuteRoute(path, track) {
  track(
    new Tmapv2.Polyline({
      path,
      strokeColor: ROUTE_LINE.haloColor,
      strokeWeight: ROUTE_LINE.haloWeight,
      strokeStyle: "solid",
      strokeOpacity: 0.95,
      map: state.tmap,
    })
  );
  track(
    new Tmapv2.Polyline({
      path,
      strokeColor: ROUTE_LINE.color,
      strokeWeight: ROUTE_LINE.weight,
      strokeStyle: "solid",
      strokeOpacity: ROUTE_LINE.opacity,
      map: state.tmap,
    })
  );
}

/** SVG 통학 경로: 흰 외곽선 + 파란 실선. */
function drawSvgCommuteRoute(svg, ns, pts) {
  const points = pts.map((p) => `${p.x},${p.y}`).join(" ");
  const halo = document.createElementNS(ns, "polyline");
  halo.setAttribute("points", points);
  halo.setAttribute("fill", "none");
  halo.setAttribute("stroke", ROUTE_LINE.haloColor);
  halo.setAttribute("stroke-width", String(ROUTE_LINE.haloWeight));
  halo.setAttribute("stroke-opacity", "0.95");
  halo.setAttribute("stroke-linecap", "round");
  halo.setAttribute("stroke-linejoin", "round");
  svg.appendChild(halo);
  const path = document.createElementNS(ns, "polyline");
  path.setAttribute("points", points);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", ROUTE_LINE.color);
  path.setAttribute("stroke-width", String(ROUTE_LINE.weight));
  path.setAttribute("stroke-opacity", String(ROUTE_LINE.opacity));
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.appendChild(path);
}

function docRiskShortLabel(d) {
  const raw = String(d?.location_text || d?.risk_type || "위험구간").trim();
  const cleaned = raw
    .replace(/^서울특별시\s*/u, "")
    .replace(/^강남구\s*/u, "")
    .trim();
  const text = cleaned || raw || "위험구간";
  return text.length > 22 ? `${text.slice(0, 20)}…` : text;
}

/** 공공 레이어는 경로 근처를 기본(흐림)으로 항상 그리고, 범례 강조 시 진하게. */
function shouldDrawPublicLayer(layer) {
  if (layer === "doc-risk") {
    return state.docMode === "analyzed" || Boolean(state.activePublicLayer === "doc-risk");
  }
  return true;
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

/** 문서 위험: pedestrian 폴리라인 우선, 없으면 시작~끝 직선은 그리지 않음(검증 실패분). */
function drawDocRiskOverlays(points, { track, bounds, onBounds, routeData = null }) {
  let segmentCount = 0;
  points.forEach((d) => {
    const color = d.is_estimated ? CATEGORY_COLORS.docRiskEstimated : CATEGORY_COLORS.docRisk;
    const near = routeData ? isDocRiskNearActiveRoute(d, routeData) : false;
    const style = layerDrawStyle("doc-risk", { nearRoute: near });
    const shortLabel = docRiskShortLabel(d);
    const start = new Tmapv2.LatLng(d.lat, d.lng);
    bounds.extend(start);
    if (onBounds) onBounds();

    const poly = Array.isArray(d.polyline) ? d.polyline.filter((p) => Number.isFinite(p?.lat) && Number.isFinite(p?.lng)) : [];
    if (poly.length >= 2) {
      const path = poly.map((p) => new Tmapv2.LatLng(p.lat, p.lng));
      path.forEach((latlng) => {
        bounds.extend(latlng);
        if (onBounds) onBounds();
      });
      track(
        new Tmapv2.Polyline({
          path,
          strokeColor: color,
          strokeWeight: style.weight,
          strokeStyle: "dash",
          strokeDashArray: [6, 4],
          strokeOpacity: style.opacity,
          map: state.tmap,
        })
      );
      segmentCount += 1;
      [path[0], path[path.length - 1]].forEach((latlng, idx) => {
        const opts = {
          position: latlng,
          icon: tmapDotIcon(color, { size: style.iconSize, opacity: style.opacity }),
          iconSize: new Tmapv2.Size(style.iconSize, style.iconSize),
          map: state.tmap,
        };
        if (style.showLabel && idx === 0) opts.label = shortLabel;
        const m = track(new Tmapv2.Marker(opts));
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

    // 폴리라인 없음: 시작 핀만 (직선 추정 금지). 끝점은 있을 때만 표시
    const markers = [start];
    if (docRiskHasSegment(d)) {
      markers.push(new Tmapv2.LatLng(d.end_lat, d.end_lng));
      bounds.extend(markers[1]);
      if (onBounds) onBounds();
    }
    markers.forEach((latlng, idx) => {
      const opts = {
        position: latlng,
        icon: tmapDotIcon(color, { size: style.iconSize, opacity: style.opacity }),
        iconSize: new Tmapv2.Size(style.iconSize, style.iconSize),
        map: state.tmap,
      };
      if (style.showLabel && idx === 0) opts.label = shortLabel;
      const m = track(new Tmapv2.Marker(opts));
      m.addListener("click", () => {
        if (state.infoWindow) state.infoWindow.setMap(null);
        state.infoWindow = new Tmapv2.InfoWindow({
          position: latlng,
          content: docRiskInfoHtml({ ...d, location_text: (d.location_text || "") + " · 구간 확인 필요" }),
          type: 2,
          map: state.tmap,
        });
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

  // 선택한 통학 경로만 (파란 실선 + 흰 헤일로)
  if (active && active.coordinates.length >= 2) {
    const pts = active.coordinates.map((pt) => project(pt, bounds, size, padding));
    drawSvgCommuteRoute(svg, ns, pts);
  }

  function drawMarker(pt, color, shape, title, { opacity = 1, sizeScale = 1, label = "" } = {}) {
    const p = project(pt, bounds, size, padding);
    const r = Math.max(3, Math.round(6 * sizeScale));
    let node;
    if (shape === "circle") {
      node = document.createElementNS(ns, "circle");
      node.setAttribute("cx", p.x);
      node.setAttribute("cy", p.y);
      node.setAttribute("r", r);
    } else if (shape === "triangle") {
      node = document.createElementNS(ns, "polygon");
      const s = Math.max(4, Math.round(8 * sizeScale));
      node.setAttribute("points", `${p.x},${p.y - s} ${p.x - s},${p.y + s} ${p.x + s},${p.y + s}`);
    } else if (shape === "diamond") {
      node = document.createElementNS(ns, "polygon");
      const s = Math.max(4, Math.round(7 * sizeScale));
      node.setAttribute("points", `${p.x},${p.y - s} ${p.x + s},${p.y} ${p.x},${p.y + s} ${p.x - s},${p.y}`);
    } else {
      const half = Math.max(3, Math.round(6 * sizeScale));
      node = document.createElementNS(ns, "rect");
      node.setAttribute("x", p.x - half);
      node.setAttribute("y", p.y - half);
      node.setAttribute("width", half * 2);
      node.setAttribute("height", half * 2);
    }
    node.setAttribute("fill", color);
    node.setAttribute("fill-opacity", String(opacity));
    node.setAttribute("stroke", "white");
    node.setAttribute("stroke-opacity", String(opacity));
    node.setAttribute("stroke-width", 1.5);
    const titleEl = document.createElementNS(ns, "title");
    titleEl.textContent = title;
    node.appendChild(titleEl);
    svg.appendChild(node);
    if (label) {
      const text = document.createElementNS(ns, "text");
      text.setAttribute("x", p.x + r + 4);
      text.setAttribute("y", p.y + 4);
      text.setAttribute("font-size", "11");
      text.setAttribute("font-weight", "700");
      text.setAttribute("fill", "#333");
      text.textContent = label;
      svg.appendChild(text);
    }
  }

  function drawPublicPoint(pt, color, shape, title, layer, nameForLabel = "") {
    const near = isPointNearActiveRoute(pt, routeData);
    const style = layerDrawStyle(layer, { nearRoute: near });
    drawMarker(pt, color, shape, title, {
      opacity: style.opacity,
      sizeScale: style.strong ? 1 : 0.65,
      label: style.showLabel ? nameForLabel : "",
    });
  }

  if (shouldDrawPublicLayer("cctv")) {
    childZones.forEach((z) =>
      drawPublicPoint(z, CATEGORY_COLORS.cctv, "circle", `${z.name || "어린이보호구역"} (CCTV ${z.cctv_count}대)`, "cctv", z.name || "어린이보호구역")
    );
  }
  if (shouldDrawPublicLayer("safety-cctv")) {
    sf.cctv.forEach((f) =>
      drawPublicPoint(
        f,
        CATEGORY_COLORS.safetyCctv,
        "circle",
        `📹 ${f.label} ${f.install_count > 1 ? `x${f.install_count}` : ""} · ${f.dong || f.district || ""}`,
        "safety-cctv",
        f.label || "CCTV"
      )
    );
  }
  if (shouldDrawPublicLayer("safety-streetlight")) {
    sf.streetlight.forEach((f) =>
      drawPublicPoint(f, CATEGORY_COLORS.safetyStreetlight, "circle", `💡 ${f.label} · ${f.dong || f.district || ""}`, "safety-streetlight", f.label || "가로등")
    );
  }
  if (shouldDrawPublicLayer("hotspot")) {
    accidentHotspots.forEach((h) =>
      drawPublicPoint(h, CATEGORY_COLORS.hotspot, "circle", `${h.name || "사고다발지역"} (${h.occurrence_count}건)`, "hotspot", h.name || "사고다발")
    );
  }
  if (shouldDrawPublicLayer("guardian")) {
    guardianHouses.forEach((g) =>
      drawPublicPoint(g, CATEGORY_COLORS.guardian, "circle", `🏪 ${g.name || "아동안전지킴이집"}`, "guardian", g.name || "지킴이집")
    );
  }
  if (shouldDrawPublicLayer("doc-risk")) {
    documentPoints.forEach((d) => {
      const color = d.is_estimated ? CATEGORY_COLORS.docRiskEstimated : CATEGORY_COLORS.docRisk;
      const title = docRiskTitle(d);
      const near = isDocRiskNearActiveRoute(d, routeData);
      const style = layerDrawStyle("doc-risk", { nearRoute: near });
      const shortLabel = style.showLabel ? docRiskShortLabel(d) : "";
      const poly = Array.isArray(d.polyline) ? d.polyline.filter((p) => Number.isFinite(p?.lat) && Number.isFinite(p?.lng)) : [];
      if (poly.length >= 2) {
        const pts = poly.map((p) => project(p, bounds, size, padding));
        const path = document.createElementNS(ns, "polyline");
        path.setAttribute("points", pts.map((p) => `${p.x},${p.y}`).join(" "));
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", String(style.weight));
        path.setAttribute("stroke-opacity", String(style.opacity));
        path.setAttribute("stroke-linecap", "round");
        path.setAttribute("stroke-dasharray", "6 4");
        const titleEl = document.createElementNS(ns, "title");
        titleEl.textContent = title;
        path.appendChild(titleEl);
        svg.appendChild(path);
        drawMarker(poly[0], color, "circle", title, {
          opacity: style.opacity,
          sizeScale: style.strong ? 1 : 0.65,
          label: shortLabel,
        });
        drawMarker(poly[poly.length - 1], color, "circle", title, {
          opacity: style.opacity,
          sizeScale: style.strong ? 1 : 0.65,
        });
      } else if (docRiskHasSegment(d)) {
        const a = project(d, bounds, size, padding);
        const b = project({ lat: d.end_lat, lng: d.end_lng }, bounds, size, padding);
        const path = document.createElementNS(ns, "polyline");
        path.setAttribute("points", `${a.x},${a.y} ${b.x},${b.y}`);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", String(style.weight));
        path.setAttribute("stroke-opacity", String(style.opacity));
        path.setAttribute("stroke-linecap", "round");
        path.setAttribute("stroke-dasharray", "6 4");
        const titleEl = document.createElementNS(ns, "title");
        titleEl.textContent = title;
        path.appendChild(titleEl);
        svg.appendChild(path);
        drawMarker(d, color, "circle", title, {
          opacity: style.opacity,
          sizeScale: style.strong ? 1 : 0.65,
          label: shortLabel,
        });
        drawMarker({ lat: d.end_lat, lng: d.end_lng }, color, "circle", title, {
          opacity: style.opacity,
          sizeScale: style.strong ? 1 : 0.65,
        });
      } else {
        drawMarker(d, color, "circle", title, {
          opacity: style.opacity,
          sizeScale: style.strong ? 1 : 0.65,
          label: shortLabel,
        });
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
function tmapDotIcon(color, { size = 18, opacity = 1 } = {}) {
  const s = Math.max(8, Math.round(size));
  const cx = s / 2;
  const r = Math.max(3, Math.round(s * 0.33));
  const strokeW = Math.max(1, Math.round(s * 0.11));
  const op = Math.max(0.15, Math.min(1, Number(opacity) || 1));
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}">` +
    `<circle cx="${cx}" cy="${cx}" r="${r}" fill="${color}" fill-opacity="${op}" ` +
    `stroke="white" stroke-opacity="${op}" stroke-width="${strokeW}"/></svg>`;
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

/** 경로(선택 후보·기하)가 바뀌었을 때만 fitBounds 하도록 지문. */
function mapFitKey(routeData) {
  const active = activeRoute(routeData);
  if (!active?.coordinates?.length) return "";
  const coords = active.coordinates;
  const first = coords[0];
  const mid = coords[Math.floor(coords.length / 2)];
  const last = coords[coords.length - 1];
  return [
    active.id,
    coords.length,
    Math.round(Number(active.distance_m) || 0),
    Number(first.lat).toFixed(5),
    Number(first.lng).toFixed(5),
    Number(mid.lat).toFixed(5),
    Number(mid.lng).toFixed(5),
    Number(last.lat).toFixed(5),
    Number(last.lng).toFixed(5),
  ].join("|");
}

function renderTmapRoutes(routeData, publicData, { fitToRoute = true } = {}) {
  if (!state.tmap) return;
  clearTmapOverlays();
  const bounds = new Tmapv2.LatLngBounds();
  // fitBounds는 통학 경로(+출발/도착)만 기준 — 시설 마커까지 넣으면 과도하게 축소됨
  const routeFitBounds = new Tmapv2.LatLngBounds();
  let hasPoint = false;
  let hasRouteFitPoint = false;
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
      routeFitBounds.extend(latlng);
      hasPoint = true;
      hasRouteFitPoint = true;
      return latlng;
    });
    drawTmapCommuteRoute(path, track);
  }

  function marker(pt, color, title, layer, nameForLabel = "") {
    const near = isPointNearActiveRoute(pt, routeData);
    const style = layerDrawStyle(layer, { nearRoute: near });
    const latlng = new Tmapv2.LatLng(pt.lat, pt.lng);
    bounds.extend(latlng);
    hasPoint = true;
    const options = {
      position: latlng,
      icon: tmapDotIcon(color, { size: style.iconSize, opacity: style.opacity }),
      iconSize: new Tmapv2.Size(style.iconSize, style.iconSize),
      map: state.tmap,
    };
    if (style.showLabel && nameForLabel) options.label = nameForLabel;
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
    routeFitBounds.extend(latlng);
    hasPoint = true;
    hasRouteFitPoint = true;
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

  if (shouldDrawPublicLayer("cctv")) {
    childZones.forEach((z) =>
      marker(z, CATEGORY_COLORS.cctv, `${z.name || "어린이보호구역"} (CCTV ${z.cctv_count}대)`, "cctv", z.name || "어린이보호구역")
    );
  }
  if (shouldDrawPublicLayer("safety-cctv")) {
    sf.cctv.forEach((f) =>
      marker(
        f,
        CATEGORY_COLORS.safetyCctv,
        `📹 ${f.label} ${f.install_count > 1 ? `x${f.install_count}` : ""} · ${f.dong || f.district || ""}`,
        "safety-cctv",
        f.label || "CCTV"
      )
    );
  }
  if (shouldDrawPublicLayer("safety-streetlight")) {
    sf.streetlight.forEach((f) =>
      marker(f, CATEGORY_COLORS.safetyStreetlight, `💡 ${f.label} · ${f.dong || f.district || ""}`, "safety-streetlight", f.label || "가로등")
    );
  }
  if (shouldDrawPublicLayer("hotspot")) {
    accidentHotspots.forEach((h) =>
      marker(h, CATEGORY_COLORS.hotspot, `${h.name || "사고다발지역"} (${h.occurrence_count}건)`, "hotspot", h.name || "사고다발")
    );
  }
  if (shouldDrawPublicLayer("guardian")) {
    guardianHouses.forEach((g) =>
      marker(g, CATEGORY_COLORS.guardian, `🏪 ${g.name || "아동안전지킴이집"}`, "guardian", g.name || "지킴이집")
    );
  }
  if (shouldDrawPublicLayer("doc-risk")) {
    drawDocRiskOverlays(documentPoints, {
      track,
      bounds,
      routeData,
      onBounds: () => {
        hasPoint = true;
      },
    });
  }

  // 출발/도착: 초록·빨강 핀 아이콘
  waypointMarker(routeData.origin, "origin", routeData.origin.name || "출발");
  waypointMarker(routeData.destination, "destination", routeData.destination.name || "도착");

  if (fitToRoute && hasRouteFitPoint) {
    fitTmapToRouteBounds(routeFitBounds);
  }
}

/** 경로 전체가 보이되, 시설 마커 없이 경로(+출발/도착)만 맞춰 조금 더 확대한다. */
function fitTmapToRouteBounds(bounds) {
  if (!state.tmap || !bounds) return;
  try {
    // 여백(px)이 작을수록 경로가 화면을 더 크게 채움
    state.tmap.fitBounds(bounds, {
      top: 56,
      right: 48,
      bottom: 56,
      left: 48,
    });
  } catch {
    state.tmap.fitBounds(bounds);
  }
}

function renderMap(routeData, publicData, refreshLegend = true) {
  const fitKey = mapFitKey(routeData);
  const fitToRoute = Boolean(fitKey) && fitKey !== state.lastMapFitKey;
  if (state.tmapReady) {
    setMapStatus("", false);
    document.getElementById("tmap").style.display = "block";
    document.getElementById("svg-map").style.display = "none";
    renderTmapRoutes(routeData, publicData, { fitToRoute });
    if (fitToRoute) state.lastMapFitKey = fitKey;
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
  const progressTimers = [];
  setRouteProgress("경로를 찾고 있어요");

  try {
    const originQuery = document.getElementById("origin-query").value.trim();
    const destQuery = document.getElementById("dest-query").value.trim();
    if (!originQuery || !destQuery) {
      alert("출발지와 목적지 이름을 모두 입력해주세요.");
      return;
    }

    const routeData = await fetchAndRenderRoute({ originQuery, destQuery, progressTimers });

    if (routeData.used_mock && routeData.used_mock.routing) {
      console.warn("[경로] MOCK 모드 — Tmap 보행자 API 미사용");
    } else {
      const main = routeData.candidates.find((c) => c.source === "TMAP_PEDESTRIAN_API");
      if (main) {
        console.log(`[경로] Tmap 보행자 경로 좌표 ${main.coordinates.length}개`);
      }
    }
    if (routeData.from_cache) {
      console.log("[경로] 캐시된 결과 사용");
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
    clearRouteProgressTimers(progressTimers);
    setRouteProgress("");
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
  const summary = document.getElementById("doc-placed-summary");
  if (panel) panel.hidden = true;
  if (list) list.innerHTML = "";
  if (summary) {
    summary.hidden = true;
    summary.textContent = "";
  }
}

function docPointQueryLine(pt) {
  const startQ = pt.start_geocode_query || pt.geocode_query || "";
  const endQ = pt.end_geocode_query || "";
  return endQ ? `${startQ} ~ ${endQ}` : startQ;
}

function renderDocPlacedPanel(createdPoints, pendingPoints = []) {
  const panel = document.getElementById("doc-placed-panel");
  const list = document.getElementById("doc-placed-list");
  const summary = document.getElementById("doc-placed-summary");
  if (!panel || !list) return;

  const points = Array.isArray(createdPoints) ? createdPoints : [];
  const pending = Array.isArray(pendingPoints) ? pendingPoints : [];
  const total = points.length + pending.length;
  if (!points.length && !pending.length) {
    hideDocPlacedPanel();
    return;
  }
  // 성공분만 이 패널에 표시 (실패분은 위 review 패널)
  if (!points.length) {
    hideDocPlacedPanel();
    return;
  }

  if (summary) {
    summary.hidden = false;
    summary.textContent = `${total || points.length}개 구간 중 ${points.length}개 위치 확인 완료`;
  }

  list.innerHTML = "";
  points.forEach((pt) => {
    const li = document.createElement("li");
    li.className = "doc-review-item doc-placed-item is-ok";

    const head = document.createElement("div");
    head.className = "doc-placed-item-head";

    const title = document.createElement("p");
    title.className = "doc-review-item-title";
    title.textContent = pt.location_text || pt.geocode_query || "구간";

    const status = document.createElement("span");
    status.className = "doc-geo-status is-ok";
    status.textContent = "✓ 위치 확인됨";

    head.append(title, status);

    const queryLine = docPointQueryLine(pt);
    const match = pt.matched_label || "";
    const details = document.createElement("details");
    details.className = "doc-placed-query-details";
    const summaryEl = document.createElement("summary");
    summaryEl.textContent = "검색어 보기";
    const meta = document.createElement("p");
    meta.className = "doc-review-item-meta";
    const matchClean = match.replace(/\s+/g, "");
    const queryClean = queryLine.replace(/\s+/g, "");
    const showMatch = match && matchClean && matchClean !== queryClean;
    meta.textContent = showMatch ? `검색어: ${queryLine} → ${match}` : `검색어: ${queryLine || "(없음)"}`;
    details.append(summaryEl, meta);

    li.append(head, details);
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
    li.className = "doc-review-item doc-review-item-pending";
    li.dataset.index = String(idx);

    const head = document.createElement("div");
    head.className = "doc-placed-item-head";

    const title = document.createElement("p");
    title.className = "doc-review-item-title";
    title.textContent = pt.location_text || pt.geocode_query || `지점 ${idx + 1}`;

    const status = document.createElement("span");
    status.className = "doc-geo-status is-warn";
    status.textContent = "⚠ 위치 확인 필요";

    head.append(title, status);

    const queryLine = docPointQueryLine(pt);
    const meta = document.createElement("p");
    meta.className = "doc-review-item-meta";
    const conf =
      typeof pt.confidence === "number" ? ` · 확신 ${(pt.confidence * 100).toFixed(0)}%` : "";
    const reason = pt.reason || "위치 확인 필요";
    meta.textContent = queryLine
      ? `검색어: ${queryLine} · ${reason}${conf}${pt.risk_type ? ` · ${pt.risk_type}` : ""}`
      : `${reason}${conf}${pt.risk_type ? ` · ${pt.risk_type}` : ""}`;

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
    li.append(head, meta, label, input, endLabel, endInput, actions);
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
  // focusDocRisk: 문서 반영 후 지도만 갱신 (기본은 흐림, 범례로 강조)
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

  const progressTimers = [];
  try {
    setRouteProgress("경로를 찾고 있어요");
    await fetchAndRenderRoute({ originQuery, destQuery, progressTimers });
  } finally {
    clearRouteProgressTimers(progressTimers);
    setRouteProgress("");
    const btn = document.getElementById("submit-btn");
    if (btn) btn.textContent = "안전 경로 찾기";
    syncRouteSubmitButton();
  }
  return true;
}

function syncRouteSubmitButton() {
  const btn = document.getElementById("submit-btn");
  if (!btn) return;
  btn.disabled = !state.docReady;
  btn.title = state.docReady
    ? ""
    : "먼저 안전 문서를 확인하거나 반영 안함을 선택해 주세요.";
  syncFloatSubmitButton();
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

    // 이전 문서 위험(직선으로 이어진 옛 점)을 지우고 다시 올린다
    try {
      await fetch(`${API_BASE}/api/documents`, {
        method: "DELETE",
        headers: { ...authHeaders() },
      });
    } catch (err) {
      console.warn("이전 문서 위험 삭제 실패(계속 진행)", err);
    }

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
    renderDocPlacedPanel(allCreated, allPending);

    const errHint = errors.length ? ` · 일부 실패 ${errors.length}건` : "";
    if (totalCreated > 0) {
      // 성공 구간은 아래 「문서 기반 위험 지역」 패널로 안내. 처리 단계 문구는 노출하지 않음.
      setDocUploadStatus(errors.length ? `일부 문서 분석 실패 ${errors.length}건` : "", "");
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
    : "안전 리포트";
  const parentReportTitle = document.querySelector(".parent-report-card h3");
  if (parentReportTitle) parentReportTitle.textContent = "안전 리포트";
  document.getElementById("results-label").textContent = kidMode
    ? "오늘의 추천 길"
    : "안전한 길 비교";
  const scaleHint = document.getElementById("score-scale-hint");
  if (scaleHint) scaleHint.hidden = kidMode;

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
  document.getElementById("origin-query")?.addEventListener("input", () => {
    const originHint = document.getElementById("origin-addr-hint");
    if (originHint) {
      originHint.textContent = "";
      originHint.hidden = true;
    }
    syncFloatSearchFields("main");
  });
  document.getElementById("dest-query")?.addEventListener("input", () => {
    const destHint = document.getElementById("dest-addr-hint");
    if (destHint) {
      destHint.textContent = "";
      destHint.hidden = true;
    }
    syncFloatSearchFields("main");
  });
  document.getElementById("float-origin-query")?.addEventListener("input", () => {
    const originHint = document.getElementById("origin-addr-hint");
    if (originHint) {
      originHint.textContent = "";
      originHint.hidden = true;
    }
    syncFloatSearchFields("float");
  });
  document.getElementById("float-dest-query")?.addEventListener("input", () => {
    const destHint = document.getElementById("dest-addr-hint");
    if (destHint) {
      destHint.textContent = "";
      destHint.hidden = true;
    }
    syncFloatSearchFields("float");
  });
  document.getElementById("float-swap-locations")?.addEventListener("click", swapLocations);
  document.getElementById("map-search-float")?.addEventListener("submit", (event) => {
    event.preventDefault();
    syncFloatSearchFields("float");
    document.getElementById("route-form")?.requestSubmit();
  });
  syncFloatSearchFields("main");
  syncFloatSubmitButton();
  bindDocumentUpload();
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.mode));
  });
  document.querySelectorAll("[data-time-mode]").forEach((button) => {
    button.addEventListener("click", () => setTimeMode(button.dataset.timeMode));
  });
  syncTimeModeButtons();
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
