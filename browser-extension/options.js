// options.js — 设置页逻辑

const DEFAULT_WS_URL = "ws://127.0.0.1:18767";
const LEGACY_WS_URL = "ws://127.0.0.1:18765";
const DEFAULT_MODEL = "deepseek-chat";

const apiKeyEl = document.getElementById("apiKey");
const modelEl = document.getElementById("model");
const wsUrlEl = document.getElementById("wsUrl");
const btnSave = document.getElementById("btnSave");
const saveStatus = document.getElementById("saveStatus");

async function load() {
  try {
    const { apiKey, model, wsUrl } = await chrome.storage.local.get(["apiKey", "model", "wsUrl"]);
    apiKeyEl.value = apiKey || "";
    modelEl.value = model || DEFAULT_MODEL;
    wsUrlEl.value = !wsUrl || wsUrl === LEGACY_WS_URL ? DEFAULT_WS_URL : wsUrl;
  } catch (e) {
    console.warn("读取存储失败:", e);
  }
}

async function save() {
  const apiKey = apiKeyEl.value.trim();
  const model = modelEl.value.trim() || DEFAULT_MODEL;
  const wsUrl = wsUrlEl.value.trim() || DEFAULT_WS_URL;

  if (!apiKey) {
    setStatus("API Key 不能为空", "err");
    return;
  }

  try {
    await chrome.storage.local.set({ apiKey, model, wsUrl });
  } catch (e) {
    setStatus("保存失败: " + e.message, "err");
    return;
  }

  // 同步到本地服务（background 处理：WS 优先，HTTP 兜底）
  try {
    await chrome.runtime.sendMessage({ type: "syncConfig", config: { api_key: apiKey, model } });
  } catch (e) {
    console.warn("配置同步失败:", e);
  }

  setStatus("已保存并同步 ✓", "ok");
}

function setStatus(text, cls) {
  saveStatus.textContent = text;
  saveStatus.className = cls === "ok" ? "save-ok" : "save-err";
  setTimeout(() => { saveStatus.textContent = ""; }, 3000);
}

btnSave.addEventListener("click", save);

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", load);
} else {
  load();
}
