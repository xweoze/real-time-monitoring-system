let members = [];
let regions = [];
let editingId = null;

const regionName = regionId =>
  regions.find(region => region.id === regionId)?.name || regionId || "미지정";

const showLogin = show => {
  document.querySelector("#authOverlay").hidden = !show;
};

const profileText = member => {
  const age = calculateAge(member.birthDate);
  const ageText = age === null ? "나이 미입력" : `만 ${age}세`;
  return `${ageText} · ${genderLabel(member.gender)}`;
};

const renderMembers = () => {
  const keyword = document.querySelector("#searchInput").value.trim().toLowerCase();
  const filtered = members.filter(member =>
    !keyword
    || member.displayName.toLowerCase().includes(keyword)
    || member.username.toLowerCase().includes(keyword)
  );
  document.querySelector("#totalCount").textContent = members.length;
  document.querySelector("#onlineCount").textContent =
    members.filter(member => member.connectionStatus === "ONLINE").length;
  document.querySelector("#emptyState").hidden = filtered.length > 0;
  document.querySelector("#memberRows").innerHTML = filtered.map(member => `
    <tr>
      <td class="identity"><b>${escapeHtml(member.displayName)}</b><span>${escapeHtml(member.username)}</span></td>
      <td><b>${escapeHtml(profileText(member))}</b><div class="profile-detail">${escapeHtml(member.birthDate || "생년월일 미입력")}</div></td>
      <td>${escapeHtml(regionName(member.regionId))}</td>
      <td><span class="status ${member.connectionStatus === "ONLINE" ? "online" : ""}"><i class="status-dot"></i>${member.connectionStatus === "ONLINE" ? "접속 중" : "오프라인"}</span></td>
      <td>${new Date(member.createdAt).toLocaleDateString("ko-KR")}</td>
      <td><div class="row-actions">
        <button type="button" data-edit="${member.id}">수정</button>
        <button type="button" class="delete" data-delete="${member.id}">삭제</button>
      </div></td>
    </tr>
  `).join("");
};

const loadMembers = async () => {
  const filter = document.querySelector("#regionFilter");
  const query = filter.value ? `?region=${encodeURIComponent(filter.value)}` : "";
  const data = await api(`/api/members${query}`);
  members = data.members;
  renderMembers();
};

const openEdit = memberId => {
  const member = members.find(item => item.id === memberId);
  if (!member) return;
  editingId = member.id;
  document.querySelector("#editUsername").value = member.username;
  document.querySelector("#editDisplayName").value = member.displayName;
  document.querySelector("#editBirthDate").value = member.birthDate || "";
  document.querySelector("#editGender").value = member.gender || "UNDISCLOSED";
  document.querySelector("#editRegion").value = member.regionId;
  document.querySelector("#editOverlay").hidden = false;
};

const closeEdit = () => {
  editingId = null;
  document.querySelector("#editOverlay").hidden = true;
};

const saveMember = async event => {
  event.preventDefault();
  if (!editingId) return;
  try {
    await api(`/api/members/${encodeURIComponent(editingId)}`, {
      method: "POST",
      body: JSON.stringify({
        displayName: document.querySelector("#editDisplayName").value.trim(),
        birthDate: document.querySelector("#editBirthDate").value || null,
        gender: document.querySelector("#editGender").value,
        regionId: document.querySelector("#editRegion").value,
      }),
    });
    closeEdit();
    await loadMembers();
    toast("회원 정보를 수정했습니다.");
  } catch (error) {
    toast(error.message);
  }
};

const deleteMember = async memberId => {
  const member = members.find(item => item.id === memberId);
  if (!member || !confirm(`${member.displayName} 회원을 삭제하시겠습니까?\n삭제 후에는 복구할 수 없습니다.`)) return;
  try {
    await api(`/api/members/${encodeURIComponent(memberId)}`, { method: "DELETE" });
    await loadMembers();
    toast("회원 계정을 삭제했습니다.");
  } catch (error) {
    toast(error.message);
  }
};

const startPage = async () => {
  const user = authSession.user;
  document.querySelector("#operatorName").textContent = user.displayName;
  const filter = document.querySelector("#regionFilter");
  if (user.role === "REGIONAL_OPERATOR") {
    filter.value = user.regionId;
    filter.disabled = true;
    document.querySelector("#editRegion").disabled = true;
  }
  showLogin(false);
  await loadMembers();
};

const login = async event => {
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
      throw new Error("회원 관리 권한이 없는 계정입니다.");
    }
    authSession.save(data);
    await startPage();
  } catch (error) {
    toast(error.message);
  }
};

const logout = async () => {
  await logoutSession();
  members = [];
  renderMembers();
  showLogin(true);
};

document.querySelector("#memberRows").addEventListener("click", event => {
  const editId = event.target.dataset.edit;
  const deleteId = event.target.dataset.delete;
  if (editId) openEdit(editId);
  if (deleteId) deleteMember(deleteId);
});
document.querySelector("#searchInput").addEventListener("input", renderMembers);
document.querySelector("#regionFilter").addEventListener("change", loadMembers);
document.querySelector("#refreshBtn").addEventListener("click", loadMembers);
document.querySelector("#editForm").addEventListener("submit", saveMember);
document.querySelector("#closeEditBtn").addEventListener("click", closeEdit);
document.querySelector("#cancelEditBtn").addEventListener("click", closeEdit);
document.querySelector("#memberLogin").addEventListener("submit", login);
document.querySelector("#logoutBtn").addEventListener("click", logout);

async function initialize() {
  setupMainMenu();
  regions = await loadRegions([document.querySelector("#editRegion")]);
  const filter = document.querySelector("#regionFilter");
  filter.innerHTML = `<option value="">전체 지역</option>${regions.map(
    region => `<option value="${region.id}">${escapeHtml(region.name)}</option>`
  ).join("")}`;

  if (authSession.token) {
    try {
      const data = await api("/api/auth/me");
      if (!["NATIONAL_ADMIN", "REGIONAL_OPERATOR"].includes(data.user.role)) {
        throw new Error("회원 관리 권한 없음");
      }
      authSession.user = data.user;
      await startPage();
      return;
    } catch (_) {
      authSession.clear();
    }
  }
  showLogin(true);
}

initialize();
