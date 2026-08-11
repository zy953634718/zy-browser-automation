// ============================================================
// Page Automator - Background Service Worker
// 通过 WebSocket 连接 Python 服务端，接收并执行自动化指令
// v2: 通用浏览器 AI 助手（对话转发 + Native Messaging 自动拉起服务）
// ============================================================

const DEFAULT_WS_URL = "ws://127.0.0.1:18767";
const LEGACY_WS_URL = "ws://127.0.0.1:18765";
const NATIVE_HOST_NAME = "com.browser.assistant"; // 需与 install.py 注册的 host 名一致
let ws = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let currentWsUrl = DEFAULT_WS_URL;
let currentStatus = "disconnected";
let wsEverOpened = false;        // 本次 Service Worker 生命周期内是否成功连过服务
let nativeRetryCount = 0;        // Native Messaging 拉起服务尝试次数
let reconnectDelay = 2000;       // 重连退避（2s → 5s → 10s → 封顶 30s）

function log(...args) {
  console.log("[Automator]", ...args);
}

function logError(...args) {
  console.error("[Automator]", ...args);
}

// ---- 生命周期 ----

chrome.runtime.onInstalled.addListener(() => {
  log("扩展已安装/更新");
  chrome.storage.local.set({ wsUrl: DEFAULT_WS_URL, autoReconnect: false });
  // Chrome/Edge 114+：点击扩展图标直接打开右侧 Side Panel，而不是弹出窗口。
  if (chrome.sidePanel?.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((e) => {
      logError("Side Panel 行为设置失败:", e);
    });
  }
  // 安装/更新后尝试拉起本地服务
  ensureServiceViaNative();
});

// 浏览器升级或 Service Worker 重新加载时也确保 Side Panel 行为生效。
if (chrome.sidePanel?.setPanelBehavior) {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}

// Service Worker 启动时（包括被 Chrome 唤醒），检查是否需要自动重连
(async () => {
  try {
    let { autoReconnect, wsUrl } = await chrome.storage.local.get(["autoReconnect", "wsUrl"]);
    if (!wsUrl || wsUrl === LEGACY_WS_URL) {
      wsUrl = DEFAULT_WS_URL;
      await chrome.storage.local.set({ wsUrl });
    }
    if (autoReconnect) {
      log("Service Worker 启动，自动重连...");
      connect(wsUrl || DEFAULT_WS_URL);
    }
  } catch (e) {
    logError("自动重连检查失败:", e);
  }
})();

// 接收 popup / options 的消息
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  log("收到消息:", msg.type, msg);
  switch (msg.type) {
    case "connect":
      connect(msg.wsUrl || DEFAULT_WS_URL);
      sendResponse({ ok: true });
      break;
    case "disconnect":
      disconnect();
      sendResponse({ ok: true });
      break;
    case "getStatus":
      sendResponse({
        status: currentStatus,
        wsUrl: currentWsUrl,
      });
      break;
    case "sendCommand":
      sendCommand(msg.command)
        .then((result) => sendResponse(result))
        .catch((e) => sendResponse({ error: e.message }));
      return true; // 异步
    case "ensureService":
      // 保证本地服务在线（未连接时先通过 Native Messaging 拉起，再重连）
      if (ws?.readyState === WebSocket.OPEN) {
        sendResponse({ ok: true, alreadyConnected: true });
      } else {
        ensureServiceViaNative().then((r) => {
          connect(currentWsUrl);
          sendResponse({ ok: true, ...r });
        });
      }
      break;
    case "sendChat":
      // 转发对话消息到服务端
      if (ws?.readyState !== WebSocket.OPEN) {
        sendResponse({ error: "服务未连接" });
        return;
      }
      ws.send(JSON.stringify({
        type: "chat",
        session_id: msg.session_id,
        text: msg.text,
        history: Array.isArray(msg.history) ? msg.history : undefined,
      }));
      sendResponse({ ok: true });
      break;
    case "cancelChat":
      if (ws?.readyState !== WebSocket.OPEN) {
        sendResponse({ error: "服务未连接" });
        return;
      }
      ws.send(JSON.stringify({ type: "cancel_chat", session_id: msg.session_id }));
      sendResponse({ ok: true });
      break;
    case "syncConfig":
      // 设置页保存后同步配置到服务端（WS 优先，HTTP 兜底）
      syncConfigToService(msg.config || {});
      sendResponse({ ok: true });
      break;
  }
});

