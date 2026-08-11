# 浏览器 AI 助手

一个由 Chrome/Edge 扩展、本地 Python 服务和 Native Messaging Host 组成的通用浏览器自动化 Agent。
用户在浏览器右侧 Side Panel 中用自然语言描述任务，DeepSeek 负责规划和决策，本地服务负责会话、工具调用和数据持久化，扩展负责在当前浏览器页面执行操作。

当前扩展版本：`2.2.0`

## 功能概览

- 读取当前页面标题、URL、正文、链接和图片。
- 通过文本、模糊文本或 CSS Selector 点击页面元素。
- 定位输入框并填写文本，兼容常见 React/Vue 受控输入框。
- 滚动页面、打开或关闭标签页、列出全部标签页。
- 提取页面图片、下载图片和截取当前视口。
- 在页面主世界执行自定义 JavaScript。
- 复杂任务自动生成执行计划，并在 Side Panel 实时显示进度。
- 支持随时停止长任务；已完成的浏览器操作和已写入的文件会保留。
- 将 Markdown、JSON、CSV、文本或代码保存到项目 `outputs/` 目录。
- 支持本地 Skill：发现、读取和创建可复用的工作流。
- 支持本地长期记忆：仅在用户明确要求时保存偏好、规则或工作经验。
- 扩展自动通过 Native Messaging 拉起本地服务，无需每次手动启动 Python。
- 提供 HTTP 接口，便于使用 `curl` 或其他脚本直接调用。

## 工作原理

```text
┌──────────────────────────────┐
│ Chrome / Edge 扩展            │
│ Side Panel + MV3 Service Worker│
└──────────────┬───────────────┘
               │ WebSocket 127.0.0.1:18767
               ▼
┌──────────────────────────────┐       HTTPS
│ Python 本地服务                │ ───────────────► DeepSeek API
│ server → agent → tools        │
│ HTTP 127.0.0.1:18768          │
└──────────────┬───────────────┘
               │ Native Messaging（按需启动）
               ▼
┌──────────────────────────────┐
│ native/host.py                │
│ 检测端口并拉起 service/server │
└──────────────────────────────┘
```

服务只监听 `127.0.0.1`，默认不会接受局域网或公网连接。每次对话由 Agent 调用 DeepSeek 的 OpenAI 兼容 `chat/completions` 接口；浏览器工具调用通过 WebSocket 转发给扩展，再将结果返回给模型继续决策。

## 快速开始

### 方式 A：使用正式发布包（推荐普通用户）

正式发布包包含对应平台的 Python 运行时和服务依赖，不需要预装 Python、pip 或手动配置环境变量。

1. 解压发布包，不要只复制其中的单个文件。
2. Windows 双击根目录的 `install.bat`。
3. macOS 在终端进入项目目录并执行：

   ```bash
   bash install.command
   ```

4. 打开 Chrome 的 `chrome://extensions`，或 Edge 的 `edge://extensions`。
5. 开启“开发者模式”，点击“加载已解压的扩展”，选择包内的 `browser-extension/` 文件夹。
6. 点击扩展的“设置”按钮，填写 DeepSeek API Key，确认模型名（默认 `deepseek-chat`），点击保存。
7. 打开任意网页，点击扩展图标，在右侧 Side Panel 输入任务。

安装脚本会检查运行时、安装 `aiohttp` 和 `websockets`、生成 Native Messaging 清单、注册 Chrome/Edge，并尝试启动本地服务。移动项目目录后，请在新位置重新运行安装脚本，以更新清单中的绝对路径。

图文安装、配置和排障说明见 [使用说明.html](使用说明.html)，可直接双击离线打开。

### 方式 B：从源码运行（推荐开发者）

要求：Windows 或 macOS、Python 3.10+、Chrome/Edge，以及可用的 DeepSeek API Key。

```powershell
# Windows PowerShell
python scripts/install.py
```

```bash
# macOS / Linux
python3 scripts/install.py
```

源码安装会优先使用 `runtime/` 或已有 `.venv`；只有在源码环境没有可用虚拟环境时，才会使用系统 Python 创建项目根目录下的 `.venv`。依赖安装完成后，脚本会注册 Native Host 并启动服务。

如果只想安装而不启动服务：

```bash
python scripts/install.py --no-start
```

离线安装（前提是依赖已在本地缓存或发布运行时内）：

```bash
python scripts/install.py --offline
```

