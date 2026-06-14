let snapshot = { clients: [], dangerAreas: [], sosEvents: [], timeline: [], regions: [], publicAlerts: [], groups: [], auditLogs: [] };
let regions = [];
let selectedId = null;
let selectedRoute = [];
let selectedRegion = "";
let selectedGroup = "";
let events = null;
let clientById = new Map();
let openSosByClient = new Map();
let openSosClientIds = new Set();
let regionById = new Map();
let refreshInFlight = false;
let refreshQueued = false;
let refreshTimer = null;
let controlMap = null;
let provinceLayer = null;
let regionLayerById = new Map();
let regionStatusLayer = null;
let dangerAreaLayer = null;
let clientMarkerLayer = null;
let routeLayer = null;
let viewportRegion = null;
let mapResizeObserver = null;
let mapResizeFrame = null;

const MAX_MAP_MARKERS = 500;
const MAX_TABLE_ROWS = 300;
const MAX_ALERTS = 100;
const NATIONAL_BOUNDS = [[33.0, 125.7], [38.7, 130.95]];
const KOSTAT_TO_REGION_ID = {
  "11": "KR-11",
  "21": "KR-26",
  "22": "KR-27",
  "23": "KR-28",
  "24": "KR-29",
  "25": "KR-30",
  "26": "KR-31",
  "29": "KR-36",
  "31": "KR-41",
  "32": "KR-42",
  "33": "KR-43",
  "34": "KR-44",
  "35": "KR-45",
  "36": "KR-46",
  "37": "KR-47",
  "38": "KR-48",
  "39": "KR-50",
};
const REGION_LABEL_OFFSETS = {
  "KR-11": [8, -22],
  "KR-28": [-45, 5],
  "KR-41": [48, 8],
  "KR-36": [-30, -18],
  "KR-30": [28, 20],
  "KR-43": [24, -16],
  "KR-44": [-34, 4],
  "KR-27": [-24, 18],
  "KR-31": [34, 2],
  "KR-26": [22, 25],
  "KR-29": [-18, 18],
  "KR-48": [0, 22],
  "KR-50": [0, 8],
};
const hasOpenSos = id => openSosClientIds.has(id);
const isLocationStale = client => {
  if (!client.location?.capturedAt) return false;
  return Date.now() - new Date(client.location.capturedAt).getTime() > 60000;
};
const regionName = id => regionById.get(id)?.name || id || "미지정";
const eventTypeLabel = type => ({
  CONNECT: "접속",
  RECONNECT: "재접속",
  DISCONNECT: "접속 종료",
  TIMEOUT: "응답 지연",
  DANGER: "위험 감지",
  DANGER_ENTER: "위험구역 진입",
  DANGER_EXIT: "위험구역 이탈",
  IMMOBILE: "장시간 무동작",
  LOW_BATTERY: "배터리 부족",
  SOS: "긴급 요청",
  RESCUE: "구조 처리",
  MEMBER_DELETE: "회원 삭제",
}[type] || type || "시스템");
const sosStatusLabel = status => ({
  OPEN: "신규 요청",
  ACKNOWLEDGED: "접수·배정",
  DISPATCHED: "출동 중",
  RESOLVED: "처리 완료",
  CANCELLED: "요청 취소",
}[status] || status || "-");

const todayEvents = () => {
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
  return snapshot.timeline.filter(event =>
    new Date(event.createdAt).toLocaleDateString("en-CA", {
      timeZone: "Asia/Seoul",
    }) === today
  );
};

function provinceStyle(feature) {
  const regionId = KOSTAT_TO_REGION_ID[feature.properties.code];
  const selected = selectedRegion === regionId;
  return {
    color: selected ? "#168c7c" : "#79cdb7",
    weight: selected ? 2.5 : 1.2,
    opacity: selected ? 1 : 0.85,
    fillColor: selected ? "#7fd8b6" : "#c9f1d7",
    fillOpacity: selected ? 0.9 : 0.82,
  };
}

