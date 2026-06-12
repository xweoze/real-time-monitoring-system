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

const setupMainMenu = () => {
  const button = document.querySelector("#menuBtn");
  const menu = document.querySelector("#mainMenu");
  if (!button || !menu) return;

  const close = () => {
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
  };
  button.addEventListener("click", event => {
    event.stopPropagation();
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    button.setAttribute("aria-expanded", String(willOpen));
  });
  menu.addEventListener("click", event => event.stopPropagation());
  document.addEventListener("click", close);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") close();
  });
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

const calculateAge = birthDate => {
  if (!birthDate) return null;
  const birth = new Date(`${birthDate}T00:00:00`);
  if (Number.isNaN(birth.getTime())) return null;
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const beforeBirthday = today.getMonth() < birth.getMonth()
    || (today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate());
  if (beforeBirthday) age -= 1;
  return age;
};

const genderLabel = gender => ({
  FEMALE: "여성",
  MALE: "남성",
  OTHER: "기타",
  UNDISCLOSED: "응답하지 않음",
}[gender] || "응답하지 않음");

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