// 把服务端推送转发给 popup（popup 关闭时静默忽略）
function broadcastToPopup(msg) {
  chrome.runtime.sendMessage(msg).catch(() => {});
}

// ---- WebSocket 连接管理 ----

function setStatus(status) {
  currentStatus = status;
  log("状态变更:", status);
  broadcastStatus(status);
}

function connect(wsUrl) {
  disconnect();
  currentWsUrl = wsUrl;
  chrome.storage.local.set({ wsUrl, autoReconnect: true });

  log("正在连接:", wsUrl);
  setStatus("connecting");

  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    logError("WebSocket 创建失败:", e);
    setStatus("error");
    return;
  }

  ws.onopen = () => {
    log("已连接到", wsUrl);
    wsEverOpened = true;
    nativeRetryCount = 0;
    reconnectDelay = 2000;
    setStatus("connected");
    clearTimeout(reconnectTimer);
    startHeartbeat();
    // 向服务端报告版本,便于诊断扩展加载的是否为新代码
    try {
      ws.send(JSON.stringify({ type: "hello", version: "2.2.0" }));
    } catch (e) {
      logError("发送 hello 失败:", e);
    }
    // 连接后自动同步扩展设置（扩展设置页优先于服务端 config.json）
    syncConfigToService();
  };

  ws.onmessage = (event) => {
    // 收到任何消息都重置心跳计时器
    resetHeartbeat();
    try {
      const msg = JSON.parse(event.data);
      // 服务端主动推送（对话回复 / 工具执行事件）→ 转发给 popup
      if (msg.type === "chat_reply" || msg.type === "tool_event" || msg.type === "task_plan" || msg.type === "chat_cancelled") {
        broadcastToPopup(msg);
        return;
      }
      handleRemoteCommand(msg);
    } catch (e) {
      logError("消息解析失败:", e);
    }
  };

  ws.onclose = (event) => {
    log("连接断开, code:", event.code, "reason:", event.reason);
    ws = null;
    stopHeartbeat();
    setStatus("disconnected");
    // 从未成功连过（服务未启动）→ 尝试通过 Native Messaging 拉起服务
    if (!wsEverOpened) {
      ensureServiceViaNative();
    }
    scheduleReconnect();
  };

  ws.onerror = (err) => {
    logError("WebSocket 错误:", err);
    // onerror 之后通常会触发 onclose，不在这里设 status 避免覆盖
  };
}

function disconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  stopHeartbeat();
  if (ws) {
    log("主动断开连接");
    ws.onclose = null; // 避免触发重连逻辑
    ws.close();
    ws = null;
  }
  chrome.storage.local.set({ autoReconnect: false });
  setStatus("disconnected");
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  // 指数退避：2s → 5s → 10s → 30s 封顶；连上过之后保持 5s
  if (wsEverOpened) {
    reconnectDelay = 5000;
  } else {
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  }
  reconnectTimer = setTimeout(() => {
    log("尝试重连...");
    connect(currentWsUrl);
  }, reconnectDelay);
}

// ---- 服务自动启动（Native Messaging） ----

/**
 * 通过 Native Messaging 让本地服务运行起来。
 * host（native/host.py）由 Chrome 自动拉起：探活端口，未监听则启动服务。
 * 最多尝试 3 次，间隔 3 秒。
 */
