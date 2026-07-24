/** 주변 안전문서 검색 (Liner) — 기존 app.js와 분리된 추가 UI */
(function () {
  const INITIAL_VISIBLE = 2;

  const btn = document.getElementById("liner-safety-docs-btn");
  const panel = document.getElementById("liner-search-panel");
  const input = document.getElementById("liner-region-input");
  const submit = document.getElementById("liner-search-submit");
  const statusEl = document.getElementById("liner-search-status");
  const listEl = document.getElementById("liner-search-results");
  const expandBtn = document.getElementById("liner-search-expand");

  if (!btn || !panel || !input || !submit || !statusEl || !listEl || !expandBtn) return;

  let resultsCache = [];
  let expanded = false;
  let searching = false;

  function apiBase() {
    if (typeof API_BASE === "string") return API_BASE;
    if (window.API_BASE) return window.API_BASE;
    return "http://127.0.0.1:8000";
  }

  function setOpen(open) {
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      input.focus();
    }
  }

  function setSearching(on) {
    searching = on;
    submit.disabled = on;
    input.disabled = on;
    if (on) {
      statusEl.textContent = "검색 중...";
      statusEl.classList.toggle("is-error", false);
    }
  }

  function showError(message) {
    statusEl.textContent = message;
    statusEl.classList.add("is-error");
    listEl.innerHTML = "";
    expandBtn.hidden = true;
  }

  function renderResults() {
    listEl.innerHTML = "";
    const total = resultsCache.length;
    if (total === 0) {
      statusEl.textContent = "해당 지역의 최근 안전 관련 문서를 찾지 못했습니다";
      statusEl.classList.remove("is-error");
      expandBtn.hidden = true;
      return;
    }

    statusEl.textContent = "";
    statusEl.classList.remove("is-error");

    const visible = expanded ? total : Math.min(INITIAL_VISIBLE, total);
    for (let i = 0; i < visible; i++) {
      listEl.appendChild(buildCard(resultsCache[i]));
    }

    if (total <= INITIAL_VISIBLE) {
      expandBtn.hidden = true;
      return;
    }

    expandBtn.hidden = false;
    if (expanded) {
      expandBtn.textContent = "접기";
    } else {
      expandBtn.textContent = `펼쳐보기 (${total - INITIAL_VISIBLE}건 더)`;
    }
  }

  function buildCard(item) {
    const li = document.createElement("li");
    li.className = "liner-result-card";

    const row = document.createElement("div");
    row.className = "liner-result-head";

    if (item.favicon_url) {
      const fav = document.createElement("img");
      fav.className = "liner-result-favicon";
      fav.src = item.favicon_url;
      fav.alt = "";
      fav.width = 16;
      fav.height = 16;
      fav.loading = "lazy";
      fav.addEventListener("error", () => {
        fav.hidden = true;
      });
      row.appendChild(fav);
    }

    const title = document.createElement("a");
    title.className = "liner-result-title";
    title.href = item.url || "#";
    title.target = "_blank";
    title.rel = "noopener noreferrer";
    title.textContent = item.title || item.url || "(제목 없음)";
    row.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "liner-result-meta";
    const parts = [item.hostname, item.date].filter(Boolean);
    meta.textContent = parts.join(" · ");

    const desc = document.createElement("p");
    desc.className = "liner-result-desc";
    desc.textContent = item.description || "";

    li.appendChild(row);
    if (parts.length) li.appendChild(meta);
    if (item.description) li.appendChild(desc);
    return li;
  }

  async function runSearch() {
    const region = input.value.trim();
    if (!region || searching) return;

    resultsCache = [];
    expanded = false;
    listEl.innerHTML = "";
    expandBtn.hidden = true;
    setSearching(true);

    try {
      const res = await fetch(`${apiBase()}/api/liner/safety-docs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ region }),
      });
      const data = await res.json().catch(() => ({}));
      if (data && data.error) {
        showError(String(data.error));
        return;
      }
      resultsCache = Array.isArray(data.results) ? data.results : [];
      renderResults();
    } catch (_err) {
      showError("검색에 실패했습니다");
    } finally {
      searching = false;
      submit.disabled = false;
      input.disabled = false;
    }
  }

  btn.addEventListener("click", (event) => {
    event.stopPropagation();
    setOpen(panel.hidden);
  });

  submit.addEventListener("click", () => {
    runSearch();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runSearch();
    }
  });

  expandBtn.addEventListener("click", () => {
    expanded = !expanded;
    renderResults();
  });

  document.addEventListener("click", (event) => {
    if (panel.hidden) return;
    const wrap = btn.closest(".liner-search-wrap");
    if (wrap && !wrap.contains(event.target)) {
      setOpen(false);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) {
      setOpen(false);
    }
  });
})();
