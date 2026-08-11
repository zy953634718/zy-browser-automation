// Side Panel UI：持久化历史对话，重新打开时恢复上次会话。
const STORAGE_KEY = "conversations";
const ACTIVE_KEY = "activeConversationId";
const DEFAULT_WS_URL = "ws://127.0.0.1:18767";
const MAX_CONVERSATIONS = 50;
const MAX_MESSAGES = 80;

const messagesEl = document.getElementById("messages");
const taskPlanEl = document.getElementById("taskPlan");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const stopBtn = document.getElementById("stop");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const selectEl = document.getElementById("conversationSelect");
const newBtn = document.getElementById("newConversation");
let conversations = [];
let activeId = "";
let thinkingEl = null;
let saveQueue = Promise.resolve();
let connectionStatus = "disconnected";
let running = false;

const TOOL_LABELS = {
  get_page_info: "读取页面信息", get_page_content: "读取页面内容", click_element: "点击页面元素",
  input_text: "填写内容", scroll_to: "滚动页面", open_url: "打开网页", close_tab: "关闭标签页",
  list_tabs: "检查标签页", get_images: "提取图片", take_screenshot: "截取页面", execute_script: "执行页面操作",
  save_file: "保存结果文件", list_skills: "查找工作流", read_skill: "读取工作流", create_skill: "保存工作流",
  remember: "保存长期记忆", recall_memory: "查询长期记忆", set_task_plan: "制定任务计划",
  update_task_plan: "更新任务进度", wait: "等待页面加载",
};
const PLAN_META = {
  pending: ["○", "待处理"], running: ["●", "进行中"], completed: ["✓", "已完成"],
  failed: ["!", "失败"], skipped: ["－", "已跳过"], cancelled: ["■", "已停止"], finished: ["■", "已结束"],
};