async function initializeMap() {
  const mapElement = document.querySelector("#map");
  controlMap = L.map(mapElement, {
    attributionControl: true,
    zoomControl: true,
    minZoom: 6,
    maxZoom: 18,
    zoomSnap: 0.25,
    preferCanvas: true,
  });
  controlMap.attributionControl.setPrefix(
    '<a href="https://leafletjs.com/" target="_blank" rel="noreferrer">Leaflet</a>'
  );
  controlMap.attributionControl.addAttribution(
    '<a href="https://sgis.kostat.go.kr/" target="_blank" rel="noreferrer">통계청 SGIS (2018)</a>'
  );
  controlMap.createPane("regions");
  controlMap.getPane("regions").style.zIndex = 310;
  controlMap.createPane("status");
  controlMap.getPane("status").style.zIndex = 430;
  controlMap.createPane("clients");
  controlMap.getPane("clients").style.zIndex = 470;

  regionStatusLayer = L.layerGroup().addTo(controlMap);
  dangerAreaLayer = L.layerGroup().addTo(controlMap);
  clientMarkerLayer = L.layerGroup().addTo(controlMap);
  routeLayer = L.layerGroup().addTo(controlMap);
  controlMap.fitBounds(NATIONAL_BOUNDS, { padding: [20, 20], animate: false });
  const refreshMapSize = () => {
    cancelAnimationFrame(mapResizeFrame);
    mapResizeFrame = requestAnimationFrame(() => {
      controlMap?.invalidateSize({ pan: false, debounceMoveend: true });
    });
  };
  if ("ResizeObserver" in window) {
    mapResizeObserver = new ResizeObserver(refreshMapSize);
    mapResizeObserver.observe(mapElement);
  }
  window.addEventListener("resize", refreshMapSize);

  const response = await fetch("/static/data/skorea-provinces-2018-topo-simple.json");
  if (!response.ok) throw new Error("대한민국 지도 경계 데이터를 불러오지 못했습니다.");
  const topology = await response.json();
  const object = topology.objects.skorea_provinces_2018_geo;
  const geojson = topojson.feature(topology, object);
  provinceLayer = L.geoJSON(geojson, {
    pane: "regions",
    style: provinceStyle,
    onEachFeature(feature, layer) {
      const regionId = KOSTAT_TO_REGION_ID[feature.properties.code];
      if (!regionId) return;
      regionLayerById.set(regionId, layer);
      layer.bindTooltip(feature.properties.name, {
        className: "province-tooltip",
        direction: "center",
        sticky: true,
      });
      layer.on({
        click() {
          if (authSession.user?.role !== "NATIONAL_ADMIN") return;
          selectedRegion = regionId;
          document.querySelector("#regionFilter").value = selectedRegion;
          selectedId = null;
          selectedRoute = [];
          scheduleRefresh(0);
        },
        mouseover() {
          layer.setStyle({ fillOpacity: 0.9, weight: 2 });
        },
        mouseout() {
          layer.setStyle(provinceStyle(feature));
        },
      });
    },
  }).addTo(controlMap);
  requestAnimationFrame(() => {
    controlMap.invalidateSize({ pan: false });
    viewportRegion = null;
    syncMapViewport();
  });
}

function syncMapViewport() {
  if (!controlMap || viewportRegion === selectedRegion) return;
  viewportRegion = selectedRegion;
  const selectedLayer = selectedRegion ? regionLayerById.get(selectedRegion) : null;
  const targetBounds = selectedLayer?.getBounds()
    || provinceLayer?.getBounds()
    || L.latLngBounds(NATIONAL_BOUNDS);
  controlMap.fitBounds(targetBounds, {
    padding: selectedRegion ? [34, 34] : [26, 26],
    maxZoom: selectedRegion ? 9 : 7,
    animate: true,
  });
}

