let snapshot = { clients: [], dangerAreas: [], sosEvents: [], timeline: [], regions: [] };
let regions = [];
let selectedId = null;
let selectedRoute = [];
let selectedRegion = "";
let events = null;
let clientById = new Map();
let openSosByClient = new Map();
let openSosClientIds = new Set();
let regionById = new Map();
let refreshInFlight = false;
let refreshQueued = false;
let refreshTimer = null;

const bounds = { minLat: 32.9, maxLat: 38.8, minLng: 125.4, maxLng: 130.4 };
const MAX_MAP_MARKERS = 500;
const MAX_TABLE_ROWS = 300;
const MAX_ALERTS = 100;
const mainlandOutline = [
  [38.62, 126.10], [38.58, 126.42], [38.64, 126.82], [38.62, 127.18],
  [38.61, 127.58], [38.62, 127.98], [38.55, 128.28], [38.38, 128.45],
  [38.20, 128.58], [37.98, 128.65], [37.78, 128.82], [37.58, 129.05],
  [37.30, 129.20], [37.02, 129.31], [36.72, 129.42], [36.38, 129.45],
  [36.08, 129.43], [35.78, 129.38], [35.54, 129.30], [35.31, 129.22],
  [35.12, 129.10], [34.98, 128.92], [34.86, 128.68], [34.78, 128.42],
  [34.72, 128.12], [34.67, 127.85], [34.58, 127.58], [34.55, 127.32],
  [34.50, 127.08], [34.45, 126.85], [34.40, 126.62], [34.47, 126.42],
  [34.59, 126.23], [34.72, 126.08], [34.87, 126.18], [35.02, 126.02],
  [35.18, 126.12], [35.34, 126.02], [35.52, 126.20], [35.72, 126.30],
  [35.92, 126.46], [36.12, 126.55], [36.34, 126.60], [36.55, 126.68],
  [36.77, 126.78], [36.98, 126.66], [37.18, 126.73], [37.38, 126.66],
  [37.56, 126.77], [37.73, 126.62], [37.92, 126.68], [38.10, 126.56],
  [38.28, 126.45], [38.45, 126.27],
];
const islands = [
  [[33.57, 126.10], [33.62, 126.35], [33.60, 126.63], [33.50, 126.84], [33.40, 126.70], [33.36, 126.42], [33.40, 126.18]],
  [[34.55, 127.68], [34.64, 127.75], [34.57, 127.84], [34.49, 127.78]],
  [[34.75, 128.00], [34.82, 128.10], [34.76, 128.18], [34.68, 128.09]],
  [[35.02, 128.68], [35.10, 128.75], [35.04, 128.84], [34.96, 128.78]],
];
const regionLabelOffsets = {
  "KR-11": { dx: 6, dy: -24 },
  "KR-28": { dx: -52, dy: 10 },
  "KR-41": { dx: 50, dy: 10 },
  "KR-36": { dx: -30, dy: 22 },
  "KR-30": { dx: 30, dy: 24 },
  "KR-43": { dx: 30, dy: -16 },
  "KR-44": { dx: -38, dy: 6 },
  "KR-27": { dx: -20, dy: 22 },
  "KR-31": { dx: 36, dy: 4 },
  "KR-26": { dx: 24, dy: 28 },
  "KR-29": { dx: -18, dy: 18 },
  "KR-48": { dx: 0, dy: 24 },
  "KR-50": { dx: 0, dy: 8 },
};
const project = (lat, lng) => ({
  x: ((lng - bounds.minLng) / (bounds.maxLng - bounds.minLng)) * 100,
  y: (1 - (lat - bounds.minLat) / (bounds.maxLat - bounds.minLat)) * 100,
});
const hasOpenSos = id => openSosClientIds.has(id);
const isLocationStale = client => {
  if (!client.location?.capturedAt) return false;
  return Date.now() - new Date(client.location.capturedAt).getTime() > 60000;
};
const regionName = id => regionById.get(id)?.name || id || "미지정";

const polygonPoints = coordinates => coordinates.map(([lat, lng]) => {
  const point = project(lat, lng);
  return `${(point.x * 10).toFixed(1)},${(point.y * 6.2).toFixed(1)}`;
}).join(" ");

