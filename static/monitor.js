let snapshot = { clients: [], dangerAreas: [], sosEvents: [], timeline: [] };
let selectedId = null;
let selectedRoute = [];

function setStreamConnected(connected) {
  const pill = document.querySelector("#streamPill");
  pill.innerHTML = `<i class="status-dot ${connected ? "" : "offline"}"></i> ${connected ? "실시간 연결" : "재연결 중"}`;
}

const bounds = { minLat: 37.47, maxLat: 37.55, minLng: 126.96, maxLng: 127.07 };
const project = (lat, lng) => ({
  x: ((lng - bounds.minLng) / (bounds.maxLng - bounds.minLng)) * 100,
  y: (1 - (lat - bounds.minLat) / (bounds.maxLat - bounds.minLat)) * 100,
});
const hasOpenSos = id => snapshot.sosEvents.some(event => event.clientId === id && ["OPEN", "ACKNOWLEDGED"].includes(event.status));
const isLocationStale = client => {
  if (!client.location?.capturedAt) return false;
  return Date.now() - new Date(client.location.capturedAt).getTime() > 60000;
};

async function refresh() {
  try {
    snapshot = await api("/api/state");
    if (!selectedId && snapshot.clients.length) selectedId = snapshot.clients[0].id;
    render();
  } catch (error) { toast(error.message); }
}

function render() {
  const online = snapshot.clients.filter(c => c.connectionStatus === "ONLINE");
  const danger = snapshot.clients.filter(c => c.dangerState === "DANGER");
  const openSos = snapshot.sosEvents.filter(e => ["OPEN", "ACKNOWLEDGED"].includes(e.status));
  document.querySelector("#onlineCount").textContent = online.length;
  document.querySelector("#dangerCount").textContent = danger.length;
  document.querySelector("#sosCount").textContent = openSos.length;
  document.querySelector("#eventCount").textContent = snapshot.timeline.length;
  document.querySelector("#alertBadge").textContent = openSos.length + danger.length;
  renderMap();
  renderAlerts(openSos, danger);
  renderDetail();
  renderTable();
  renderTimeline();
}

function renderMap() {
  const areas = document.querySelector("#areas");
  areas.innerHTML = snapshot.dangerAreas.map(area => {
    const p = project(area.lat, area.lng);
    const size = Math.max(70, area.radius / 5);
    return `<div class="danger-area" style="left:${p.x}%;top:${p.y}%;width:${size}px;height:${size}px"><label>${escapeHtml(area.name)}</label></div>`;
  }).join("");
  document.querySelector("#markers").innerHTML = snapshot.clients.filter(c => c.location).map(client => {
    const p = project(client.location.lat, client.location.lng);
    const state = hasOpenSos(client.id)
      ? "sos"
      : client.connectionStatus === "OFFLINE" || isLocationStale(client)
        ? "offline"
        : client.dangerState === "DANGER" ? "danger" : "";
    return `<button class="marker ${state}" style="left:${p.x}%;top:${p.y}%" data-id="${client.id}" data-label="${escapeHtml(client.name)}" aria-label="${escapeHtml(client.name)}"></button>`;
  }).join("");
  document.querySelectorAll(".marker").forEach(marker => marker.onclick = () => selectClient(marker.dataset.id));
  const points = selectedRoute.map(point => {
    const p = project(point.lat, point.lng);
    return `${p.x * 10},${p.y * 6.2}`;
  }).join(" ");
  document.querySelector("#routeLayer").innerHTML = points ? `<polyline points="${points}"/>` : "";
}

function renderAlerts(sosEvents, dangerClients) {
  const sos = sosEvents.map(event => `
    <article class="alert-card sos" data-client="${event.clientId}">
      <div class="alert-top"><b>SOS · ${escapeHtml(event.status)}</b><span>${ago(event.createdAt)}</span></div>
      <h3>${escapeHtml(event.clientName)} 긴급 구조 요청</h3><p>${escapeHtml(event.message)}</p>
    </article>`).join("");
  const sosClients = new Set(sosEvents.map(e => e.clientId));
  const danger = dangerClients.filter(c => !sosClients.has(c.id)).map(client => `
    <article class="alert-card" data-client="${client.id}">
      <div class="alert-top"><b>DANGER</b><span>${ago(client.updatedAt)}</span></div>
      <h3>${escapeHtml(client.name)} 위험 지역 진입</h3><p>${escapeHtml(client.dangerArea?.name || "위험 구역")}</p>
    </article>`).join("");
  document.querySelector("#alerts").innerHTML = sos + danger || `<p class="empty">활성 알림이 없습니다.</p>`;
  document.querySelectorAll(".alert-card").forEach(card => card.onclick = () => selectClient(card.dataset.client));
}

