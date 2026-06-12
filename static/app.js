let client = null;
let regions = [];
let signupMode = false;
let lastDanger = false;
let holdTimer = null;
let holdStarted = 0;
let holdFrame = null;
let locationWatchId = null;
let heartbeatTimer = null;

const regionName = id => regions.find(region => region.id === id)?.name || id || "-";

function clearClient() {
  stopAutoShare();
  stopHeartbeat();
  client = null;
  lastDanger = false;
  sessionStorage.removeItem("rtls-client");
  setConnected(false);
}

function showAuthenticated(user) {
  document.querySelector("#authCard").hidden = Boolean(user);
  document.querySelector("#logoutBtn").hidden = !user;
  document.querySelector("#accountName").textContent = user?.displayName || "";
  if (!client) document.querySelector("#setupCard").hidden = !user;
}

function setConnected(connected) {
  const pill = document.querySelector("#connectionPill");
  pill.innerHTML = `<i class="status-dot ${connected ? "" : "offline"}"></i> ${connected ? "실시간 연결" : "연결 안 됨"}`;
  document.querySelector("#setupCard").hidden = connected || !authSession.user;
  document.querySelector("#appContent").hidden = !connected;
}

function setAuthMode(isSignup) {
  signupMode = isSignup;
  document.querySelector("#signupFields").hidden = !isSignup;
  document.querySelector("#loginTab").classList.toggle("active", !isSignup);
  document.querySelector("#signupTab").classList.toggle("active", isSignup);
  document.querySelector("#authBtn").textContent = isSignup ? "회원가입" : "로그인";
  document.querySelector("#passwordInput").autocomplete = isSignup ? "new-password" : "current-password";
}

async function submitAuth() {
  const payload = {
    username: document.querySelector("#usernameInput").value.trim(),
    password: document.querySelector("#passwordInput").value,
  };
  if (signupMode) {
    payload.displayName = document.querySelector("#displayNameInput").value.trim();
    payload.birthDate = document.querySelector("#birthDateInput").value || null;
    payload.gender = document.querySelector("#genderInput").value;
    payload.regionId = document.querySelector("#regionInput").value;
  }
  try {
    const data = await api(signupMode ? "/api/auth/signup" : "/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.user.role !== "USER") {
      authSession.save(data);
      await logoutSession();
      return toast("관리자 계정은 관제센터 화면에서 로그인해 주세요.");
    }
    authSession.save(data);
    showAuthenticated(data.user);
    toast(signupMode ? "회원가입과 로그인이 완료되었습니다." : "로그인되었습니다.");
    await restoreClient();
  } catch (error) {
    toast(error.message);
  }
}

async function connect() {
  if (!document.querySelector("#locationConsent").checked) {
    return toast("위치 정보 공유에 동의해 주세요.");
  }
  try {
    const data = await api("/api/clients", {
      method: "POST",
      body: JSON.stringify({ deviceId: `web-${Date.now()}` }),
    });
    client = data.client;
    sessionStorage.setItem("rtls-client", JSON.stringify(client));
    setConnected(true);
    startHeartbeat();
    renderClient();
    await locate();
    toast("관제센터에 연결되었습니다.");
  } catch (error) {
    toast(error.message);
  }
}

async function locate() {
  if (!navigator.geolocation) return toast("이 브라우저에서는 위치 기능을 사용할 수 없습니다.");
  navigator.geolocation.getCurrentPosition(position => {
    document.querySelector("#latInput").value = position.coords.latitude.toFixed(5);
    document.querySelector("#lngInput").value = position.coords.longitude.toFixed(5);
    sendLocation(position.coords.accuracy);
  }, () => toast("위치 권한이 없어 입력된 좌표를 사용합니다."), {
    enableHighAccuracy: true,
    timeout: 7000,
  });
}

async function sendLocation(accuracy = 5, quiet = false) {
  if (!client) return;
  try {
    const body = {
      lat: Number(document.querySelector("#latInput").value),
      lng: Number(document.querySelector("#lngInput").value),
      accuracy,
      state: "NORMAL",
      capturedAt: new Date().toISOString(),
    };
    const data = await api(`/api/clients/${client.id}/location`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    client = data.client;
    sessionStorage.setItem("rtls-client", JSON.stringify(client));
    renderClient();
    if (client.dangerState === "DANGER" && !lastDanger) showDanger();
    lastDanger = client.dangerState === "DANGER";
    if (!quiet) toast("현재 위치를 전송했습니다.");
  } catch (error) {
    handleClientError(error);
  }
}

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(async () => {
    if (!client) return;
    try {
      const data = await api(`/api/clients/${client.id}/heartbeat`, {
        method: "POST",
        body: "{}",
      });
      client = data.client;
      sessionStorage.setItem("rtls-client", JSON.stringify(client));
    } catch (error) {
      handleClientError(error, true);
    }
  }, 15000);
}