function renderGeography() {
  const mainland = `<polygon class="land" points="${polygonPoints(mainlandOutline)}"/>`;
  const islandShapes = islands.map(
    coordinates => `<polygon class="island" points="${polygonPoints(coordinates)}"/>`
  ).join("");
  const border = polygonPoints(mainlandOutline.slice(0, 8));
  document.querySelector("#geographyLayer").innerHTML =
    `${mainland}${islandShapes}<polyline class="border" points="${border}"/>`;
}

function rebuildIndexes() {
  clientById = new Map(snapshot.clients.map(client => [client.id, client]));
  const openEvents = snapshot.sosEvents.filter(
    event => ["OPEN", "ACKNOWLEDGED"].includes(event.status)
  );
  openSosByClient = new Map(openEvents.map(event => [event.clientId, event]));
  openSosClientIds = new Set(openSosByClient.keys());
}

function setStreamConnected(connected) {
  const pill = document.querySelector("#streamPill");
  pill.innerHTML = `<i class="status-dot ${connected ? "" : "offline"}"></i> ${connected ? "실시간 연결" : "재연결 중"}`;
}

function showLogin(show) {
  document.querySelector("#authOverlay").hidden = !show;
  document.querySelector(".shell").classList.toggle("locked", show);
}

async function login(event) {
  event.preventDefault();
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.querySelector("#loginUsername").value.trim(),
        password: document.querySelector("#loginPassword").value,
      }),
    });
    if (!["NATIONAL_ADMIN", "REGIONAL_OPERATOR"].includes(data.user.role)) {
      authSession.save(data);
      await logoutSession();
      throw new Error("일반 사용자 계정은 사용자 앱에서 로그인해 주세요.");
    }
    authSession.save(data);
    await startDashboard();
  } catch (error) {
    toast(error.message);
  }
}

async function logout() {
  if (events) events.close();
  events = null;
  await logoutSession();
  snapshot = { clients: [], dangerAreas: [], sosEvents: [], timeline: [], regions: [] };
  rebuildIndexes();
  render();
  showLogin(true);
  toast("관제센터에서 로그아웃되었습니다.");
}

async function startDashboard() {
  const user = authSession.user;
  document.querySelector("#operatorName").textContent = user.displayName;
  const filter = document.querySelector("#regionFilter");
  if (user.role === "NATIONAL_ADMIN") {
    filter.hidden = false;
    document.querySelector("#operatorPanel").hidden = false;
    selectedRegion = filter.value;
    await loadOperators();
  } else {
    filter.hidden = true;
    document.querySelector("#operatorPanel").hidden = true;
    selectedRegion = user.regionId;
  }
  showLogin(false);
  connectEvents();
  await refresh();
}

function connectEvents() {
  if (events) events.close();
  events = new EventSource(`/api/events?token=${encodeURIComponent(authSession.token)}`);
  events.addEventListener("connected", () => setStreamConnected(true));
  events.addEventListener("update", () => scheduleRefresh());
  events.onerror = () => setStreamConnected(false);
}

async function refresh() {
  if (!authSession.token) return;
  if (refreshInFlight) {
    refreshQueued = true;
    return;
  }
  refreshInFlight = true;
  try {
    const query = selectedRegion ? `?region=${encodeURIComponent(selectedRegion)}` : "";
    snapshot = await api(`/api/state${query}`);
    rebuildIndexes();
    if (selectedId && !clientById.has(selectedId)) {
      selectedId = null;
      selectedRoute = [];
    }
    if (!selectedId && snapshot.clients.length) selectedId = snapshot.clients[0].id;
    render();
  } catch (error) {
    if (error.status === 401) {
      authSession.clear();
      showLogin(true);
    }
    toast(error.message);
  } finally {
    refreshInFlight = false;
    if (refreshQueued) {
      refreshQueued = false;
      scheduleRefresh();
    }
  }
}

function scheduleRefresh(delay = 500) {
  if (refreshTimer) {
    if (delay > 0) return;
    clearTimeout(refreshTimer);
  }
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    refresh();
  }, delay);
}