function renderDetail() {
  const client = snapshot.clients.find(item => item.id === selectedId);
  const target = document.querySelector("#clientDetail");
  if (!client) { target.innerHTML = `<p class="empty">지도에서 사용자를 선택하세요.</p>`; return; }
  const sos = snapshot.sosEvents.find(e => e.clientId === client.id && ["OPEN", "ACKNOWLEDGED"].includes(e.status));
  target.innerHTML = `
    <div class="client-identity"><div class="avatar">${escapeHtml(client.name.slice(0,1))}</div><div><b>${escapeHtml(client.name)}</b><span>${client.id} · ${client.connectionStatus}</span></div></div>
    <div class="detail-grid">
      <div><label>안전 상태</label><strong class="state-text ${client.dangerState.toLowerCase()}">${client.dangerState}</strong></div>
      <div><label>최근 갱신</label><strong>${ago(client.updatedAt)}</strong></div>
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
  if (sos?.status === "OPEN") document.querySelector("#ackBtn").onclick = () => updateSos(sos.id, "ACKNOWLEDGED");
  if (sos?.status === "ACKNOWLEDGED") document.querySelector("#resolveBtn").onclick = () => updateSos(sos.id, "RESOLVED");
}

function renderTable() {
  const query = document.querySelector("#search").value.trim().toLowerCase();
  const clients = snapshot.clients.filter(c => !query || `${c.id} ${c.name}`.toLowerCase().includes(query));
  document.querySelector("#clientsTable").innerHTML = clients.map(client => `
    <tr data-id="${client.id}">
      <td><b>${escapeHtml(client.name)}</b><br><span class="muted">${client.id}</span></td>
      <td>${client.connectionStatus}${isLocationStale(client) ? `<br><span class="stale-text">STALE LOCATION</span>` : ""}</td>
      <td><b class="state-text ${client.dangerState.toLowerCase()}">${client.dangerState}</b></td>
      <td>${ago(client.updatedAt)}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="empty">사용자가 없습니다.</td></tr>`;
  document.querySelectorAll("#clientsTable tr[data-id]").forEach(row => row.onclick = () => selectClient(row.dataset.id));
}

function renderTimeline() {
  document.querySelector("#timeline").innerHTML = snapshot.timeline.map(event => `
    <div class="time-item ${event.severity === "CRITICAL" ? "critical" : ""}">
      <b>${escapeHtml(event.title)}</b><span>${timeOnly(event.createdAt)} · ${escapeHtml(event.clientId || "SYSTEM")}</span>
    </div>`).join("") || `<p class="empty">아직 이벤트가 없습니다.</p>`;
}

function selectClient(id) { selectedId = id; selectedRoute = []; render(); }
async function loadRoute() {
  const data = await api(`/api/clients/${selectedId}/route`);
  selectedRoute = data.route;
  renderMap();
  toast(`이동 경로 ${selectedRoute.length}개 지점을 표시했습니다.`);
}
async function updateSos(id, status) {
  try {
    await api(`/api/sos/${id}`, { method: "POST", body: JSON.stringify({ status, operator: "관제 요원" }) });
    toast(status === "ACKNOWLEDGED" ? "구조 요청을 접수했습니다." : "구조 처리를 완료했습니다.");
    await refresh();
  } catch (error) { toast(error.message); }
}

document.querySelector("#search").addEventListener("input", renderTable);
setInterval(() => {
  document.querySelector("#clock").textContent = new Date().toLocaleString("ko-KR");
  renderTable(); renderDetail();
}, 1000);
const events = new EventSource("/api/events");
events.addEventListener("connected", () => setStreamConnected(true));
events.addEventListener("update", refresh);
events.onerror = () => setStreamConnected(false);
setInterval(refresh, 10000);
refresh();