然后按“加载已解压的扩展”步骤加载 `browser-extension/`。

## 配置

### 在扩展设置页配置（推荐）

扩展设置页保存以下项目：

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| DeepSeek API Key | 调用模型所需的密钥 | 无 |
| Model | DeepSeek 模型名称 | `deepseek-chat` |
| WebSocket URL | 扩展连接的本地服务地址 | `ws://127.0.0.1:18767` |

保存后，扩展会优先通过 WebSocket 同步到服务；服务未连接时会通过 `POST /config` 进行 HTTP 兜底同步。API Key 会保存在浏览器本地存储和服务目录的 `service/config.local.json`，该文件已被 `.gitignore` 排除。

### 配置文件和环境变量

默认配置位于 [service/config.json](service/config.json)。不要把真实 API Key 写入并提交该文件；本机覆盖请使用 `service/config.local.json`，或通过扩展设置页保存。

服务配置优先级（高到低）：

1. 运行时覆盖（扩展同步或 `POST /config`）。
2. 环境变量：`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`。
3. `service/config.local.json` 和 `service/config.json`。
4. 代码内默认值。

可用配置示例：

```json
{
  "api_key": "",
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com",
  "ws_port": 18767,
  "http_port": 18768,
  "max_tool_rounds": 16,
  "tool_result_max_len": 4000,
  "page_content_result_max_len": 8000,
  "execute_script_result_max_len": 12000,
  "api_timeout": 60
}
```

环境变量示例：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
$env:DEEPSEEK_MODEL = "deepseek-chat"
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
python scripts/run_service.py
```

## 手动启动和停止

安装脚本通常会自动启动服务。需要手动启动时，在项目根目录运行：

```bash
python scripts/run_service.py
```

也可以直接运行入口：

```bash
python service/zy/server.py
```

服务启动后会打印 WebSocket、HTTP、模型和 API Key 状态。服务日志位于 `logs/server.log` 和 `logs/zy-bot.log`。Native Host 日志位于 `logs/native-host.log`。

Windows 下服务由 `pythonw.exe` 以无窗口、独立进程方式启动；关闭浏览器不会删除已经生成的 `outputs/`、记忆或日志文件。

## HTTP API

默认地址：`http://127.0.0.1:18768`。所有请求和响应均为 UTF-8 JSON。

### 查看状态

```bash
curl http://127.0.0.1:18768/status
```

响应示例：

```json
{
  "extension_connected": true,
  "extension_version": "2.2.0",
  "ws_port": 18767,
  "http_port": 18768,
  "model": "deepseek-chat",
  "has_api_key": true,
  "sessions": 1,
  "active_tasks": 0
}
```

### 直接执行扩展指令

`POST /command` 会把命令转发给已连接的扩展。扩展未连接时会返回错误。

```bash
curl -X POST http://127.0.0.1:18768/command \
  -H "Content-Type: application/json" \
  -d '{"command":"getPageContent","params":{"maxTextLen":2000,"includeLinks":true}}'
```

支持的底层命令包括：`getPageInfo`、`getPageContent`、`clickElement`、`inputText`、`scrollTo`、`openUrl`、`closeTab`、`getTabs`、`getImages`、`downloadImages`、`takeScreenshot`、`executeScript`。

### 发起 Agent 对话

`POST /chat` 会执行完整的 DeepSeek function-calling 循环，并返回最终回答、工具事件和任务计划。可以传入 `session_id` 复用服务内存中的会话。

```bash
curl -X POST http://127.0.0.1:18768/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo","text":"读取当前页面并总结主要内容"}'
```

响应结构：

```json
{
  "reply": "页面主要介绍……",
  "error": false,
  "tools": [],
  "plans": []
}
```

没有扩展连接时仍可测试模型对话，但涉及页面读取、点击或截图的工具会返回“浏览器扩展未连接”。

### 同步配置

```bash
curl -X POST http://127.0.0.1:18768/config \
  -H "Content-Type: application/json" \
  -d '{"api_key":"sk-...","model":"deepseek-chat"}'
```

服务只接受代码中声明的配置字段，并将有效字段持久化到 `service/config.local.json`。

### 保存当前视口截图

```bash
curl "http://127.0.0.1:18768/screenshot?dir=screenshots"
```

接口调用扩展的 `takeScreenshot`，将 PNG 写入指定目录，并返回保存路径、文件大小、页面 URL 和标题。

## WebSocket 协议（扩展内部）