function render() {
  let onlineCount = 0;
  const danger = [];
  for (const client of snapshot.clients) {
    onlineCount += client.connectionStatus === "ONLINE";
    if (client.dangerState === "DANGER") danger.push(client);
  }
  const openSos = [...openSosByClient.values()];
  document.querySelector("#onlineCount").textContent = onlineCount;
  document.querySelector("#dangerCount").textContent = danger.length;
  document.querySelector("#sosCount").textContent = openSos.length;
  document.querySelector("#eventCount").textContent = snapshot.timeline.length;
  document.querySelector("#alertBadge").textContent = openSos.length + danger.length;
  document.querySelector("#mapTitle").textContent = selectedRegion
    ? `${regionName(selectedRegion)} 지역 관제 지도`
    : "대한민국 통합 관제 지도";
  renderMap();
  renderAlerts(openSos, danger);
  renderDetail();
  renderTable();
  renderTimeline();
  updateRelativeTimes();
}

function renderMap() {
  document.querySelector("#regionMarkers").innerHTML = (snapshot.regions || []).map(region => {
    const point = project(region.lat, region.lng);
    const level = region.sos ? "sos" : region.danger ? "danger" : "";
    const offset = regionLabelOffsets[region.id] || { dx: 0, dy: 0 };
    return `
      <i class="region-anchor" style="left:${point.x}%;top:${point.y}%"></i>
      <button class="region-marker ${level}"
        style="left:${point.x}%;top:${point.y}%;--dx:${offset.dx}px;--dy:${offset.dy}px"
        data-region="${region.id}" title="${escapeHtml(region.name)}">
        <b>${escapeHtml(region.name.replace(/(특별자치도|특별자치시|특별시|광역시|도)$/,""))}</b>
        <span>${region.online}/${region.total}</span>
      </button>`;
  }).join("");
  document.querySelectorAll(".region-marker").forEach(marker => {
    marker.onclick = () => {
      if (authSession.user.role !== "NATIONAL_ADMIN") return;
      selectedRegion = marker.dataset.region;
      document.querySelector("#regionFilter").value = selectedRegion;
      scheduleRefresh(0);
    };
  });

  const visibleAreas = selectedRegion ? snapshot.dangerAreas : [];
  document.querySelector("#areas").innerHTML = visibleAreas.map(area => {
    const point = project(area.lat, area.lng);
    const size = Math.max(30, Math.min(60, area.radius / 8));
    return `<div class="danger-area" style="left:${point.x}%;top:${point.y}%;width:${size}px;height:${size}px"><label>${escapeHtml(area.name)}</label></div>`;
  }).join("");

  const mapClients = selectedRegion
    ? snapshot.clients.filter(client => client.location).slice(0, MAX_MAP_MARKERS)
    : [];
  document.querySelector("#markers").innerHTML = mapClients.map(client => {
    const point = project(client.location.lat, client.location.lng);
    const state = hasOpenSos(client.id)
      ? "sos"
      : client.connectionStatus === "OFFLINE" || isLocationStale(client)
        ? "offline"
        : client.dangerState === "DANGER" ? "danger" : "";
    return `<button class="marker ${state}" style="left:${point.x}%;top:${point.y}%"
      data-id="${client.id}" data-label="${escapeHtml(client.name)}"
      aria-label="${escapeHtml(client.name)}"></button>`;
  }).join("");
  document.querySelectorAll(".marker").forEach(marker => {
    marker.onclick = () => selectClient(marker.dataset.id);
  });

  const points = selectedRoute.map(point => {
    const projected = project(point.lat, point.lng);
    return `${projected.x * 10},${projected.y * 6.2}`;
  }).join(" ");
  document.querySelector("#routeLayer").innerHTML = points
    ? `<polyline points="${points}"/>`
    : "";
}

