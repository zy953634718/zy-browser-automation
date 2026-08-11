---
name: browser-ai-assistant
description: 通用浏览器 AI 助手：Chrome 扩展 + 本地 Python 服务，通过 DeepSeek 对话控制浏览器（读取页面、点击、输入、滚动、开关标签页、截图等）。Use when Codex needs to安装、启动、调试或调用该浏览器自动化组件。
---

# 浏览器 AI 助手

通用浏览器自动化组件（不再绑定知衣等特定网站）：Chrome MV3 扩展提供聊天界面，本地 Python 服务承载 DeepSeek 对话循环与指令转发，Native Messaging 实现服务自动拉起。

## 架构

```
用户 ←→ popup 聊天界面（扩展）
              │ WS 18767
              ▼
        Python 服务（DeepSeek function calling 循环 + 指令转发）
              │ WS 18767 / HTTP 18768
              ▼
        扩展 service worker 执行页面操作（点击/输入/读取/截图…）
```

- `browser-extension/`：MV3 扩展（右侧 Side Panel 聊天界面、历史对话、设置页、service worker）
- `service/zy/`：Python 服务（server / agent / deepseek_client / tools / config / actions）
- `native/`：Native Messaging host（Chrome 自动拉起，负责启动服务）
- `install.bat` / `scripts/install.py`：一键安装（发布包自带运行时、依赖、注册表、启动服务）
- `scripts/run_service.py`：手动启动服务（从任意目录）
- `archive/zy/`：旧版知衣特有抓取代码归档（不被加载）

## 一键安装

普通 Windows 用户直接双击项目根目录的 `install.bat`；macOS 用户运行 `bash install.command`。正式发布包已内置对应平台的 `runtime/`，不需要预装 Python 或手动执行 pip。

开发者也可以运行：

```bash
python scripts/install.py
```

幂等可重跑。完成：检查运行时和依赖 → 注册 Native Messaging host（Chrome/Edge）→ 启动服务。

之后在 Chrome 打开 `chrome://extensions` → 开发者模式 → 「加载已解压的扩展」选择 `browser-extension/`。右键扩展图标 → 选项，填写 DeepSeek API Key 与模型名（默认 `deepseek-chat`）。点击扩展图标会在浏览器右侧打开 Side Panel；对话默认恢复上次会话，点击“新对话”才会创建新会话。扩展内置固定公钥，Native Messaging 授权不再需要用户手工配置扩展 ID。

**自动启动**：扩展检测到本地服务未运行时会通过 Native Messaging 自动拉起，无需手动启动。移动项目目录后需重跑 `scripts/install.py`（注册表路径固定）。

## 常用接口

服务默认监听 WebSocket `127.0.0.1:18767`（扩展）与 HTTP `127.0.0.1:18768`。

```bash
curl http://127.0.0.1:18768/status                          # 状态（含 has_api_key、会话数）
curl -X POST http://127.0.0.1:18768/command \
  -H "Content-Type: application/json" \
  -d '{"command":"getPageContent","params":{"maxTextLen":2000}}'   # 直接指令
curl -X POST http://127.0.0.1:18768/chat \
  -H "Content-Type: application/json" \
  -d '{"text":"这个页面讲了什么"}'                              # 对话（可脱离扩展测试）
curl -X POST http://127.0.0.1:18768/config \
  -H "Content-Type: application/json" \
  -d '{"api_key":"sk-...","model":"deepseek-chat"}'          # 配置同步
curl "http://127.0.0.1:18768/screenshot?dir=screenshots"      # 截图保存
```

## 扩展指令集

`getPageInfo`、`getPageContent`、`clickElement`、`executeScript`、`scrollTo`、`getTabs`、`takeScreenshot`、`getImages`、`downloadImages`、`closeTab`、`openUrl`。

对话中 DeepSeek 通过 function calling 自动使用这些工具；20 个工具定义见 `service/zy/tools.py`。

## 运行规则

- 只修改本目录中的副本，不依赖主仓库。
- 手动启动：`python scripts/run_service.py`（或 `.venv\Scripts\pythonw.exe service/zy/server.py`）。
- 若扩展显示未连接：先确认服务进程（`logs/server.log`）、再确认 Native host 注册（重跑 install.py）、最后确认 Chrome 已重新加载扩展。
- 服务依赖仅 `aiohttp` 与 `websockets`（发布包已随 `runtime/` 一并携带）。
- 复杂页面默认最多 16 轮工具调用；`execute_script` 结果最多保留 12000 字符。达到轮次上限后会关闭工具并基于已有结果强制总结，而不是直接终止。
- Agent 支持 `set_task_plan`/`update_task_plan` 复杂任务规划与进度展示、可中止长任务、`remember`/`recall_memory` 本地长期记忆、`list_skills`/`read_skill`/`create_skill` 本地 Skill，以及 `save_file` 将生成内容保存到 `outputs/`。