扩展连接 `ws://127.0.0.1:18767` 后会发送：

```json
{"type":"hello","version":"2.2.0"}
```

聊天请求：

```json
{"type":"chat","session_id":"demo","text":"总结当前页面","history":[]}
```

取消任务：

```json
{"type":"cancel_chat","session_id":"demo"}
```

服务端会推送 `thinking`、`started`、`done` 等 `tool_event`，以及 `task_plan`、`chat_reply`、`chat_cancelled`。浏览器指令使用 `{id, command, params}` 请求和 `{id, result}` 回复。该通道仅绑定回环地址，通常不需要手动调用。

## Agent 工具清单

DeepSeek 可通过 function calling 使用以下 20 个工具：

| 工具 | 用途 |
| --- | --- |
| `get_page_info` | 获取当前标签页标题、URL 和 ID |
| `get_page_content` | 读取正文、链接和图片（支持长度截断） |
| `click_element` | 按精确文本、包含文本或 CSS 选择器点击 |
| `input_text` | 按 placeholder 或 CSS 选择器填写输入框 |
| `scroll_to` | 滚动到顶部、底部或按像素移动 |
| `open_url` | 新建标签页或复用指定标签页打开 URL |
| `close_tab` | 关闭指定或当前活动标签页 |
| `list_tabs` | 列出所有标签页及活动状态 |
| `get_images` | 获取图片 URL、尺寸和来源信息 |
| `take_screenshot` | 获取当前视口 PNG（Base64） |
| `execute_script` | 在页面主世界执行自定义 JavaScript |
| `save_file` | 将文本类结果安全保存到 `outputs/` |
| `list_skills` | 列出本地可用 Skill |
| `read_skill` | 读取指定 Skill 的 Markdown 工作流 |
| `create_skill` | 在 `skills/<name>/SKILL.md` 创建工作流 |
| `remember` | 保存用户明确要求记住的内容 |
| `recall_memory` | 查询本地长期记忆和对话索引 |
| `set_task_plan` | 创建最多 12 步的复杂任务计划 |
| `update_task_plan` | 更新计划步骤状态和说明 |
| `wait` | 等待 1–30 秒，用于页面加载或动画 |

工具结果会按配置截断后写入模型上下文：普通工具默认 4000 字符，`get_page_content` 默认 8000 字符，`execute_script` 默认 12000 字符。单次对话默认最多 16 轮工具调用，达到上限后会再请求一次不带工具的总结。

## 项目结构

```text
.
├─ browser-extension/          # Chrome MV3 扩展
│  ├─ manifest.json             # 权限、Side Panel、Native Messaging 声明
│  ├─ background_v2.js          # WebSocket、Native Host 和页面指令分发
│  ├─ side_panel.html/js        # 侧边栏聊天、历史会话和任务计划
│  ├─ popup.html/js             # 扩展弹窗
│  ├─ options.html/js           # API Key、模型和 WS 地址设置
│  └─ icons/                    # 扩展图标
├─ service/
│  ├─ config.json               # 默认配置（不要放真实密钥）
│  ├─ requirements.txt          # aiohttp、websockets
│  └─ zy/
│     ├─ server.py              # WebSocket + HTTP 服务入口
│     ├─ agent.py               # 会话和 DeepSeek 工具调用循环
│     ├─ tools.py               # 工具定义和执行分发
│     ├─ deepseek_client.py     # OpenAI 兼容 API 客户端
│     ├─ config.py              # 配置优先级和本机覆盖
│     ├─ memory.py              # 长期记忆和对话索引
│     ├─ skills.py              # 本地 Skill 发现、读取和创建
│     ├─ actions/                # 点击文本、输入文本等辅助动作
│     └─ log.py                  # 控制台和文件日志
├─ native/
│  ├─ host.py                   # Native Messaging 启动器
│  └─ host-manifest.template.json
├─ scripts/
│  ├─ install.py                # 安装、依赖、Native Host 注册和启动
│  ├─ install.bat                # Windows 安装入口
│  ├─ run_service.py             # 手动启动服务
│  └─ build_release.py           # 白名单发布包构建
├─ tests/                       # Agent、工具和历史修复测试
├─ docs/images/                 # 使用说明图片资源
├─ 使用说明.html                # 离线图文手册
├─ SKILL.md                     # Agent 可读取的项目工作流说明
└─ README.md
```

以下目录由运行时生成或仅用于本机，不应提交：