function ensureServiceViaNative() {
  if (nativeRetryCount >= 3) {
    logError("Native Messaging 拉起服务失败（已达最大重试次数）");
    return Promise.resolve({ ok: false, error: "max retries" });
  }
  nativeRetryCount += 1;
  log("通过 Native Messaging 拉起本地服务...");

  return new Promise((resolve) => {
    let port;
    try {
      port = chrome.runtime.connectNative(NATIVE_HOST_NAME);
    } catch (e) {
      logError("connectNative 失败:", e);
      resolve({ ok: false, error: e.message });
      return;
    }
    const timeout = setTimeout(() => {
      logError("Native Messaging 超时");
      try { port.disconnect(); } catch {}
      resolve({ ok: false, error: "timeout" });
    }, 10000);
    port.onMessage.addListener((resp) => {
      log("Native host 响应:", resp);
      clearTimeout(timeout);
      if (resp?.ok) {
        // 服务已就绪，稍等 1 秒让端口稳定，重连由调用方触发
        resolve({ ok: true, started: resp.started });
      } else {
        resolve({ ok: false, error: resp?.error || "unknown" });
      }
    });
    port.onDisconnect.addListener(() => {
      clearTimeout(timeout);
      resolve({ ok: false, error: "disconnected" });
    });
    port.postMessage({ type: "ensure_service", http_port: 18768 });
  });
}

// ---- 配置同步 ----

/** 把扩展设置（chrome.storage）同步给服务端；未连接时用 HTTP /config 兜底 */
async function syncConfigToService(config = {}) {
  let stored;
  try {
    stored = await chrome.storage.local.get(["apiKey", "model"]);
  } catch {
    stored = {};
  }
  const payload = {
    api_key: config.api_key ?? stored.apiKey ?? "",
    model: config.model ?? stored.model ?? "deepseek-chat",
  };
  if (ws?.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({ type: "sync_config", config: payload }));
      return;
    } catch (e) {
      logError("WS 配置同步失败:", e);
    }
  }
  // HTTP 兜底（host_permissions <all_urls> 已覆盖本地地址）
  try {
    await fetch("http://127.0.0.1:18768/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    logError("HTTP 配置同步失败:", e);
  }
}

function broadcastStatus(status) {
  chrome.runtime.sendMessage({ type: "statusUpdate", status }).catch(() => {
    // popup 未打开，忽略
  });
}

// ---- 心跳保活 ----

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, 15000); // 每 15 秒发一次 ping，防止 Service Worker 空闲被杀
}

function stopHeartbeat() {
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function resetHeartbeat() {
  if (heartbeatTimer) startHeartbeat();
}

// ---- 收到远程指令并执行 ----

async function handleRemoteCommand(msg) {
  const { id, command, params } = msg;
  log("执行指令:", command, JSON.stringify(params));

  let result;
  try {
    switch (command) {
      case "getImages":
        result = await getImages(params);
        break;
      case "downloadImages":
        result = await downloadImages(params);
        break;
      case "executeScript":
        result = await executeOnPage(params);
        break;
      case "scrollTo":
        result = await scrollTo(params);
        break;
      case "getTabs":
        result = await getTabs();
        break;
      case "takeScreenshot":
        result = await takeScreenshot(params);
        break;
      case "clickElement":
        result = await clickElement(params);
        break;
      case "closeTab":
        result = await closeTab(params);
        break;
      case "openUrl":
        result = await openUrl(params);
        break;
      case "getPageInfo":
        result = await getPageInfo(params);
        break;
      case "getPageContent":
        result = await getPageContent(params);
        break;
      default:
        result = { error: `未知指令: ${command}` };
    }
  } catch (e) {
    logError("指令执行失败:", e);
    result = { error: e.message || String(e) };
  }

  // 回复服务端
  if (id && ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ id, result }));
  }
}

// ---- 指令实现 ----

async function getImages(params = {}) {
  const tab = await getActiveTab(params?.tabId);
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: extractImages,
    args: [params || {}],
  });
  const images = results?.[0]?.result || [];
  return { images, count: images.length, tabUrl: tab.url, tabTitle: tab.title };
}