function rebuildIndexes() {
  clientById = new Map(snapshot.clients.map(client => [client.id, client]));
  const openEvents = snapshot.sosEvents.filter(
    event => ["OPEN", "ACKNOWLEDGED", "DISPATCHED"].includes(event.status)
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
  closeTodayEvents();
  closeOperatorManager();
  await logoutSession();
  snapshot = { clients: [], dangerAreas: [], sosEvents: [], timeline: [], regions: [], publicAlerts: [], groups: [], auditLogs: [] };
  rebuildIndexes();
  render();
  showLogin(true);
  toast("관제센터에서 로그아웃되었습니다.");
}

async function startDashboard() {
  const user = authSession.user;
  document.querySelector("#operatorName").textContent = user.displayName;
  const filter = document.querySelector("#regionFilter");
  const operatorMenuButton = document.querySelector("#operatorMenuBtn");
  if (user.role === "NATIONAL_ADMIN") {
    filter.hidden = false;
    operatorMenuButton.hidden = false;
    selectedRegion = filter.value;
  } else {
    filter.hidden = true;
    operatorMenuButton.hidden = true;
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
  const todayEventCount = todayEvents().length;
  for (const client of snapshot.clients) {
    onlineCount += client.connectionStatus === "ONLINE";
    if (client.dangerState === "DANGER") danger.push(client);
  }
  const openSos = [...openSosByClient.values()];
  const publicAlerts = snapshot.publicAlerts || [];
  const deviceWarnings = snapshot.clients.flatMap(client => {
    const warnings = [];
    if (client.warnings?.signalLost) warnings.push({ client, type: "신호 끊김", severity: "WARNING", createdAt: client.lastSeenAt });
    if (client.warnings?.lowBattery) warnings.push({ client, type: "배터리 부족", severity: "WARNING", createdAt: client.updatedAt });
    if (client.warnings?.immobile) warnings.push({ client, type: "장시간 움직임 없음", severity: "WARNING", createdAt: client.movement?.lastMovedAt });
    return warnings;
  });
  document.querySelector("#onlineCount").textContent = onlineCount;
  document.querySelector("#dangerCount").textContent = danger.length;
  document.querySelector("#sosCount").textContent = openSos.length;
  document.querySelector("#eventCount").textContent = todayEventCount;
  document.querySelector("#alertBadge").textContent = openSos.length + danger.length + publicAlerts.length + deviceWarnings.length;
  const sourceStatus = document.querySelector("#publicAlertStatus");
  sourceStatus.textContent = snapshot.publicAlertStatus?.message || "공공데이터 상태 미확인";
  sourceStatus.classList.toggle("connected", Boolean(snapshot.publicAlertStatus?.connected));
  const notificationStatus = document.querySelector("#notificationStatus");
  const webhook = snapshot.notificationStatus || {};
  notificationStatus.textContent = webhook.enabled
    ? webhook.lastError
      ? `n8n 오류 · ${webhook.lastError}`
      : `n8n 연결 · ${webhook.delivered || 0}건 전달`
    : "n8n Webhook 미설정";
  notificationStatus.classList.toggle("connected", Boolean(webhook.enabled && !webhook.lastError));
  document.querySelector("#mapTitle").textContent = selectedRegion
    ? `${regionName(selectedRegion)} 지역 관제 지도`
    : "대한민국 통합 관제 지도";
  const groupFilter = document.querySelector("#groupFilter");
  const availableGroups = snapshot.groups || [];
  if (selectedGroup && !availableGroups.some(group => group.id === selectedGroup)) {
    selectedGroup = "";
  }
  groupFilter.innerHTML = `<option value="">전체 그룹</option>${availableGroups.map(
    group => `<option value="${group.id}" ${group.id === selectedGroup ? "selected" : ""}>${escapeHtml(group.name)}</option>`
  ).join("")}`;
  renderMap();
  renderAlerts(openSos, danger, publicAlerts, deviceWarnings);
  renderDetail();
  renderTable();
  renderTimeline();
  updateRelativeTimes();
}

function renderMap() {
  if (!controlMap) return;
  provinceLayer?.setStyle(provinceStyle);
  regionStatusLayer.clearLayers();
  dangerAreaLayer.clearLayers();
  clientMarkerLayer.clearLayers();
  routeLayer.clearLayers();

  (snapshot.regions || []).forEach(region => {
    const level = region.sos || region.publicSeverity === "CRITICAL"
      ? "sos"
      : region.danger || region.publicSeverity === "WARNING"
        ? "danger"
        : "";
    const [offsetX, offsetY] = REGION_LABEL_OFFSETS[region.id] || [0, 0];
    const label = L.marker([region.lat, region.lng], {
      pane: "status",
      interactive: true,
      icon: L.divIcon({
        className: "region-status-icon",
        iconSize: null,
        html: `<button class="region-marker ${level}" type="button"
          style="--offset-x:${offsetX}px;--offset-y:${offsetY}px"
          title="${escapeHtml(region.name)}">
        <b>${escapeHtml(region.name.replace(/(특별자치도|특별자치시|특별시|광역시|도)$/,""))}</b>
        <span>${region.online}/${region.total}${region.publicAlerts ? ` · 알림 ${region.publicAlerts}` : ""}</span>
      </button>`,
      }),
    }).addTo(regionStatusLayer);
    label.on("click", () => {
      if (authSession.user.role !== "NATIONAL_ADMIN") return;
      selectedRegion = region.id;
      document.querySelector("#regionFilter").value = selectedRegion;
      selectedId = null;
      selectedRoute = [];
      scheduleRefresh(0);
    });
  });

  const visibleAreas = selectedRegion ? snapshot.dangerAreas : [];
  visibleAreas.forEach(area => {
    const layer = area.shape === "POLYGON"
      ? L.polygon(area.points.map(point => [point.lat, point.lng]), {
        pane: "status",
        className: "danger-area",
        color: "#ff5d6c",
        fillColor: "#ff5d6c",
        fillOpacity: 0.14,
        weight: 1.5,
      })
      : L.circle([area.lat, area.lng], {
      pane: "status",
      radius: area.radius,
      className: "danger-area",
      color: "#ff5d6c",
      fillColor: "#ff5d6c",
      fillOpacity: 0.14,
      weight: 1.5,
    });
    layer.bindTooltip(area.name, {
      className: "danger-tooltip",
      direction: "bottom",
      permanent: true,
      offset: [0, 8],
    }).addTo(dangerAreaLayer);
  });

  const mapClients = selectedRegion
    ? snapshot.clients
      .filter(client => client.location)
      .filter(client => !selectedGroup || (client.groupIds || []).includes(selectedGroup))
      .slice(0, MAX_MAP_MARKERS)
    : [];
  mapClients.forEach(client => {
    const group = (snapshot.groups || []).find(item => (client.groupIds || []).includes(item.id));
    const state = hasOpenSos(client.id)
      ? "sos"
      : client.connectionStatus === "OFFLINE" || isLocationStale(client)
        ? "offline"
        : client.dangerState === "DANGER" ? "danger" : "";
    const marker = L.marker([client.location.lat, client.location.lng], {
      pane: "clients",
      icon: L.divIcon({
        className: "client-map-icon",
        iconSize: [24, 24],
        iconAnchor: [12, 12],
        html: `<button class="marker ${state} ${group ? "grouped" : ""}" ${group ? `style="--group-color:${escapeHtml(group.color)}"` : ""} type="button" aria-label="${escapeHtml(client.name)}"></button>`,
      }),
    }).bindTooltip(client.name, {
      className: "client-tooltip",
      direction: "bottom",
      offset: [0, 12],
      permanent: true,
    }).addTo(clientMarkerLayer);
    marker.on("click", () => selectClient(client.id));
  });

  if (selectedRoute.length) {
    L.polyline(selectedRoute.map(point => [point.lat, point.lng]), {
      pane: "clients",
      color: "#52c8ff",
      weight: 4,
      opacity: 0.9,
      dashArray: "8 7",
      className: "client-route",
    }).addTo(routeLayer);
  }
  syncMapViewport();
}

function renderAlerts(sosEvents, dangerClients, publicAlerts, deviceWarnings) {
  const severityFilter = document.querySelector("#alertSeverity").value;
  const typeFilter = document.querySelector("#alertType").value;
  const hours = Number(document.querySelector("#alertTime").value || 0);
  const recent = createdAt => !hours || Date.now() - new Date(createdAt).getTime() <= hours * 3600000;
  const allowed = (severity, type, createdAt) =>
    (!severityFilter || severity === severityFilter)
    && (!typeFilter || type === typeFilter)
    && recent(createdAt);
  const publicCards = publicAlerts.filter(alert => allowed(alert.severity, "PUBLIC", alert.issuedAt)).slice(0, MAX_ALERTS).map(alert => `
    <article class="alert-card public ${alert.severity.toLowerCase()}">
      <div class="alert-top"><b>${escapeHtml(alert.source)} · ${escapeHtml(alert.severity)}</b><span data-ago="${alert.issuedAt}">${ago(alert.issuedAt)}</span></div>
      <h3>${escapeHtml(alert.title)}</h3>
      <p>${escapeHtml(alert.message || regionName(alert.regionId))}</p>
    </article>`).join("");
  const sos = sosEvents.filter(event => allowed("CRITICAL", "SOS", event.createdAt)).slice(0, MAX_ALERTS).map(event => `
    <article class="alert-card sos" data-client="${event.clientId}">
      <div class="alert-top"><b>SOS · ${escapeHtml(sosStatusLabel(event.status))}</b><span data-ago="${event.createdAt}">${ago(event.createdAt)}</span></div>
      <h3>${escapeHtml(event.clientName)} 긴급 구조 요청</h3><p>${escapeHtml(event.message)}</p>
      ${event.operator ? `<small class="alert-assignee">담당 ${escapeHtml(event.operator)}</small>` : ""}
    </article>`).join("");
  const danger = dangerClients
    .filter(client => !openSosClientIds.has(client.id))
    .filter(client => allowed(client.dangerArea?.severity >= 5 ? "CRITICAL" : "WARNING", "DANGER", client.updatedAt))
    .slice(0, Math.max(0, MAX_ALERTS - sosEvents.length))
    .map(client => `
    <article class="alert-card" data-client="${client.id}">
      <div class="alert-top"><b>DANGER</b><span data-ago="${client.updatedAt}">${ago(client.updatedAt)}</span></div>
      <h3>${escapeHtml(client.name)} 위험 지역 진입</h3><p>${escapeHtml(client.dangerArea?.name || "위험 구역")}</p>
    </article>`).join("");
  const devices = deviceWarnings
    .filter(item => allowed(item.severity, "DEVICE", item.createdAt))
    .map(item => `
      <article class="alert-card device" data-client="${item.client.id}">
        <div class="alert-top"><b>DEVICE · ${item.severity}</b><span data-ago="${item.createdAt}">${ago(item.createdAt)}</span></div>
        <h3>${escapeHtml(item.client.name)} ${escapeHtml(item.type)}</h3>
        <p>${item.type === "배터리 부족" ? `잔량 ${item.client.batteryLevel}%` : "즉시 상태를 확인하세요."}</p>
      </article>`).join("");
  document.querySelector("#alerts").innerHTML = publicCards + sos + danger + devices || `<p class="empty">조건에 맞는 활성 알림이 없습니다.</p>`;
  document.querySelectorAll(".alert-card[data-client]").forEach(card => {
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
  const age = calculateAge(client.birthDate);
  const sosHistory = sos?.history || [];
  target.innerHTML = `
    <div class="client-identity"><div class="avatar">${escapeHtml(client.name.slice(0,1))}</div><div><b>${escapeHtml(client.name)}</b><span>${client.id} · ${escapeHtml(regionName(client.regionId))} · ${age === null ? "연령 미입력" : `만 ${age}세`} · ${genderLabel(client.gender)}</span></div></div>
    <div class="detail-grid">
      <div><label>안전 상태</label><strong class="state-text ${client.dangerState.toLowerCase()}">${client.dangerState}</strong></div>
      <div><label>최근 갱신</label><strong data-ago="${client.updatedAt}">${ago(client.updatedAt)}</strong></div>
      <div><label>연령</label><strong>${age === null ? "-" : `만 ${age}세`}</strong></div>
      <div><label>성별</label><strong>${genderLabel(client.gender)}</strong></div>
      <div><label>위도</label><strong>${client.location?.lat?.toFixed(5) || "-"}</strong></div>
      <div><label>경도</label><strong>${client.location?.lng?.toFixed(5) || "-"}</strong></div>
      <div><label>위치 정확도</label><strong>${client.location ? `${Math.round(client.location.accuracy || 0)} m` : "-"}</strong></div>
      <div><label>위치 신선도</label><strong class="${isLocationStale(client) ? "stale-text" : ""}">${client.location ? (isLocationStale(client) ? "STALE" : "CURRENT") : "-"}</strong></div>
      <div><label>배터리</label><strong class="${client.warnings?.lowBattery ? "stale-text" : ""}">${client.batteryLevel === null || client.batteryLevel === undefined ? "미지원" : `${client.batteryLevel}%${client.batteryCharging ? " · 충전 중" : ""}`}</strong></div>
      <div><label>움직임</label><strong class="${client.warnings?.immobile ? "stale-text" : ""}">${client.warnings?.immobile ? "장시간 정지" : "정상"}</strong></div>
      <div class="address-detail"><label>관리 그룹</label><strong>${escapeHtml((client.groupIds || []).map(id => snapshot.groups?.find(group => group.id === id)?.name).filter(Boolean).join(", ") || "미지정")}</strong></div>
      <div class="address-detail"><label>현재 주소</label><strong>${escapeHtml(client.location?.address || "주소 미확인")}</strong>${client.location?.addressProvider ? `<small>${escapeHtml(client.location.addressProvider)} · ${ago(client.location.addressResolvedAt)}</small>` : ""}</div>
    </div>
    ${sos ? `
      <section class="sos-workflow">
        <div class="sos-workflow-head">
          <div><label>SOS 처리 단계</label><strong class="sos-stage ${sos.status.toLowerCase()}">${escapeHtml(sosStatusLabel(sos.status))}</strong></div>
          <span>${sos.operator ? `담당 ${escapeHtml(sos.operator)}` : "담당자 미배정"}</span>
        </div>
        <textarea id="sosNote" maxlength="500" placeholder="출동 위치, 연락 결과 등 처리 메모">${escapeHtml(sos.note || "")}</textarea>
        ${sosHistory.length ? `
          <div class="sos-history">
            ${sosHistory.slice().reverse().map(item => `
              <div>
                <b>${escapeHtml(sosStatusLabel(item.status))}</b>
                <span>${escapeHtml(item.operator || "관제 요원")} · ${timeOnly(item.createdAt)}</span>
                ${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}
              </div>
            `).join("")}
          </div>` : ""}
      </section>` : ""}
    <div class="detail-actions">
      <button class="btn" id="routeBtn">이동 경로</button>
      <button class="btn" id="analyticsBtn">이동 통계</button>
      ${client.location ? `<button class="btn" id="facilitiesBtn">가까운 안전시설</button>` : ""}
      <button class="btn" id="guidesBtn">재난 행동 요령</button>
      ${client.location ? `<button class="btn" id="addressBtn">주소 확인</button>` : ""}
      ${sos ? sos.status === "OPEN"
        ? `<button class="btn btn-danger" id="ackBtn">접수·담당 배정</button>`
        : sos.status === "ACKNOWLEDGED"
          ? `<button class="btn btn-primary" id="dispatchBtn">출동 시작</button>`
          : sos.status === "DISPATCHED"
            ? `<button class="btn btn-success" id="resolveBtn">구조 완료</button>`
            : "" : ""}
    </div>`;
  document.querySelector("#routeBtn").onclick = loadRoute;
  document.querySelector("#analyticsBtn").onclick = loadAnalytics;
  document.querySelector("#guidesBtn").onclick = loadSafetyGuides;
  if (client.location) {
    document.querySelector("#addressBtn").onclick = resolveAddress;
    document.querySelector("#facilitiesBtn").onclick = loadFacilities;
  }
  if (sos?.status === "OPEN") {
    document.querySelector("#ackBtn").onclick = () => updateSos(sos.id, "ACKNOWLEDGED");
  }
  if (sos?.status === "ACKNOWLEDGED") {
    document.querySelector("#dispatchBtn").onclick = () => updateSos(sos.id, "DISPATCHED");
  }
  if (sos?.status === "DISPATCHED") {
    document.querySelector("#resolveBtn").onclick = () => updateSos(sos.id, "RESOLVED");
  }
}

function renderTable() {
  const query = document.querySelector("#search").value.trim().toLowerCase();
  const matchingClients = snapshot.clients.filter(
    client => (!selectedGroup || (client.groupIds || []).includes(selectedGroup))
      && (!query || `${client.id} ${client.name}`.toLowerCase().includes(query))
  );
  const clients = matchingClients.slice(0, MAX_TABLE_ROWS);
  const overflow = matchingClients.length > clients.length
    ? `<tr><td colspan="4" class="empty">${matchingClients.length - clients.length}명은 검색어 또는 지역 필터로 범위를 줄여 확인하세요.</td></tr>`
    : "";
  document.querySelector("#clientsTable").innerHTML = clients.map(client => `
    <tr data-id="${client.id}">
      <td><b>${escapeHtml(client.name)}</b><br><span class="muted">${client.id} · ${escapeHtml(regionName(client.regionId))} · ${calculateAge(client.birthDate) === null ? "연령 미입력" : `만 ${calculateAge(client.birthDate)}세`} · ${genderLabel(client.gender)}</span></td>
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

function openTodayEvents() {
  const eventsForToday = todayEvents();
  document.querySelector("#todayEventsList").innerHTML = eventsForToday.map(event => `
    <article class="today-event">
      <span class="today-event-type">${escapeHtml(eventTypeLabel(event.type))}</span>
      <div><b>${escapeHtml(event.title)}</b><small>${escapeHtml(event.clientId || "시스템 이벤트")}</small></div>
      <time>${new Date(event.createdAt).toLocaleTimeString("ko-KR", {
        timeZone: "Asia/Seoul",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })}</time>
    </article>
  `).join("") || `<p class="empty">오늘 발생한 이벤트가 없습니다.</p>`;
  document.querySelector("#eventsOverlay").hidden = false;
}

function closeTodayEvents() {
  document.querySelector("#eventsOverlay").hidden = true;
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

async function resolveAddress() {
  try {
    const data = await api(`/api/clients/${selectedId}/address`, {
      method: "POST",
      body: "{}",
    });
    const updated = data.client;
    const index = snapshot.clients.findIndex(client => client.id === updated.id);
    if (index >= 0) snapshot.clients[index] = updated;
    rebuildIndexes();
    renderDetail();
    toast("현재 위치의 주소를 확인했습니다.");
  } catch (error) {
    toast(error.message);
  }
}

async function updateSos(id, status) {
  try {
    const note = document.querySelector("#sosNote")?.value.trim() || "";
    await api(`/api/sos/${id}`, {
      method: "POST",
      body: JSON.stringify({ status, note }),
    });
    const messages = {
      ACKNOWLEDGED: "구조 요청을 접수하고 담당자를 배정했습니다.",
      DISPATCHED: "현장 출동 단계로 변경했습니다.",
      RESOLVED: "구조 처리를 완료했습니다.",
    };
    toast(messages[status] || "SOS 상태를 변경했습니다.");
    await refresh();
  } catch (error) {
    toast(error.message);
  }
}

function openInfo(title, html) {
  document.querySelector("#infoTitle").textContent = title;
  document.querySelector("#infoContent").innerHTML = html;
  document.querySelector("#infoOverlay").hidden = false;
}

async function loadAnalytics() {
  try {
    const { analytics } = await api(`/api/clients/${selectedId}/analytics`);
    openInfo("이동·정차 통계", `
      <div class="metric-grid">
        <article><span>총 이동 거리</span><b>${(analytics.distanceMeters / 1000).toFixed(2)} km</b></article>
        <article><span>정차 시간</span><b>${Math.floor(analytics.stationarySeconds / 60)}분</b></article>
        <article><span>수집 지점</span><b>${analytics.pointCount}개</b></article>
      </div>
      <h3>자주 방문한 장소</h3>
      <div class="info-list">${analytics.frequentPlaces.map(place => `
        <p><b>${place.lat.toFixed(3)}, ${place.lng.toFixed(3)}</b><span>${place.visits}회 · ${ago(place.lastVisitedAt)}</span></p>
      `).join("") || "<p>분석할 위치 기록이 부족합니다.</p>"}</div>
    `);
  } catch (error) {
    toast(error.message);
  }
}

async function loadFacilities() {
  try {
    const { facilities } = await api(`/api/clients/${selectedId}/facilities`);
    const labels = { SHELTER: "대피소", HOSPITAL: "병원", FIRE_STATION: "소방서" };
    openInfo("가까운 안전시설", `<div class="info-list">${facilities.map(item => `
      <p><b>${labels[item.type]} · ${escapeHtml(item.name)}</b>
      <span>${item.distanceMeters.toLocaleString()}m · ${escapeHtml(item.source)}</span>
      <a target="_blank" rel="noreferrer" href="https://map.kakao.com/link/to/${encodeURIComponent(item.name)},${item.lat},${item.lng}">길 안내</a></p>
    `).join("")}</div><small class="data-notice">현재 기본 안전시설 데이터입니다. 운영 전 공공데이터 최신 시설 목록으로 교체해야 합니다.</small>`);
  } catch (error) {
    toast(error.message);
  }
}

async function loadSafetyGuides() {
  try {
    const { guides } = await api("/api/safety-guides");
    openInfo("재난 종류별 행동 요령", `<div class="guide-grid">${Object.values(guides).map(guide => `
      <article><h3>${escapeHtml(guide.title)}</h3><ol>${guide.steps.map(step => `<li>${escapeHtml(step)}</li>`).join("")}</ol></article>
    `).join("")}</div>`);
  } catch (error) {
    toast(error.message);
  }
}

function closeManager(id) {
  document.querySelector(`#${id}`).hidden = true;
}

function openManager(id) {
  document.querySelector("#mainMenu").hidden = true;
  document.querySelector("#menuBtn").setAttribute("aria-expanded", "false");
  document.querySelector(`#${id}`).hidden = false;
}

function renderDangerAreaManager() {
  document.querySelector("#dangerAreaList").innerHTML = (snapshot.dangerAreas || []).map(area => `
    <article><div><b>${escapeHtml(area.name)}</b><span>${escapeHtml(regionName(area.regionId))} · ${area.shape === "POLYGON" ? `다각형 ${area.points.length}점` : `원형 ${Math.round(area.radius)}m`} · 위험도 ${area.severity}</span></div>
    <button class="text-danger" data-delete-area="${area.id}">삭제</button></article>
  `).join("") || `<p class="empty">등록된 위험구역이 없습니다.</p>`;
}

function openDangerAreaManager() {
  openManager("dangerAreaOverlay");
  const region = selectedRegion || authSession.user?.regionId || "KR-11";
  document.querySelector("#dangerAreaRegion").value = region;
  document.querySelector("#dangerAreaRegion").disabled = authSession.user?.role === "REGIONAL_OPERATOR";
  renderDangerAreaManager();
}

async function createDangerArea(event) {
  event.preventDefault();
  const shape = document.querySelector("#dangerAreaShape").value;
  const payload = {
    name: document.querySelector("#dangerAreaName").value.trim(),
    regionId: document.querySelector("#dangerAreaRegion").value,
    shape,
    severity: Number(document.querySelector("#dangerAreaSeverity").value),
  };
  if (shape === "POLYGON") {
    payload.points = document.querySelector("#dangerAreaPoints").value.split(/\n+/)
      .filter(Boolean).map(line => {
        const [lat, lng] = line.split(",").map(Number);
        return { lat, lng };
      });
  } else {
    payload.lat = Number(document.querySelector("#dangerAreaLat").value);
    payload.lng = Number(document.querySelector("#dangerAreaLng").value);
    payload.radius = Number(document.querySelector("#dangerAreaRadius").value);
  }
  try {
    await api("/api/danger-areas", { method: "POST", body: JSON.stringify(payload) });
    event.target.reset();
    document.querySelector("#dangerAreaRegion").value =
      selectedRegion || authSession.user?.regionId || "KR-11";
    document.querySelector("#dangerAreaShape").dispatchEvent(new Event("change"));
    await refresh();
    renderDangerAreaManager();
    toast("위험구역을 생성했습니다.");
  } catch (error) {
    toast(error.message);
  }
}

async function deleteDangerArea(id) {
  try {
    await api(`/api/danger-areas/${id}`, { method: "DELETE" });
    await refresh();
    renderDangerAreaManager();
    toast("위험구역을 삭제했습니다.");
  } catch (error) {
    toast(error.message);
  }
}

function renderGroupManager() {
  document.querySelector("#groupList").innerHTML = (snapshot.groups || []).map(group => `
    <article class="group-editor">
      <div class="group-title"><b><i style="background:${escapeHtml(group.color)}"></i>${escapeHtml(group.name)}</b><button class="text-danger" data-delete-group="${group.id}">삭제</button></div>
      <div class="member-checks">${snapshot.clients.map(client => `
        <label><input type="checkbox" data-group-member="${group.id}" value="${client.id}" ${group.memberIds.includes(client.id) ? "checked" : ""}>${escapeHtml(client.name)}</label>
      `).join("") || "<span>배정할 사용자가 없습니다.</span>"}</div>
      <button class="btn" data-save-group="${group.id}">구성원 저장</button>
    </article>
  `).join("") || `<p class="empty">등록된 그룹이 없습니다.</p>`;
}

function openGroupManager() {
  openManager("groupOverlay");
  renderGroupManager();
}

async function createGroup(event) {
  event.preventDefault();
  try {
    await api("/api/groups", {
      method: "POST",
      body: JSON.stringify({
        name: document.querySelector("#groupName").value.trim(),
        color: document.querySelector("#groupColor").value,
        regionId: selectedRegion || null,
      }),
    });
    event.target.reset();
    await refresh();
    renderGroupManager();
    toast("사용자 그룹을 생성했습니다.");
  } catch (error) {
    toast(error.message);
  }
}

async function saveGroupMembers(id) {
  const memberIds = [...document.querySelectorAll(`[data-group-member="${id}"]:checked`)].map(input => input.value);
  try {
    await api(`/api/groups/${id}/members`, { method: "POST", body: JSON.stringify({ memberIds }) });
    await refresh();
    renderGroupManager();
    toast("그룹 구성원을 저장했습니다.");
  } catch (error) {
    toast(error.message);
  }
}

async function deleteGroup(id) {
  try {
    await api(`/api/groups/${id}`, { method: "DELETE" });
    await refresh();
    renderGroupManager();
    toast("그룹을 삭제했습니다.");
  } catch (error) {
    toast(error.message);
  }
}

function openAuditLog() {
  openManager("auditOverlay");
  document.querySelector("#auditList").innerHTML = (snapshot.auditLogs || []).map(entry => `
    <article><div><b>${escapeHtml(entry.action)}</b><span>${escapeHtml(entry.actorName)} · ${escapeHtml(entry.target)} · ${ago(entry.createdAt)}</span></div><small>${escapeHtml(entry.detail || "-")}</small></article>
  `).join("") || `<p class="empty">관리자 작업 기록이 없습니다.</p>`;
}

function openKnowledgeSearch() {
  openManager("knowledgeOverlay");
  requestAnimationFrame(() => document.querySelector("#knowledgeQuery").focus());
}

async function searchKnowledge(event) {
  event.preventDefault();
  const query = document.querySelector("#knowledgeQuery").value.trim();
  const target = document.querySelector("#knowledgeResults");
  target.innerHTML = `<p class="empty">공식 문서를 검색하고 있습니다.</p>`;
  try {
    const result = await api("/api/disaster-knowledge/search", {
      method: "POST",
      body: JSON.stringify({ query, limit: 4 }),
    });
    target.innerHTML = result.grounded ? `
      <div class="knowledge-answer">${escapeHtml(result.answer).replace(/\n/g, "<br>")}</div>
      <div class="knowledge-sources">
        ${result.sources.map(source => `
          <article>
            <b>${escapeHtml(source.title)}</b>
            <span>${escapeHtml(source.source)} · ${escapeHtml(source.section)}</span>
            <a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">공식 원문 확인</a>
          </article>
        `).join("")}
      </div>
      <small class="data-notice">${escapeHtml(result.notice)}</small>
    ` : `<p class="empty">관련 문서를 찾지 못했습니다. 재난 종류나 행동을 더 구체적으로 입력해 주세요.</p>`;
  } catch (error) {
    target.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
  }
}

async function loadOperators() {
  const data = await api("/api/operators");
  document.querySelector("#operatorList").innerHTML = data.operators.map(operator => `
    <span><b>${escapeHtml(operator.displayName)}</b> ${escapeHtml(regionName(operator.regionId))} · ${escapeHtml(operator.username)}</span>
  `).join("") || "<span>등록된 지역 관리자가 없습니다.</span>";
}

async function openOperatorManager() {
  if (authSession.user?.role !== "NATIONAL_ADMIN") return;
  document.querySelector("#mainMenu").hidden = true;
  document.querySelector("#menuBtn").setAttribute("aria-expanded", "false");
  document.querySelector("#operatorOverlay").hidden = false;
  try {
    await loadOperators();
  } catch (error) {
    closeOperatorManager();
    toast(error.message);
  }
}

function closeOperatorManager() {
  document.querySelector("#operatorOverlay").hidden = true;
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
document.querySelector("#operatorMenuBtn").addEventListener("click", openOperatorManager);
document.querySelector("#dangerAreaMenuBtn").addEventListener("click", openDangerAreaManager);
document.querySelector("#groupMenuBtn").addEventListener("click", openGroupManager);
document.querySelector("#auditMenuBtn").addEventListener("click", openAuditLog);
document.querySelector("#knowledgeMenuBtn").addEventListener("click", openKnowledgeSearch);
document.querySelector("#dangerAreaForm").addEventListener("submit", createDangerArea);
document.querySelector("#groupForm").addEventListener("submit", createGroup);
document.querySelector("#knowledgeForm").addEventListener("submit", searchKnowledge);
document.querySelector("#dangerAreaShape").addEventListener("change", event => {
  const polygon = event.target.value === "POLYGON";
  document.querySelector("#circleAreaFields").hidden = polygon;
  document.querySelector("#polygonAreaFields").hidden = !polygon;
});
document.querySelector("#dangerAreaList").addEventListener("click", event => {
  if (event.target.dataset.deleteArea) deleteDangerArea(event.target.dataset.deleteArea);
});
document.querySelector("#groupList").addEventListener("click", event => {
  if (event.target.dataset.saveGroup) saveGroupMembers(event.target.dataset.saveGroup);
  if (event.target.dataset.deleteGroup) deleteGroup(event.target.dataset.deleteGroup);
});
document.querySelectorAll("[data-close]").forEach(button => {
  button.addEventListener("click", () => closeManager(button.dataset.close));
});
document.querySelectorAll(".manager-overlay").forEach(overlay => {
  overlay.addEventListener("click", event => {
    if (event.target === overlay) closeManager(overlay.id);
  });
});
document.querySelector("#closeOperatorBtn").addEventListener("click", closeOperatorManager);
document.querySelector("#operatorOverlay").addEventListener("click", event => {
  if (event.target.id === "operatorOverlay") closeOperatorManager();
});
document.querySelector("#search").addEventListener("input", renderTable);
["#alertSeverity", "#alertType", "#alertTime"].forEach(selector => {
  document.querySelector(selector).addEventListener("change", render);
});
document.querySelector("#todayEventsCard").addEventListener("click", openTodayEvents);
document.querySelector("#todayEventsCard").addEventListener("keydown", event => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    openTodayEvents();
  }
});
document.querySelector("#closeEventsBtn").addEventListener("click", closeTodayEvents);
document.querySelector("#eventsOverlay").addEventListener("click", event => {
  if (event.target.id === "eventsOverlay") closeTodayEvents();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    closeTodayEvents();
    closeOperatorManager();
    document.querySelectorAll(".manager-overlay").forEach(overlay => {
      overlay.hidden = true;
    });
  }
});
document.querySelector("#regionFilter").onchange = event => {
  selectedRegion = event.target.value;
  selectedId = null;
  selectedRoute = [];
  scheduleRefresh(0);
};
document.querySelector("#groupFilter").onchange = event => {
  selectedGroup = event.target.value;
  selectedId = null;
  selectedRoute = [];
  render();
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
  setupMainMenu();
  try {
    await initializeMap();
  } catch (error) {
    toast(error.message);
  }
  regions = await loadRegions([
    document.querySelector("#operatorRegion"),
    document.querySelector("#dangerAreaRegion"),
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
