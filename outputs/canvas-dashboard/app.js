const REFRESH_MS = 3 * 60 * 1000;
const state = { assignments: [], courses: [], timezone: null, filter: "all", course: "all", showEnded: false, syncing: false, localTasks: [], timer: null, connectionMessageShown: false, connectionStorage: null };
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
function formatDate(date, options) {
  try { return new Intl.DateTimeFormat("zh-CN", { ...options, timeZone: state.timezone || undefined }).format(date); }
  catch (_) { return new Intl.DateTimeFormat("zh-CN", options).format(date); }
}
function dueDate(value) {
  if (!value) return { text: "—", date: null };
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { text: "截止时间未提供", date: null };
  return { text: formatDate(date, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }), date };
}

function dateParts(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { month: "待定", day: "—" };
  return { month: formatDate(date, { month: "short" }), day: formatDate(date, { day: "numeric" }) };
}

function scopedAssignments(includeEnded = state.showEnded) {
  const ended = new Set(state.courses.filter((course) => course.ended).map((course) => course.id));
  return state.assignments.filter((item) => includeEnded || !ended.has(item.course_id));
}

function counts(items = scopedAssignments()) {
  return items.reduce((total, item) => { total[item.status] = (total[item.status] || 0) + 1; return total; }, {});
}

function renderEndedToggle() {
  const button = $("endedToggle");
  const endedCount = state.courses.filter((course) => course.ended).length;
  button.hidden = endedCount === 0;
  button.textContent = state.showEnded ? "隐藏已结束课程" : `查看已结束课程 (${endedCount})`;
  button.setAttribute("aria-expanded", String(state.showEnded));
}

function renderFilters() {
  const select = $("courseFilter");
  const previous = state.course;
  const courses = state.courses.filter((course) => state.showEnded || !course.ended);
  select.innerHTML = '<option value="all">所有课程</option>' + courses.map((course) => `<option value="${esc(course.id)}">${esc(course.name)}${course.ended ? " · 已结束" : ""}</option>`).join("");
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  else { state.course = "all"; select.value = "all"; }
  const items = scopedAssignments();
  const total = counts(items);
  $("allTabCount").textContent = String(items.length);
  $("pendingTabCount").textContent = String(total.pending || 0);
  $("overdueTabCount").textContent = String(total.overdue || 0);
  $("completedTabCount").textContent = String(total.completed || 0);
  $("undatedTabCount").textContent = String(total.undated || 0);
  $("manualTabCount").textContent = String(total.manual || 0);
  $("historicalTabCount").textContent = String(total.historical || 0);
}

function renderStats() {
  const total = counts();
  $("pendingCount").textContent = String(total.pending || 0);
  $("overdueCount").textContent = String(total.overdue || 0);
  $("completedCount").textContent = String(total.completed || 0);
  $("courseCount").textContent = String(state.courses.filter((course) => !course.ended).length);
}

function matchesThisWeek(item) {
  if (!item.due_at) return false;
  const due = new Date(item.due_at).getTime();
  return due >= Date.now() && due < Date.now() + 7 * 86400000;
}

function visibleAssignments() {
  return scopedAssignments().filter((item) => (state.filter === "all" || item.status === state.filter) && (state.course === "all" || item.course_id === state.course));
}

function renderTaskNotes() {
  const visible = scopedAssignments();
  const notes = [];
  const undated = visible.filter((item) => item.status === "undated").length;
  const manual = visible.filter((item) => item.status === "manual").length;
  const historical = visible.filter((item) => item.status === "historical").length;
  const ended = state.showEnded ? state.courses.filter((course) => course.ended && (state.course === "all" || course.id === state.course)) : [];
  if (undated) notes.push(`${undated} 项未设截止日期，不计入待完成、逾期或未来一周统计。`);
  if (manual) notes.push(`${manual} 项需线下确认，Canvas 无法读取其提交状态。`);
  if (historical) notes.push(`${historical} 项的截止日期已超过 180 天，收在“历史任务”中供核对。`);
  for (const course of ended) notes.push(`${course.name}：${course.ended_reason}。`);
  $("manualNote").textContent = notes.join(" ");
  $("manualNote").hidden = notes.length === 0;
}

function renderAssignments() {
  const items = visibleAssignments();
  if (!items.length) {
    $("taskList").innerHTML = '<div class="empty-state">这个筛选条件下没有任务。</div>';
    renderTaskNotes();
    return;
  }
  const labelClass = { overdue: "overdue", completed: "completed", manual: "manual", undated: "undated", historical: "historical", pending: "" };
  $("taskList").innerHTML = items.map((item) => {
    const due = dueDate(item.due_at);
    const dueClass = item.status === "overdue" ? "late" : item.status === "historical" ? "historical" : item.status === "pending" && due.date && due.date - Date.now() < 3 * 86400000 ? "soon" : "";
    const title = item.url ? `<a class="task-link" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.name)}</a>` : esc(item.name);
    const course = state.courses.find((entry) => entry.id === item.course_id);
    return `<article class="task-row"><div><div class="task-name">${title}</div><div class="task-course">${esc(item.course)}${course?.ended ? " · 已结束课程" : ""}${item.points != null ? ` · ${esc(item.points)} 分` : ""}</div></div><div class="task-meta"><span class="due ${dueClass}">${esc(due.text)}</span><span class="status-badge ${labelClass[item.status] || ""}">${esc(item.status_label)}</span></div></article>`;
  }).join("");
  renderTaskNotes();
}