function extractImages(params) {
  const minSize = params?.minSize || 0;
  const images = [];
  const seen = new Set();

  function addImage(url, width, height, tagName) {
    if (!url || url.startsWith("data:image/svg")) return;
    if (seen.has(url)) return;
    if (minSize && (width < minSize || height < minSize)) return;
    seen.add(url);
    images.push({ url, width: width || 0, height: height || 0, tagName });
  }

  document.querySelectorAll("img").forEach((img) => {
    const src = img.currentSrc || img.src || img.dataset?.src || "";
    addImage(src, img.naturalWidth || img.width, img.naturalHeight || img.height, "img");
  });

  document.querySelectorAll("picture source[srcset]").forEach((source) => {
    const srcset = source.srcset.split(",")[0].trim().split(/\s+/)[0];
    if (srcset) addImage(srcset, 0, 0, "source");
  });

  const allEls = document.querySelectorAll("*");
  for (const el of allEls) {
    const bg = getComputedStyle(el).backgroundImage;
    if (bg && bg !== "none") {
      const match = bg.match(/url\(["']?(.*?)["']?\)/);
      if (match && match[1]) addImage(match[1], 0, 0, "background");
    }
  }

  document.querySelectorAll("video[poster]").forEach((v) => {
    addImage(v.poster, 0, 0, "video-poster");
  });

  document.querySelectorAll("a[href]").forEach((a) => {
    const href = a.href;
    if (/\.(jpe?g|png|gif|webp|bmp|svg|ico)(\?.*)?$/i.test(href)) {
      addImage(href, 0, 0, "link");
    }
  });

  return images;
}

async function downloadImages(params) {
  const { images, folder } = params;
  if (!images?.length) return { error: "未提供图片列表" };

  const results = [];
  for (const img of images) {
    const url = typeof img === "string" ? img : img.url;
    if (!url) continue;
    try {
      const filename = folder
        ? `${folder}/${getFilenameFromUrl(url)}`
        : getFilenameFromUrl(url);
      const downloadId = await chrome.downloads.download({
        url, filename, saveAs: false, conflictAction: "uniquify",
      });
      results.push({ url, downloadId, status: "started" });
    } catch (e) {
      results.push({ url, error: e.message });
    }
  }
  return { downloaded: results.length, results };
}

async function executeOnPage(params) {
  const tab = await getActiveTab(params?.tabId);
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: function(code, ...args) {
      try {
        const fn = new Function(code);
        return fn.apply(null, args);
      } catch(e) {
        return { error: e.message };
      }
    },
    args: [params.code, ...(params.args || [])],
    world: "MAIN",
  });
  return { result: results?.[0]?.result };
}

async function scrollTo(params = {}) {
  const tab = await getActiveTab(params?.tabId);
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (p) => {
      if (p?.to === "bottom") window.scrollTo(0, document.body.scrollHeight);
      else if (p?.to === "top") window.scrollTo(0, 0);
      else if (typeof p?.y === "number") window.scrollBy(0, p.y);
    },
    args: [params],
  });
  return { ok: true };
}

async function getTabs() {
  const tabs = await chrome.tabs.query({});
  return tabs.map((t) => ({
    id: t.id, url: t.url, title: t.title, active: t.active,
  }));
}

/** 关闭标签页 */
async function closeTab(params = {}) {
  const tabId = params?.tabId;
  if (tabId) {
    await chrome.tabs.remove(tabId);
    return { ok: true, closed: tabId };
  }
  // 默认关闭当前活动标签页
  const tab = await getActiveTab();
  await chrome.tabs.remove(tab.id);
  return { ok: true, closed: tab.id, url: tab.url, title: tab.title };
}

/** 打开 URL — 指定 tabId 时复用该标签页跳转(不新开 tab),否则新建标签页 */
async function openUrl(params = {}) {
  const { url, tabId, active } = params;
  if (!url || typeof url !== "string") return { error: "缺少 url 参数" };
  let tab;
  if (tabId) {
    tab = await chrome.tabs.update(tabId, { url, active: active !== false });
  } else {
    tab = await chrome.tabs.create({ url, active: active !== false });
  }
  return { ok: true, tabId: tab.id, url: tab.url || url };
}

/** 获取当前活动页面基本信息 */
async function getPageInfo(params = {}) {
  const tab = await getActiveTab(params?.tabId);
  return { title: tab.title, url: tab.url, tabId: tab.id };
}

