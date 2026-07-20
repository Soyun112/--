/** Google OAuth (백엔드 경유) + JWT localStorage 세션 */
const AUTH_TOKEN_KEY = "kids_auth_token";

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
  // 백엔드(8000)에서 정적 파일을 같이 제공할 때는 상대경로 /api 사용
  if (!isLocal || window.location.port === "8000") {
    return "";
  }
  return "http://127.0.0.1:8000";
}

const API_BASE = resolveApiBase();

function getAuthToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

function setAuthToken(token) {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

function clearAuthToken() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

function getFrontendOrigin() {
  if (window.location.protocol === "file:") {
    return "http://127.0.0.1:5500";
  }
  return `${window.location.origin}${window.location.pathname.replace(/\/[^/]*$/, "") || ""}`.replace(/\/$/, "") ||
    window.location.origin;
}

function consumeTokenFromUrl() {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  const hashParams = new URLSearchParams(hash);
  const tokenFromHash = hashParams.get("access_token");
  if (tokenFromHash) {
    setAuthToken(tokenFromHash);
    history.replaceState(null, "", window.location.pathname + window.location.search);
    return true;
  }

  const query = new URLSearchParams(window.location.search);
  const authError = query.get("auth_error");
  if (authError) {
    history.replaceState(null, "", window.location.pathname);
    return { error: authError };
  }
  return false;
}

function authHeaders() {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function startGoogleLogin() {
  let frontendUrl = window.location.origin;
  if (window.location.protocol === "file:") {
    frontendUrl = "http://127.0.0.1:5500";
  }
  const loginUrl = `${API_BASE}/api/auth/google/login?frontend_url=${encodeURIComponent(frontendUrl)}`;
  window.location.href = loginUrl;
}

async function fetchCurrentUser() {
  const token = getAuthToken();
  if (!token) return null;
  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, {
      headers: { ...authHeaders() },
    });
    if (!res.ok) {
      if (res.status === 401) clearAuthToken();
      return null;
    }
    return await res.json();
  } catch {
    return null;
  }
}

function renderUserProfile(user) {
  const wrap = document.getElementById("user-profile");
  const avatar = document.getElementById("user-avatar");
  const nameEl = document.getElementById("user-name");
  const emailEl = document.getElementById("user-email");
  if (!wrap || !user) return;

  if (user.picture) {
    avatar.src = user.picture;
    avatar.alt = `${user.name} 프로필`;
    avatar.hidden = false;
  } else {
    avatar.hidden = true;
  }
  nameEl.textContent = user.name || "사용자";
  emailEl.textContent = user.email || "";
  wrap.hidden = false;
}

function showLoginScreen(message) {
  document.getElementById("login-screen").hidden = false;
  document.getElementById("app-shell").hidden = true;
  const errEl = document.getElementById("login-error");
  if (errEl) {
    errEl.textContent = message || "";
    errEl.hidden = !message;
  }
}

function showAppShell() {
  document.getElementById("login-screen").hidden = true;
  document.getElementById("app-shell").hidden = false;
}

function logout() {
  clearAuthToken();
  fetch(`${API_BASE}/api/auth/logout`, { method: "POST" }).catch(() => {});
  showLoginScreen();
}

async function requireAuth() {
  const consumed = consumeTokenFromUrl();
  if (consumed && consumed.error) {
    showLoginScreen("Google 로그인에 실패했습니다. 다시 시도해 주세요.");
    return null;
  }

  const user = await fetchCurrentUser();
  if (!user) {
    showLoginScreen();
    return null;
  }

  showAppShell();
  renderUserProfile(user);
  return user;
}