function id() { return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`; }
function activeConversation() { return conversations.find((item) => item.id === activeId); }

function queueSave() {
  saveQueue = saveQueue.catch(() => {}).then(() => chrome.storage.local.set({ conversations, activeConversationId: activeId }));
  return saveQueue;
}

function newConversation() {
  const conversation = { id: id(), title: "新对话", createdAt: Date.now(), updatedAt: Date.now(), messages: [], taskPlan: null };
  conversations.unshift(conversation);
  conversations = conversations.slice(0, MAX_CONVERSATIONS);
  activeId = conversation.id;
  renderHistory();
  renderMessages();
  queueSave();
  inputEl.focus();
}

async function loadState() {
  const stored = await chrome.storage.local.get([STORAGE_KEY, ACTIVE_KEY]);
  conversations = Array.isArray(stored[STORAGE_KEY]) ? stored[STORAGE_KEY] : [];
  conversations = conversations.filter((item) => item && item.id && Array.isArray(item.messages));
  activeId = stored[ACTIVE_KEY] && conversations.some((item) => item.id === stored[ACTIVE_KEY]) ? stored[ACTIVE_KEY] : conversations[0]?.id;
  if (!activeId) newConversation();
  else { renderHistory(); renderMessages(); }
}

function renderHistory() {
  selectEl.textContent = "";
  if (!conversations.length) {
    selectEl.disabled = true;
    const option = document.createElement("option"); option.textContent = "暂无历史对话"; selectEl.appendChild(option); return;
  }
  selectEl.disabled = false;
  conversations.forEach((item) => {
    const option = document.createElement("option"); option.value = item.id; option.textContent = item.title || "新对话"; option.selected = item.id === activeId; selectEl.appendChild(option);
  });
  syncControls();
}

function renderMessages() {
  messagesEl.textContent = "";
  renderTaskPlan();
  const conversation = activeConversation();
  if (!conversation || !conversation.messages.length) {
    const welcome = document.createElement("div"); welcome.className = "welcome"; welcome.textContent = "告诉我你想在当前网页上完成什么，例如：总结页面、查找信息、点击按钮或填写表单。"; messagesEl.appendChild(welcome); return;
  }
  conversation.messages.forEach((message) => addMessage(message.text, message.role === "user" ? "user" : (message.error ? "error" : "assistant")));
  scrollBottom();
}

function addMessage(text, cls) {
  const el = document.createElement("div"); el.className = `msg ${cls || "assistant"}`; el.textContent = text || ""; messagesEl.appendChild(el); return el;
}
function addTool(text) { const el = document.createElement("div"); el.className = "tool-row"; el.textContent = text; messagesEl.appendChild(el); scrollBottom(); return el; }
function scrollBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }
function toolLabel(name) { return TOOL_LABELS[name] || name || "浏览器操作"; }
function syncControls() {
  sendBtn.disabled = connectionStatus !== "connected" || running;
  stopBtn.disabled = connectionStatus !== "connected" || !running;
  newBtn.disabled = running;
  selectEl.disabled = running || !conversations.length;
}
function setRunning(value) { running = !!value; syncControls(); }
function activeStatus(status) {
  connectionStatus = status || "disconnected";
  statusDot.className = `dot ${status || "disconnected"}`;
  statusText.textContent = ({ connected: "已连接", connecting: "连接中", error: "连接错误", disconnected: "未连接" })[status] || "未连接";
  syncControls();
}

function renderTaskPlan() {
  const plan = activeConversation()?.taskPlan;
  taskPlanEl.textContent = "";
  taskPlanEl.hidden = !plan || !Array.isArray(plan.steps) || !plan.steps.length;
  if (taskPlanEl.hidden) return;

  const head = document.createElement("div"); head.className = "plan-head";
  const title = document.createElement("strong"); title.textContent = plan.goal || "任务计划";
  const status = document.createElement("span"); status.className = "plan-status";
  status.textContent = (PLAN_META[plan.status] || PLAN_META.running)[1];
  head.append(title, status); taskPlanEl.appendChild(head);

  const list = document.createElement("ol"); list.className = "plan-steps";
  plan.steps.forEach((step) => {
    const item = document.createElement("li"); item.className = `plan-step ${step.status || "pending"}`;
    const icon = document.createElement("span"); icon.className = "step-icon"; icon.textContent = (PLAN_META[step.status] || PLAN_META.pending)[0];
    const content = document.createElement("span"); content.textContent = step.title || step.id || "未命名步骤";
    if (step.detail) { const detail = document.createElement("span"); detail.className = "plan-detail"; detail.textContent = step.detail; content.appendChild(detail); }
    item.append(icon, content); list.appendChild(item);
  });
  taskPlanEl.appendChild(list);
}

function updateConversation(message) {
  const conversation = activeConversation(); if (!conversation) return;
  conversation.messages.push({ role: message.role, text: String(message.text || ""), error: !!message.error, createdAt: Date.now() });
  conversation.messages = conversation.messages.slice(-MAX_MESSAGES);
  if (message.role === "user" && conversation.title === "新对话") conversation.title = String(message.text || "新对话").replace(/\s+/g, " ").slice(0, 28);
  conversation.updatedAt = Date.now();
  conversations.sort((a, b) => b.updatedAt - a.updatedAt);
  renderHistory();
  queueSave();
}

async function send() {
  const text = inputEl.value.trim(); if (!text || sendBtn.disabled) return;
  inputEl.value = ""; inputEl.style.height = "auto";
  const conversation = activeConversation(); if (conversation) conversation.taskPlan = null;
  renderTaskPlan();
  addMessage(text, "user"); updateConversation({ role: "user", text });
  if (thinkingEl) thinkingEl.remove(); thinkingEl = addTool("正在思考…");
  setRunning(true);
  try {
    const response = await chrome.runtime.sendMessage({
      type: "sendChat",
      session_id: activeId,
      text,
      history: (activeConversation()?.messages || []).map((message) => ({ role: message.role, content: message.text })),
    });
    if (response?.error) throw new Error(response.error);
  } catch (error) {
    if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
    setRunning(false);
    const errorText = `发送失败：${error.message}`; addMessage(errorText, "error"); updateConversation({ role: "assistant", text: errorText, error: true });
  }
}

async function stop() {
  if (!running || stopBtn.disabled) return;
  stopBtn.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "cancelChat", session_id: activeId });
    if (response?.error) throw new Error(response.error);
  } catch (error) {
    setRunning(false);
    const errorText = `停止失败：${error.message}`; addMessage(errorText, "error");
  }
}

selectEl.addEventListener("change", () => { activeId = selectEl.value; queueSave(); renderHistory(); renderMessages(); });
newBtn.addEventListener("click", newConversation);
document.getElementById("settingsButton").addEventListener("click", () => chrome.runtime.openOptionsPage());
sendBtn.addEventListener("click", send);
stopBtn.addEventListener("click", stop);
inputEl.addEventListener("input", () => { inputEl.style.height = "auto"; inputEl.style.height = `${Math.min(inputEl.scrollHeight, 120)}px`; });
inputEl.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } });

chrome.runtime.onMessage.addListener((message) => {
  if (message.session_id && message.session_id !== activeId) return;
  if (message.type === "statusUpdate") activeStatus(message.status);
  if (message.type === "tool_event") {
    if (message.status === "thinking" && !thinkingEl) thinkingEl = addTool("正在思考…");
    if (message.status === "started") { if (thinkingEl) thinkingEl.remove(); thinkingEl = addTool(`正在执行：${toolLabel(message.tool)}`); }
    if (message.status === "done" && thinkingEl) { thinkingEl.textContent = `已完成：${toolLabel(message.tool)}`; thinkingEl = null; }
    scrollBottom();
  }
  if (message.type === "task_plan") {
    const conversation = activeConversation();
    if (conversation) { conversation.taskPlan = message.plan || null; conversation.updatedAt = Date.now(); queueSave(); }
    renderTaskPlan();
  }
  if (message.type === "chat_reply") {
    if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
    setRunning(false);
    addMessage(message.text, message.error ? "error" : "assistant"); updateConversation({ role: "assistant", text: message.text, error: message.error }); scrollBottom();
  }
  if (message.type === "chat_cancelled") {
    if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
    const conversation = activeConversation();
    if (conversation?.taskPlan) { conversation.taskPlan.status = "cancelled"; queueSave(); renderTaskPlan(); }
    setRunning(false);
    addTool(message.text || "任务已停止");
  }
});

(async function init() {
  await loadState();
  chrome.runtime.sendMessage({ type: "ensureService" }).catch(() => {});
  chrome.runtime.sendMessage({ type: "getStatus" }).then((response) => activeStatus(response?.status)).catch(() => activeStatus("disconnected"));
})();