function renderAlerts(sosEvents, dangerClients) {
  const sos = sosEvents.slice(0, MAX_ALERTS).map(event => `
    <article class="alert-card sos" data-client="${event.clientId}">
      <div class="alert-top"><b>SOS · ${escapeHtml(event.status)}</b><span data-ago="${event.createdAt}">${ago(event.createdAt)}</span></div>
      <h3>${escapeHtml(event.clientName)} 긴급 구조 요청</h3><p>${escapeHtml(event.message)}</p>
    </article>`).join("");
  const danger = dangerClients
    .filter(client => !openSosClientIds.has(client.id))
    .slice(0, Math.max(0, MAX_ALERTS - sosEvents.length))
    .map(client => `
    <article class="alert-card" data-client="${client.id}">
      <div class="alert-top"><b>DANGER</b><span data-ago="${client.updatedAt}">${ago(client.updatedAt)}</span></div>
      <h3>${escapeHtml(client.name)} 위험 지역 진입</h3><p>${escapeHtml(client.dangerArea?.name || "위험 구역")}</p>
    </article>`).join("");
  document.querySelector("#alerts").innerHTML = sos + danger || `<p class="empty">활성 알림이 없습니다.</p>`;
  document.querySelectorAll(".alert-card").forEach(card => {
    card.onclick = () => selectClient(card.dataset.client);
  });
}

function renderDetail() {
  const client = clientById.get(selectedId);
  const target = document.querySelector("#clientDetail");
  if (!client) {
    target.innerHTML = `<p class="empty">지도에서 사용자를 선택하세요.</p>`;
    return;
  }
  const sos = openSosByClient.get(client.id);
  target.innerHTML = `
    <div class="client-identity"><div class="avatar">${escapeHtml(client.name.slice(0,1))}</div><div><b>${escapeHtml(client.name)}</b><span>${client.id} · ${escapeHtml(regionName(client.regionId))}</span></div></div>
    <div class="detail-grid">
      <div><label>안전 상태</label><strong class="state-text ${client.dangerState.toLowerCase()}">${client.dangerState}</strong></div>
      <div><label>최근 갱신</label><strong data-ago="${client.updatedAt}">${ago(client.updatedAt)}</strong></div>
      <div><label>위도</label><strong>${client.location?.lat?.toFixed(5) || "-"}</strong></div>
      <div><label>경도</label><strong>${client.location?.lng?.toFixed(5) || "-"}</strong></div>
      <div><label>위치 정확도</label><strong>${client.location ? `${Math.round(client.location.accuracy || 0)} m` : "-"}</strong></div>
      <div><label>위치 신선도</label><strong class="${isLocationStale(client) ? "stale-text" : ""}">${client.location ? (isLocationStale(client) ? "STALE" : "CURRENT") : "-"}</strong></div>
    </div>
    <div class="detail-actions">
      <button class="btn" id="routeBtn">이동 경로</button>
      ${sos ? sos.status === "OPEN"
        ? `<button class="btn btn-danger" id="ackBtn">구조 접수</button>`
        : `<button class="btn btn-success" id="resolveBtn">구조 완료</button>` : ""}
    </div>`;
  document.querySelector("#routeBtn").onclick = loadRoute;
  if (sos?.status === "OPEN") {
    document.querySelector("#ackBtn").onclick = () => updateSos(sos.id, "ACKNOWLEDGED");
  }
  if (sos?.status === "ACKNOWLEDGED") {
    document.querySelector("#resolveBtn").onclick = () => updateSos(sos.id, "RESOLVED");
  }
}

function renderTable() {
  const query = document.querySelector("#search").value.trim().toLowerCase();
  const matchingClients = snapshot.clients.filter(
    client => !query || `${client.id} ${client.name}`.toLowerCase().includes(query)
  );
  const clients = matchingClients.slice(0, MAX_TABLE_ROWS);
  const overflow = matchingClients.length > clients.length
    ? `<tr><td colspan="4" class="empty">${matchingClients.length - clients.length}명은 검색어 또는 지역 필터로 범위를 줄여 확인하세요.</td></tr>`
    : "";
  document.querySelector("#clientsTable").innerHTML = clients.map(client => `
    <tr data-id="${client.id}">
      <td><b>${escapeHtml(client.name)}</b><br><span class="muted">${client.id} · ${escapeHtml(regionName(client.regionId))}</span></td>
      <td>${client.connectionStatus}${isLocationStale(client) ? `<br><span class="stale-text">STALE LOCATION</span>` : ""}</td>
      <td><b class="state-text ${client.dangerState.toLowerCase()}">${client.dangerState}</b></td>
      <td><span data-ago="${client.updatedAt}">${ago(client.updatedAt)}</span></td>
    </tr>`).join("") + overflow || `<tr><td colspan="4" class="empty">사용자가 없습니다.</td></tr>`;
  document.querySelectorAll("#clientsTable tr[data-id]").forEach(row => {
    row.onclick = () => selectClient(row.dataset.id);
  });
}

