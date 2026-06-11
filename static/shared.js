const AUTH_TOKEN_KEY = "rtls-auth-token";
const AUTH_USER_KEY = "rtls-auth-user";

const authSession = {
  token: localStorage.getItem(AUTH_TOKEN_KEY) || "",
  user: JSON.parse(localStorage.getItem(AUTH_USER_KEY) || "null"),
  save(data) {
    this.token = data.token;
    this.user = data.user;
    localStorage.setItem(AUTH_TOKEN_KEY, data.token);
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify(data.user));
  },
  clear() {
    this.token = "";
    this.user = null;
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
  },
};

const api = async (url, options = {}) => {
  const authHeader = authSession.token
    ? { Authorization: `Bearer ${authSession.token}` }
    : {};
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeader,
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "요청 처리에 실패했습니다.");
    error.status = response.status;
    throw error;
  }
  return data;
};

const loadRegions = async selectElements => {
  const data = await api("/api/regions");
  const options = data.regions
    .map(region => `<option value="${region.id}">${escapeHtml(region.name)}</option>`)
    .join("");
  selectElements.forEach(element => {
    element.innerHTML = options;
  });
  return data.regions;
};

const logoutSession = async () => {
  try {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
  } finally {
    authSession.clear();
  }
};

const ago = value => {
  if (!value) return "-";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 5) return "방금 전";
  if (seconds < 60) return `${seconds}초 전`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}분 전`;
  return `${Math.floor(seconds / 3600)}시간 전`;
};

const timeOnly = value => value ? new Date(value).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "-";

const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
}[char]));

let toastTimer;
const toast = message => {
  const element = document.querySelector("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 2600);
};