function stopHeartbeat() {
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function startAutoShare() {
  if (!client || !navigator.geolocation) {
    document.querySelector("#autoShare").checked = false;
    return toast("이 브라우저에서는 자동 위치 공유를 사용할 수 없습니다.");
  }
  if (locationWatchId !== null) return;
  locationWatchId = navigator.geolocation.watchPosition(position => {
    document.querySelector("#latInput").value = position.coords.latitude.toFixed(5);
    document.querySelector("#lngInput").value = position.coords.longitude.toFixed(5);
    sendLocation(position.coords.accuracy, true);
  }, () => {
    stopAutoShare();
    document.querySelector("#autoShare").checked = false;
    toast("위치 권한이 없어 자동 공유를 중지했습니다.");
  }, { enableHighAccuracy: true, maximumAge: 10000, timeout: 15000 });
  toast("자동 위치 공유를 시작했습니다.");
}

function stopAutoShare() {
  if (locationWatchId !== null && navigator.geolocation) {
    navigator.geolocation.clearWatch(locationWatchId);
  }
  locationWatchId = null;
}

function renderClient() {
  document.querySelector("#clientId").textContent = client?.id || "-";
  document.querySelector("#clientRegion").textContent = regionName(client?.regionId);
  const age = calculateAge(client?.birthDate);
  document.querySelector("#clientAge").textContent = age === null ? "-" : `만 ${age}세`;
  document.querySelector("#clientGender").textContent = genderLabel(client?.gender);
  document.querySelector("#lastUpdate").textContent = ago(client?.updatedAt);
  const danger = client?.dangerState === "DANGER";
  const hero = document.querySelector("#hero");
  hero.classList.toggle("danger", danger);
  hero.classList.toggle("safe", !danger);
  document.querySelector(".shield").textContent = danger ? "!" : "✓";
  document.querySelector("#statusTitle").textContent = danger ? "위험 지역입니다" : "현재 안전합니다";
  document.querySelector("#statusMessage").textContent = danger
    ? "안전한 장소로 즉시 이동하세요."
    : "위치 정보를 관제센터와 공유하고 있습니다.";
}

function showDanger() {
  document.querySelector("#dangerAreaName").textContent = client.dangerArea?.name || "위험 구역";
  document.querySelector("#dangerModal").hidden = false;
  if (navigator.vibrate) navigator.vibrate([250, 120, 250]);
}

async function sendSos() {
  if (!client) return;
  try {
    await api(`/api/clients/${client.id}/sos`, {
      method: "POST",
      body: JSON.stringify({ message: "사용자 앱 긴급 구조 요청" }),
    });
    toast("SOS가 접수되었습니다. 구조 요원의 연락을 기다려 주세요.");
    if (navigator.vibrate) navigator.vibrate([100, 80, 100]);
  } catch (error) {
    handleClientError(error);
  }
}

function handleClientError(error, quiet = false) {
  if ([401, 403, 404].includes(error.status)) {
    clearClient();
    if (error.status === 401) {
      authSession.clear();
      showAuthenticated(null);
    }
  }
  if (!quiet) toast(error.message);
}

function startHold(event) {
  event.preventDefault();
  holdStarted = performance.now();
  const progress = document.querySelector("#sosProgress");
  const animate = current => {
    const ratio = Math.min(1, (current - holdStarted) / 3000);
    progress.style.height = `${ratio * 100}%`;
    if (ratio < 1) holdFrame = requestAnimationFrame(animate);
  };
  holdFrame = requestAnimationFrame(animate);
  holdTimer = setTimeout(() => {
    cancelHold();
    sendSos();
  }, 3000);
}

function cancelHold() {
  clearTimeout(holdTimer);
  cancelAnimationFrame(holdFrame);
  document.querySelector("#sosProgress").style.height = "0";
}

async function disconnect() {
  if (!client) return;
  try {
    await api(`/api/clients/${client.id}/disconnect`, {
      method: "POST",
      body: "{}",
    });
  } catch (_) {}
  clearClient();
  toast("위치 공유 연결을 종료했습니다.");
}

async function logout() {
  if (client) await disconnect();
  await logoutSession();
  showAuthenticated(null);
  setConnected(false);
  toast("로그아웃되었습니다.");
}

async function restoreClient() {
  if (!authSession.user) return;
  const stored = JSON.parse(sessionStorage.getItem("rtls-client") || "null");
  if (!stored?.id) return;
  try {
    const data = await api(`/api/clients/${stored.id}/heartbeat`, {
      method: "POST",
      body: "{}",
    });
    client = data.client;
    lastDanger = client.dangerState === "DANGER";
    setConnected(true);
    startHeartbeat();
    renderClient();
  } catch (_) {
    clearClient();
  }
}

document.querySelector("#loginTab").onclick = () => setAuthMode(false);
document.querySelector("#signupTab").onclick = () => setAuthMode(true);
document.querySelector("#authBtn").onclick = submitAuth;
document.querySelector("#logoutBtn").onclick = logout;
document.querySelector("#connectBtn").onclick = connect;
document.querySelector("#locateBtn").onclick = locate;
document.querySelector("#sendBtn").onclick = () => sendLocation();
document.querySelector("#simulateBtn").onclick = () => {
  document.querySelector("#latInput").value = "37.49790";
  document.querySelector("#lngInput").value = "127.02760";
  sendLocation();
};
document.querySelector("#confirmDanger").onclick = () => {
  document.querySelector("#dangerModal").hidden = true;
};
document.querySelector("#disconnectBtn").onclick = disconnect;
document.querySelector("#autoShare").onchange = event => {
  if (event.target.checked) startAutoShare();
  else {
    stopAutoShare();
    toast("자동 위치 공유를 중지했습니다.");
  }
};
const sosButton = document.querySelector("#sosBtn");
sosButton.addEventListener("pointerdown", startHold);
["pointerup", "pointerleave", "pointercancel"].forEach(name => {
  sosButton.addEventListener(name, cancelHold);
});
setInterval(renderClient, 1000);

async function initialize() {
  regions = await loadRegions([document.querySelector("#regionInput")]);
  document.querySelector("#birthDateInput").max = new Date().toISOString().slice(0, 10);
  if (authSession.token) {
    try {
      const data = await api("/api/auth/me");
      if (data.user.role !== "USER") throw new Error("관리자 계정");
      authSession.user = data.user;
    } catch (_) {
      authSession.clear();
    }
  }
  showAuthenticated(authSession.user);
  setConnected(false);
  await restoreClient();
}

initialize();
