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

  const title = data.title || "오늘의 안전 길";
  document.title = `👶 ${title}`;

  state.steps = data.steps || [];
  state.index = 0;
  renderStoryBar();
  renderCard(0);
}

function renderStoryBar() {
  const bar = document.getElementById("kid-guide-story-bar");
  if (!bar) return;
  bar.innerHTML = state.steps
    .map((_, idx) => {
      const cls = idx < state.index ? "done" : idx === state.index ? "active" : "";
      return `<div class="kid-guide-story-seg ${cls}"><span></span></div>`;
    })
    .join("");
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

  const card = document.getElementById("kid-guide-card");
  card.classList.toggle("arrived", isArrive);
  document.getElementById("kid-guide-icon").textContent = step.icon || (isArrive ? "🎉" : "↑");
  document.getElementById("kid-guide-text").textContent = step.keyword || "";
  document.getElementById("kid-guide-friendly").textContent = step.friendly || "";
  document.getElementById("kid-guide-tip").textContent = step.tip || tipForShareStep(step);
  document.getElementById("kid-guide-landmark").textContent = step.landmark || "";

  const nextBtn = document.getElementById("kid-guide-next-btn");
  if (isArrive) {
    nextBtn.textContent = "🎉 도착! 잘했어요";
    nextBtn.classList.add("arrive-btn");
    nextBtn.disabled = true;
  } else {
    nextBtn.textContent = index === total - 2 ? "거의 다 왔어요 →" : "다음 →";
    nextBtn.classList.remove("arrive-btn");
    nextBtn.disabled = false;
  }

  renderStoryBar();

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

function bindSwipe() {
  const card = document.getElementById("kid-guide-card");
  if (!card) return;

  let startX = 0;
  let startY = 0;

  card.addEventListener(
    "touchstart",
    (event) => {
      const touch = event.changedTouches[0];
      startX = touch.clientX;
      startY = touch.clientY;
    },
    { passive: true }
  );

  card.addEventListener(
    "touchend",
    (event) => {
      const touch = event.changedTouches[0];
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;
      if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy)) return;
      stepCard(dx < 0 ? 1 : -1);
    },
    { passive: true }
  );
}

async function fetchShareById(shareId) {
  const res = await fetch(`${API_BASE}/api/share/kid-guide/${encodeURIComponent(shareId)}`);
  if (!res.ok) return null;
  return res.json();
}

async function loadGuide() {
  if (window.__KID_GUIDE_PRELOAD__?.steps?.length) {
    showApp(window.__KID_GUIDE_PRELOAD__);
    return;
  }

  const inline = readInlineGuidePayload();
  if (inline?.steps?.length) {
    showApp(inline);
    return;
  }

  const shareId = readShareIdFromLocation();
  if (shareId) {
    try {
      const data = await fetchShareById(shareId);
      if (data?.steps?.length) {
        showApp(data);
        return;
      }
    } catch {
      /* fall through */
    }
  }

  showError(
    "길 안내를 불러오지 못했어요.\n엄마·아빠에게 링크 복사를 다시 눌러달라고 하세요."
  );
}

document.getElementById("kid-guide-next-btn")?.addEventListener("click", () => stepCard(1));
document.getElementById("kid-guide-tap-prev")?.addEventListener("click", () => stepCard(-1));
document.getElementById("kid-guide-tap-next")?.addEventListener("click", () => stepCard(1));

bindSwipe();
loadGuide();