function renderFocus() {
  const items = scopedAssignments(false).filter((item) => item.status !== "completed" && matchesThisWeek(item)).slice(0, 5);
  if (!items.length) {
    $("focusList").innerHTML = '<div class="muted-empty">未来一周没有未完成的截止任务。</div>';
    return;
  }
  $("focusList").innerHTML = items.map((item) => {
    const date = dateParts(item.due_at);
    const stateClass = item.status === "overdue" ? "overdue" : item.status === "completed" ? "completed" : "";
    return `<article class="focus-item"><div class="focus-date"><span>${esc(date.month)}</span><strong>${esc(date.day)}</strong></div><div><div class="focus-title">${esc(item.name)}</div><div class="focus-course">${esc(item.course)}</div><div class="focus-state ${stateClass}">${esc(item.status_label)}</div></div></article>`;
  }).join("");
}

async function loadCanvas({ quiet = false } = {}) {
  if (state.syncing) return;
  state.syncing = true;
  if (!quiet) {
    $("syncDot").className = "sync-dot syncing";
    $("syncTime").textContent = "正在同步…";
  }
  $("notice").hidden = true;
  try {
    const response = await fetch("/api/data", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      const error = new Error(payload.error || "暂时无法读取 Canvas。");
      error.canReconnect = Boolean(payload.can_reconnect);
      error.canvasUrl = payload.canvas_url || "";
      throw error;
    }
    state.assignments = payload.assignments || [];
    state.courses = payload.courses || [];
    state.timezone = payload.timezone || null;
    state.connectionStorage = payload.connection_storage || null;
    $("connectionModeLabel").textContent = payload.connection_storage === "memory" ? "本次临时 Canvas 连接" : "本机 Canvas 连接";
    $("sessionOnly").checked = payload.connection_storage === "memory";
    renderEndedToggle();
    renderFilters(); renderStats(); renderAssignments(); renderFocus();
    const date = new Date(payload.synced_at);
    $("syncTime").textContent = `${formatDate(date, { hour: "2-digit", minute: "2-digit" })} · ${esc(payload.timezone || "本地时间")}`;
    $("syncDot").className = "sync-dot";
    if (payload.connection_storage === "memory" && !state.connectionMessageShown) {
      state.connectionMessageShown = true;
      showNotice("当前 Canvas 连接只保存在看板服务内存中；停止或重启看板后需要重新输入 Token。");
    }
    const errors = state.courses.filter((course) => course.error).length;
    if (errors) showNotice(`${errors} 门课程暂时无法读取作业，其他课程已更新。`);
  } catch (error) {
    $("syncDot").className = "sync-dot error";
    $("syncTime").textContent = "同步失败";
    showNotice(error.message || "暂时无法读取 Canvas。请检查连接后再试。", { canReconnect: error.canReconnect, canvasUrl: error.canvasUrl });
    if (!state.assignments.length) $("taskList").innerHTML = '<div class="empty-state">请确认本机 Canvas 连接后，点击“刷新 Canvas”。</div>';
  } finally {
    state.syncing = false;
  }
}

function showNotice(message, { canReconnect = false, canvasUrl = "" } = {}) {
  $("noticeText").textContent = message;
  $("noticeRepairButton").hidden = !canReconnect;
  $("notice").hidden = false;
  if (canvasUrl) $("canvasUrl").value = canvasUrl;
  if (canReconnect) {
    $("connectionPanel").hidden = false;
    $("connectPanelButton").setAttribute("aria-expanded", "true");
  }
}

async function loadLocalTasks() {
  try {
    const response = await fetch("/api/tasks", { cache: "no-store" });
    const payload = await response.json();
    state.localTasks = payload.tasks || [];
    renderLocalTasks();
  } catch (_) { $("localTaskList").innerHTML = '<li class="muted-empty">本地清单暂时无法读取。</li>'; }
}

function renderLocalTasks() {
  const list = $("localTaskList");
  if (!state.localTasks.length) list.innerHTML = '<li class="muted-empty">添加一项今天想完成的学习任务。</li>';
  else list.innerHTML = state.localTasks.map((task) => `<li class="local-task ${task.done ? "done" : ""}"><input type="checkbox" data-action="toggle" data-id="${esc(task.id)}" ${task.done ? "checked" : ""} aria-label="标记完成"><span>${esc(task.title)}</span><button class="delete-task" data-action="delete" data-id="${esc(task.id)}" type="button" aria-label="删除事项">×</button></li>`).join("");
  const done = state.localTasks.filter((task) => task.done).length;
  $("planProgress").textContent = `${done} / ${state.localTasks.length} 项已完成`;
  $("clearDoneButton").hidden = done === 0;
}

