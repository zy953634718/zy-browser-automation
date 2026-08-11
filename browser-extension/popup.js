// popup.js — 聊天界面交互逻辑

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const btnSend = document.getElementById("btnSend");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");

// 会话 id：每次打开 popup 一个会话（sessionStorage 在 popup 重开时失效）
let sessionId = sessionStorage.getItem("sessionId") || crypto.randomUUID();
sessionStorage.setItem("sessionId", sessionId);

// 本地消息序号：用于工具事件行与回复配对
let pendingThinking = null;   // 正在思考的占位元素
let activeToolRow = null;     // 当前工具执行行

// ---- 初始化 ----

function init() {
  document.getElementById("btnSettings").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });
  inputEl.addEventListener("input", autoGrow);
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  btnSend.addEventListener("click", send);

  // 打开时保证本地服务在线
  chrome.runtime.sendMessage({ type: "ensureService" }).catch(() => {});
  refreshStatus();
}

function refreshStatus() {
  chrome.runtime.sendMessage({ type: "getStatus" })
    .then((resp) => {
      if (resp) updateStatus(resp.status);
    })
    .catch(() => updateStatus("disconnected"));
}

// ---- 消息渲染 ----

function updateStatus(status) {
  statusDot.className = "dot " + (status || "disconnected");
  const map = {
    connected: "已连接",
    disconnected: "未连接",
    connecting: "连接中…",
    error: "连接错误",
  };
  statusText.textContent = map[status] || status || "未连接";
  // 未连接时提示自动拉起
  if (status === "disconnected") {
    statusText.textContent = "未连接，正在拉起服务…";
  }
  btnSend.disabled = status !== "connected";
}

function addMessage(text, cls) {
  const el = document.createElement("div");
  el.className = "msg " + (cls || "assistant");
  el.textContent = text;
  messagesEl.appendChild(el);
  scrollBottom();
  return el;
}

function addToolRow(text) {
  const el = document.createElement("div");
  el.className = "msg tool";
  el.innerHTML = text;
  messagesEl.appendChild(el);
  scrollBottom();
  return el;
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 90) + "px";
}

// ---- 发送 ----

function send() {
  const text = inputEl.value.trim();
  if (!text || btnSend.disabled) return;

  inputEl.value = "";
  inputEl.style.height = "auto";
  addMessage(text, "user");

  // 清掉旧的 thinking/工具行，加新的 thinking 占位
  if (pendingThinking) pendingThinking.remove();
  pendingThinking = addToolRow('<span class="pulse">正在思考</span>');
  activeToolRow = null;

  chrome.runtime.sendMessage({ type: "sendChat", session_id: sessionId, text })
    .catch((e) => {
      if (pendingThinking) { pendingThinking.remove(); pendingThinking = null; }
      addMessage("发送失败：" + e.message, "error");
    });
}

// ---- 服务端推送 ----

chrome.runtime.onMessage.addListener((msg) => {
  // 会话过滤：只处理本 popup 会话的消息
  if (msg.session_id && msg.session_id !== sessionId) return;

  switch (msg.type) {
    case "statusUpdate":
      updateStatus(msg.status);
      break;

    case "tool_event":
      if (msg.status === "thinking") {
        // 服务端开始处理
        if (!pendingThinking) {
          pendingThinking = addToolRow('<span class="pulse">正在思考</span>');
        }
      } else if (msg.status === "started") {
        // 工具开始执行：把 thinking 行替换为工具行
        if (pendingThinking) { pendingThinking.remove(); pendingThinking = null; }
        activeToolRow = addToolRow(
          '正在执行：<span class="tool-name">' + toolLabel(msg.tool, msg.args) + "</span>"
        );
      } else if (msg.status === "done") {
        if (activeToolRow) {
          activeToolRow.innerHTML =
            '✅ <span class="tool-name">' + toolLabel(msg.tool, msg.args) + "</span> 完成";
          activeToolRow = null;
        }
      }
      break;

    case "chat_reply":
      if (pendingThinking) { pendingThinking.remove(); pendingThinking = null; }
      if (activeToolRow) { activeToolRow.remove(); activeToolRow = null; }
      addMessage(msg.text, msg.error ? "error" : "assistant");
      break;
  }
});

function toolLabel(tool, args) {
  if (tool === "get_page_content") return "读取页面内容";
  if (tool === "get_page_info") return "获取页面信息";
  if (tool === "click_element") return "点击元素" + (args?.text ? "「" + args.text + "」" : "");
  if (tool === "input_text") return "输入「" + (args?.text || "") + "」";
  if (tool === "open_url") return "打开 " + (args?.url || "");
  if (tool === "close_tab") return "关闭标签页";
  if (tool === "list_tabs") return "列出标签页";
  if (tool === "scroll_to") return "滚动页面";
  if (tool === "get_images") return "获取页面图片";
  if (tool === "take_screenshot") return "截图";
  if (tool === "execute_script") return "执行自定义脚本";
  if (tool === "wait") return "等待 " + (args?.seconds || "") + " 秒";
  return tool;
}

// ---- 启动 ----

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