/** 获取当前页面内容：正文（截断）、链接、图片 */
async function getPageContent(params = {}) {
  const tab = await getActiveTab(params?.tabId);
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (p) => {
      const maxTextLen = p?.maxTextLen || 2000;
      const includeLinks = p?.includeLinks !== false;
      const includeImages = !!p?.includeImages;

      let text = "";
      try {
        text = document.body ? document.body.innerText : "";
        if (text.length > maxTextLen) {
          text = text.substring(0, maxTextLen) + `\n...[已截断，全文 ${text.length} 字符]`;
        }
      } catch {}

      let links = [];
      if (includeLinks) {
        const seen = new Set();
        document.querySelectorAll("a[href]").forEach((a) => {
          const href = a.href;
          if (!href || href.startsWith("javascript:")) return;
          if (seen.has(href)) return;
          seen.add(href);
          links.push({ href, text: (a.innerText || a.textContent || "").trim().substring(0, 80) });
        });
        links = links.slice(0, 50);
      }

      let images = [];
      if (includeImages) {
        const seen = new Set();
        document.querySelectorAll("img").forEach((img) => {
          const src = img.currentSrc || img.src || "";
          if (!src || seen.has(src)) return;
          seen.add(src);
          images.push({ src, alt: img.alt || "" });
        });
        images = images.slice(0, 30);
      }

      return { title: document.title, url: location.href, text, links, images };
    },
    args: [params || {}],
  });
  return results?.[0]?.result || { error: "执行失败" };
}

/** 点击页面元素 */
async function clickElement(params = {}) {
  const tab = await getActiveTab(params?.tabId);

  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (p) => {
      let el = null;

      // 1. 按 CSS 选择器查找
      if (p.selector) {
        el = document.querySelector(p.selector);
      }

      // 2. 按文本内容查找
      if (!el && p.text) {
        const allEls = document.querySelectorAll(p.tagName || "*");
        for (const e of allEls) {
          if (e.textContent.trim() === p.text.trim()) {
            el = e;
            break;
          }
        }
      }

      // 3. 按文本模糊匹配
      if (!el && p.textContains) {
        const allEls = document.querySelectorAll(p.tagName || "*");
        for (const e of allEls) {
          if (e.textContent.includes(p.textContains)) {
            el = e;
            break;
          }
        }
      }

      if (!el) return { error: "未找到元素", selector: p.selector, text: p.text, textContains: p.textContains };

      // 滚动到可视区域
      el.scrollIntoView({ block: "center", behavior: "instant" });

      // 如果目标是链接或按钮内部，找到可点击的祖先元素
      let clickTarget = el;
      if (el.tagName !== "A" && el.tagName !== "BUTTON" && el.tagName !== "INPUT") {
        const parent = el.closest("a, button, [role='button'], [onclick]");
        if (parent) clickTarget = parent;
      }

      // 模拟真实点击事件
      clickTarget.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
      clickTarget.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
      clickTarget.click();

      return {
        ok: true,
        tagName: clickTarget.tagName,
        text: clickTarget.textContent.trim().substring(0, 100),
        href: clickTarget.href || null,
      };
    },
    args: [params],
  });

  return results?.[0]?.result || { error: "执行失败" };
}

/** 截取当前视口 */
async function takeScreenshot(params = {}) {
  const tab = await getActiveTab(params?.tabId);
  const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: "png" });
  const base64 = dataUrl.replace(/^data:image\/png;base64,/, "");
  return {
    data: base64,
    format: "png",
    tabUrl: tab.url,
    tabTitle: tab.title,
  };
}

// ---- 辅助函数 ----

async function getActiveTab(tabId) {
  if (tabId) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab) return tab;
    } catch {}
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) throw new Error("没有找到活动标签页");
  return tab;
}

function getFilenameFromUrl(url) {
  try {
    const pathname = new URL(url).pathname;
    const name = pathname.substring(pathname.lastIndexOf("/") + 1) || "image";
    if (!/\.\w{2,5}$/.test(name)) return name + ".jpg";
    return decodeURIComponent(name);
  } catch {
    return "image.jpg";
  }
}

async function sendCommand(command) {
  return new Promise((resolve, reject) => {
    if (ws?.readyState !== WebSocket.OPEN) {
      reject(new Error("未连接到服务端"));
      return;
    }
    const id = crypto.randomUUID();
    const handler = (event) => {
      try {
        const resp = JSON.parse(event.data);
        if (resp.id === id) {
          ws.removeEventListener("message", handler);
          resolve(resp.result);
        }
      } catch {}
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ id, command }));
    setTimeout(() => {
      ws.removeEventListener("message", handler);
      reject(new Error("指令超时"));
    }, 30000);
  });
}
