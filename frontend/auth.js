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

function consumeTokenFromUrl() {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  const hashParams = new URLSearchParams(hash);
  let tokenFromHash = hashParams.get("access_token");
  if (tokenFromHash) {
    try {
      tokenFromHash = decodeURIComponent(tokenFromHash);
    } catch {
      /* keep raw */
    }
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
  if (!token) return { user: null, error: null };

  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, {
      headers: { ...authHeaders() },
    });
    if (res.status === 404) {
      return {
        user: null,
        error: "백엔드에 로그인 API가 없습니다. Render에서 최신 코드를 Deploy latest commit 하세요.",
      };
    }
    if (res.status === 503) {
      return {
        user: null,
        error: "Google OAuth 환경변수가 Render에 설정되지 않았습니다.",
      };
    }
    if (!res.ok) {
      if (res.status === 401) clearAuthToken();
      return { user: null, error: "로그인 세션이 만료되었거나 유효하지 않습니다." };
    }
    return { user: await res.json(), error: null };
  } catch {
    return {
      user: null,
      error: "백엔드에 연결할 수 없습니다. BACKEND_URL(Render) 설정을 확인하세요.",
    };
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

function authErrorMessage(code) {
  if (code.startsWith("google_token_failed:")) {
    const googleErr = code.split(":").slice(1).join(":");
    const details = {
      invalid_client:
        "Client ID와 Client Secret이 짝이 맞지 않습니다. Google Console에서 같은 OAuth 클라이언트의 값을 Render에 넣으세요.",
      unauthorized_client: "OAuth 클라이언트 유형이 Web application인지 확인하세요.",
      redirect_uri_mismatch:
        "Redirect URI 불일치입니다. Google Console에 https://kids-safe-route-api.onrender.com/api/auth/google/callback 를 등록하세요.",
      invalid_grant: "인증 코드가 만료됐습니다. 페이지 새로고침 후 다시 로그인하세요.",
    };
    return (
      details[googleErr] ||
      `Google 토큰 교환 실패 (${googleErr}). Render·Google Console 설정을 확인하세요.`
    );
  }
  if (code.startsWith("login_failed:")) {
    const reason = code.split(":").slice(1).join(":");
    return `로그인 처리 중 오류 (${reason}). Render 로그·Google Console 설정을 확인하세요.`;
  }
  const messages = {
    google_token_failed:
      "Google Client Secret 또는 Redirect URI가 맞지 않습니다. Render·Google Console 설정을 확인하세요.",
    invalid_state: "로그인 세션이 만료되었습니다. 다시 시도해 주세요.",
    missing_code: "Google 인증 정보가 없습니다. 다시 시도해 주세요.",
    access_denied:
      "Google 로그인이 거부됐습니다. OAuth consent screen이 Testing이면 Test users에 본인 Gmail을 추가하세요.",
    login_failed: "로그인 처리 중 오류가 발생했습니다. 다시 시도해 주세요.",
  };
  return messages[code] || `Google 로그인 실패 (${code}). 다시 시도해 주세요.`;
}

function showLoginScreen(message) {
  const login = document.getElementById("login-screen");
  const app = document.getElementById("app-shell");
  login.hidden = false;
  login.style.display = "";
  if (app) {
    app.hidden = true;
    app.style.display = "none";
  }
  const errEl = document.getElementById("login-error");
  if (errEl) {
    errEl.textContent = message || "";
    errEl.hidden = !message;
  }
}

function showAppShell() {
  const login = document.getElementById("login-screen");
  const app = document.getElementById("app-shell");
  login.hidden = true;
  login.style.display = "none";
  if (app) {
    app.hidden = false;
    app.style.display = "";
  }
}

function logout() {
  clearAuthToken();
  fetch(`${API_BASE}/api/auth/logout`, { method: "POST" }).catch(() => {});
  showLoginScreen();
}

async function requireAuth() {
  const consumed = consumeTokenFromUrl();
  if (consumed && consumed.error) {
    showLoginScreen(authErrorMessage(consumed.error));
    return null;
  }

  const { user, error } = await fetchCurrentUser();
  if (!user) {
    showLoginScreen(error || "");
    return null;
  }

  showAppShell();
  renderUserProfile(user);
  return user;
}
