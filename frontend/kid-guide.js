function resolveApiBase() {
  const host = window.location.hostname;
  const isLocal =
    !host ||
    host === "localhost" ||
    host === "127.0.0.1" ||
    window.location.protocol === "file:";
  if (!isLocal || window.location.port === "8000") {
    return "";
  }
  return "http://127.0.0.1:8000";
}

const API_BASE = resolveApiBase();

const state = {
  steps: [],
  index: 0,
};

function showError(message) {
  document.getElementById("kid-guide-loading").hidden = true;
  document.getElementById("kid-guide-app").hidden = true;
  const errorEl = document.getElementById("kid-guide-error");
  document.getElementById("kid-guide-error-text").textContent = message;
  errorEl.hidden = false;
}

function showApp(data) {
  document.getElementById("kid-guide-loading").hidden = true;
  document.getElementById("kid-guide-error").hidden = true;
  document.getElementById("kid-guide-app").hidden = false;

  document.getElementById("kid-guide-title").textContent = data.title || "오늘의 안전 길";

  const metaParts = [];
  if (data.origin && data.destination) {
    metaParts.push(`${data.origin} → ${data.destination}`);
  }
  if (data.safety_score != null) metaParts.push(`안전 ${data.safety_score}점`);
  if (data.duration_min != null) metaParts.push(`약 ${data.duration_min}분`);
  document.getElementById("kid-guide-meta").textContent = metaParts.join(" · ");

  state.steps = data.steps || [];
  state.index = 0;
  renderCard(0);
}

function renderCard(direction = 0) {
  const steps = state.steps;
  const total = steps.length;
  if (!total) {
    showError("길 안내 내용이 비어 있어요.");
    return;
  }

  const index = Math.min(state.index, total - 1);
  const step = steps[index];
  const isArrive = step.is_arrive || index === total - 1;

  document.getElementById("kid-guide-progress").textContent = `${index + 1} / ${total}`;
  const card = document.getElementById("kid-guide-card");
  card.classList.toggle("arrived", isArrive);
  document.getElementById("kid-guide-icon").textContent = step.icon || (isArrive ? "🎉" : "↑");
  document.getElementById("kid-guide-text").textContent = step.keyword || "";
  document.getElementById("kid-guide-friendly").textContent = step.friendly || "";
  document.getElementById("kid-guide-distance").textContent =
    !isArrive && step.distance_m > 0 ? `${Math.round(step.distance_m)}m` : "";
  document.getElementById("kid-guide-landmark").textContent = step.landmark || "";
  document.getElementById("kid-guide-prev").disabled = index === 0;
  document.getElementById("kid-guide-next").hidden = isArrive;

  const stage = document.getElementById("kid-guide-stage");
  stage.classList.remove("slide-next", "slide-prev");
  void stage.offsetWidth;
  stage.classList.add(direction < 0 ? "slide-prev" : "slide-next");
}

function stepCard(delta) {
  const total = state.steps.length;
  const next = Math.min(total - 1, Math.max(0, state.index + delta));
  if (next === state.index) return;
  const direction = delta > 0 ? 1 : -1;
  state.index = next;
  renderCard(direction);
}

async function loadGuide() {
  const shareId = new URLSearchParams(window.location.search).get("id");
  if (!shareId) {
    showError("공유 링크가 올바르지 않아요.");
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/share/kid-guide/${encodeURIComponent(shareId)}`);
    if (!res.ok) {
      const detail = res.status === 404 ? "링크가 만료되었거나 찾을 수 없어요." : "길 안내를 불러오지 못했어요.";
      showError(detail);
      return;
    }
    showApp(await res.json());
  } catch {
    showError("서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.");
  }
}

document.getElementById("kid-guide-prev")?.addEventListener("click", () => stepCard(-1));
document.getElementById("kid-guide-next")?.addEventListener("click", () => stepCard(1));

loadGuide();