async function mutateTask(payload) {
  const response = await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "清单更新失败");
  state.localTasks = result.tasks;
  renderLocalTasks();
}

function startPolling() {
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => { if (!document.hidden) loadCanvas({ quiet: true }); }, REFRESH_MS);
}

document.addEventListener("DOMContentLoaded", () => {
  $("refreshButton").addEventListener("click", () => loadCanvas());
  $("connectPanelButton").addEventListener("click", () => {
    const panel = $("connectionPanel");
    panel.hidden = !panel.hidden;
    $("connectPanelButton").setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) $("canvasToken").focus();
    else { $("canvasToken").value = ""; $("sessionOnly").checked = state.connectionStorage === "memory"; }
  });
  $("noticeRepairButton").addEventListener("click", () => {
    $("connectionPanel").hidden = false;
    $("connectPanelButton").setAttribute("aria-expanded", "true");
    $("canvasToken").focus();
  });
  $("closeConnectionButton").addEventListener("click", () => {
    $("connectionPanel").hidden = true;
    $("connectionStatus").textContent = "";
    $("canvasToken").value = "";
    $("sessionOnly").checked = state.connectionStorage === "memory";
    $("connectPanelButton").setAttribute("aria-expanded", "false");
  });
  $("connectionForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const tokenInput = $("canvasToken");
    let token = tokenInput.value.trim();
    if (!token) return;
    tokenInput.value = "";
    $("connectSubmit").disabled = true;
    const sessionOnly = $("sessionOnly").checked;
    $("connectionStatus").textContent = sessionOnly ? "正在验证并连接（仅本次运行）…" : "正在验证并保存到本机凭证管理器…";
    $("connectionStatus").className = "connection-status";
    try {
      const response = await fetch("/api/reconnect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ canvas_url: $("canvasUrl").value.trim(), token, session_only: sessionOnly })
      });
      token = "";
      const result = await response.json();
      if (!response.ok) {
        if (result.credential_unavailable) {
          $("connectionStatus").textContent = result.error + " Token 输入框已清空，请重新粘贴后提交。";
          $("connectionStatus").className = "connection-status error";
          $("canvasToken").focus();
          return;
        }
        throw new Error(result.error || "连接验证失败，请检查 Canvas 地址和 Token。");
      }
      $("connectionPanel").hidden = true;
      $("connectPanelButton").setAttribute("aria-expanded", "false");
      $("sessionOnly").checked = false;
      await loadCanvas();
      if (result.storage === "credential_manager" && $("notice").hidden) {
        showNotice("Canvas 已连接，Token 已保存到本机凭证管理器。");
      }
    } catch (error) {
      token = "";
      $("connectionPanel").hidden = false;
      $("connectionStatus").textContent = error.message || "连接失败，请检查后重试。";
      $("connectionStatus").className = "connection-status error";
    } finally {
      token = "";
      tokenInput.value = "";
      $("connectSubmit").disabled = false;
    }
  });
  $("endedToggle").addEventListener("click", () => {
    state.showEnded = !state.showEnded;
    renderEndedToggle(); renderFilters(); renderStats(); renderAssignments(); renderFocus();
  });
  $("courseFilter").addEventListener("change", (event) => { state.course = event.target.value; renderAssignments(); });
  document.querySelectorAll(".filter-chip").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll(".filter-chip").forEach((item) => { item.classList.remove("active"); item.setAttribute("aria-selected", "false"); });
    button.classList.add("active"); button.setAttribute("aria-selected", "true"); state.filter = button.dataset.filter; renderAssignments();
  }));
  $("addTaskForm").addEventListener("submit", async (event) => {
    event.preventDefault(); const input = $("newTask"); const title = input.value.trim(); if (!title) return;
    try { await mutateTask({ action: "add", title }); input.value = ""; } catch (error) { showNotice(error.message); }
  });
  $("localTaskList").addEventListener("change", async (event) => {
    if (event.target.dataset.action === "toggle") try { await mutateTask({ action: "toggle", id: event.target.dataset.id }); } catch (error) { showNotice(error.message); }
  });
  $("localTaskList").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action='delete']"); if (!button) return;
    try { await mutateTask({ action: "delete", id: button.dataset.id }); } catch (error) { showNotice(error.message); }
  });
  $("clearDoneButton").addEventListener("click", async () => {
    try { for (const task of [...state.localTasks].filter((item) => item.done)) await mutateTask({ action: "delete", id: task.id }); } catch (error) { showNotice(error.message); }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadCanvas({ quiet: true }); });
  loadCanvas(); loadLocalTasks(); startPolling();
});