function renderTimeline() {
  document.querySelector("#timeline").innerHTML = snapshot.timeline.map(event => `
    <div class="time-item ${event.severity === "CRITICAL" ? "critical" : ""}">
      <b>${escapeHtml(event.title)}</b><span>${timeOnly(event.createdAt)} · ${escapeHtml(event.clientId || "SYSTEM")} · <i data-ago="${event.createdAt}">${ago(event.createdAt)}</i></span>
    </div>`).join("") || `<p class="empty">아직 이벤트가 없습니다.</p>`;
}

function selectClient(id) {
  selectedId = id;
  selectedRoute = [];
  renderMap();
  renderDetail();
}

async function loadRoute() {
  try {
    const data = await api(`/api/clients/${selectedId}/route`);
    selectedRoute = data.route;
    renderMap();
    toast(`이동 경로 ${selectedRoute.length}개 지점을 표시했습니다.`);
  } catch (error) {
    toast(error.message);
  }
}

async function updateSos(id, status) {
  try {
    await api(`/api/sos/${id}`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    toast(status === "ACKNOWLEDGED" ? "구조 요청을 접수했습니다." : "구조 처리를 완료했습니다.");
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

async function loadOperators() {
  const data = await api("/api/operators");
  document.querySelector("#operatorList").innerHTML = data.operators.map(operator => `
    <span><b>${escapeHtml(operator.displayName)}</b> ${escapeHtml(regionName(operator.regionId))} · ${escapeHtml(operator.username)}</span>
  `).join("") || "<span>등록된 지역 관리자가 없습니다.</span>";
}

async function createOperator(event) {
  event.preventDefault();
  try {
    await api("/api/operators", {
      method: "POST",
      body: JSON.stringify({
        username: document.querySelector("#operatorUsername").value.trim(),
        password: document.querySelector("#operatorPassword").value,
        displayName: document.querySelector("#operatorDisplayName").value.trim(),
        regionId: document.querySelector("#operatorRegion").value,
      }),
    });
    event.target.reset();
    await loadOperators();
    toast("지역 관제 관리자 계정을 생성했습니다.");
  } catch (error) {
    toast(error.message);
  }
}

document.querySelector("#monitorLogin").addEventListener("submit", login);
document.querySelector("#logoutBtn").onclick = logout;
document.querySelector("#operatorForm").addEventListener("submit", createOperator);
document.querySelector("#search").addEventListener("input", renderTable);
document.querySelector("#regionFilter").onchange = event => {
  selectedRegion = event.target.value;
  selectedId = null;
  selectedRoute = [];
  scheduleRefresh(0);
};
setInterval(() => {
  document.querySelector("#clock").textContent = new Date().toLocaleString("ko-KR");
  updateRelativeTimes();
}, 1000);
setInterval(() => scheduleRefresh(0), 30000);

function updateRelativeTimes() {
  document.querySelectorAll("[data-ago]").forEach(element => {
    element.textContent = ago(element.dataset.ago);
  });
}

async function initialize() {
  renderGeography();
  regions = await loadRegions([
    document.querySelector("#operatorRegion"),
  ]);
  regionById = new Map(regions.map(region => [region.id, region]));
  const filter = document.querySelector("#regionFilter");
  filter.innerHTML = `<option value="">전국 관제</option>${regions.map(
    region => `<option value="${region.id}">${escapeHtml(region.name)}</option>`
  ).join("")}`;

  if (authSession.token) {
    try {
      const data = await api("/api/auth/me");
      if (!["NATIONAL_ADMIN", "REGIONAL_OPERATOR"].includes(data.user.role)) {
        throw new Error("관제 권한 없음");
      }
      authSession.user = data.user;
      await startDashboard();
      return;
    } catch (_) {
      authSession.clear();
    }
  }
  showLogin(true);
}

initialize();