- `service/config.local.json`：扩展同步的本机配置，可能包含 API Key。
- `service/data/agent_memory.json`：长期记忆和对话索引。
- `skills/`：Agent 创建的本地 Skill。
- `outputs/`：Agent 保存的报告、数据和代码。
- `logs/`：服务、Native Host 和 Agent 日志。
- `.venv/`、`dist/`、`__pycache__/`：开发环境、发布产物和缓存。

## 开发和测试

安装依赖后运行全部测试：

```bash
python -m unittest discover -s tests -v
```

手动启动服务并观察日志：

```bash
python scripts/run_service.py
```

修改扩展代码后，在 `chrome://extensions` 页面点击扩展的“重新加载”，再重新打开 Side Panel。修改 Python 服务后重启服务；Native Host 清单或项目路径变化后重新运行 `python scripts/install.py`。

### 构建发布包

```bash
python scripts/install.py
python scripts/build_release.py
```

默认产物为 `dist/browser-ai-assistant/`。发布脚本采用白名单复制，只包含扩展、服务、Native Host、安装脚本、文档和运行时，不会复制 API Key、长期记忆、日志、测试、`outputs/` 或开发缓存。

构建平台决定运行时平台：macOS 发布包应在 macOS 上构建，不能把 Windows 的 `runtime/` 直接复制给 macOS 用户。

如果加载的是未授权的解压扩展，且扩展页面显示的 ID 与内置 ID 不同，安装前指定 ID：

```powershell
$env:BROWSER_ASSISTANT_EXTENSION_ID = "扩展页面显示的 32 位 ID"
python scripts/install.py
```

## 故障排查

### 扩展显示“未连接”

1. 查看 `http://127.0.0.1:18768/status` 是否能访问。
2. 检查 `logs/server.log`、`logs/zy-bot.log` 和 `logs/native-host.log`。
3. 重新运行 `python scripts/install.py`，确保 Native Host 注册路径是当前项目路径。
4. 在扩展管理页重新加载 `browser-extension/`。
5. 确认本机没有其他程序占用 `18767` 或 `18768` 端口。

### API Key 错误

- 在扩展设置页重新保存完整的 DeepSeek API Key。
- `401` 表示密钥无效；`429` 表示请求频率过高。
- 检查 `DEEPSEEK_BASE_URL` 是否包含正确的 API 根地址，服务会自动追加 `/chat/completions`。
- 不要把密钥写入 Git 跟踪文件或发布压缩包。

### 页面操作失败

- 确认目标页面是当前活动标签页，并已等待页面加载完成。
- 优先让 Agent 先读取 `get_page_info` 或 `get_page_content`，再执行点击或输入。
- 部分浏览器内部页面（例如 `chrome://extensions`）、跨域受限页面或弹窗不允许脚本注入。
- 复杂操作可以使用 `execute_script`，但该工具会在页面主世界执行任意 JavaScript，请仅使用可信任务。

### 安装脚本窗口立即关闭

在项目目录打开 PowerShell/命令提示符后重新运行安装命令，保留完整错误输出；Windows 也可以双击根目录 `install.bat`，脚本结束时会暂停窗口。发布包应包含 `runtime/`；源码环境请安装 Python 3.10+。

## 安全与隐私

- HTTP 和 WebSocket 服务只监听 `127.0.0.1`，但本机上的其他程序理论上可以调用这些接口；不要把端口转发到公网。
- 扩展声明了 `<all_urls>`、`scripting`、`tabs`、`downloads` 等权限，能够读取和操作当前浏览器页面。请只从可信来源加载扩展。
- 页面内容、用户指令和工具结果会发送到配置的 DeepSeek API；不要在不适合外发的页面上使用，除非你已确认服务商的数据政策。
- API Key 仅用于本机服务请求认证，扩展和服务都使用本地存储；`config.local.json`、记忆、日志和输出目录均被 Git 忽略。
- `save_file` 只允许写入项目根目录的 `outputs/`，禁止绝对路径和 `..` 路径穿越。
- 长期记忆只在用户明确要求“记住”时写入 `service/data/agent_memory.json`，可直接删除该文件清空本机记忆。

## 版本控制提示

提交前检查：

```bash
git status
git diff -- service/config.json README.md
```

确认没有把 `service/config.local.json`、`service/data/agent_memory.json`、`logs/`、`outputs/` 或 `.venv/` 加入提交后再推送。
