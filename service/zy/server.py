"""
浏览器 AI 助手 — Python 服务端

双通道：
  WebSocket 127.0.0.1:18767   — 扩展连接（指令回复 + chat 对话协议）
  HTTP      127.0.0.1:18768   — 外部脚本/curl（指令直连 + 对话 + 配置同步）

用法示例:
    curl http://127.0.0.1:18768/status
    curl -X POST http://127.0.0.1:18768/command \
      -H "Content-Type: application/json" \
      -d '{"command": "getPageContent", "params": {}}'
    curl -X POST http://127.0.0.1:18768/chat \
      -H "Content-Type: application/json" \
      -d '{"text": "这个页面讲了什么？"}'
"""

import asyncio
import base64
import json
import sys
import uuid
from asyncio import Queue
from pathlib import Path

import websockets
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zy import config, agent
from zy.log import logger

# ---- 配置 ----
WS_HOST = "127.0.0.1"

# ---- 全局状态 ----
extension_ws = None  # 当前连接的扩展
extension_version = None  # 扩展版本标识(hello 消息)
pending_requests: dict[str, Queue] = {}  # id -> 回复队列
chat_tasks: dict[str, asyncio.Task] = {}  # session_id -> 当前可取消的对话任务


def json_response(data, *, status=200):
    """JSON 响应，确保中文不被转义为 Unicode"""
    return web.json_response(data, status=status, dumps=lambda d: json.dumps(d, ensure_ascii=False))


# ---- WebSocket 服务端 (扩展连接到这里) ----

async def push_to_extension(type_, **payload):
    """向扩展推送一条服务端消息（chat 协议），连接断开时静默忽略"""
    if extension_ws is None:
        return
    try:
        await extension_ws.send(json.dumps({"type": type_, **payload}, ensure_ascii=False))
    except Exception:
        pass


async def ws_handler(websocket):
    global extension_ws, extension_version
    logger.info("[WS] 扩展已连接: %s", websocket.remote_address)
    extension_ws = websocket
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type")

                # 心跳消息，忽略
                if msg_type == "ping":
                    continue
                # 扩展版本标识
                if msg_type == "hello":
                    extension_version = msg.get("version")
                    logger.info("[WS] 扩展版本: %s", extension_version)
                    continue
                # 对话消息 → 异步处理，不阻塞消息循环
                if msg_type == "chat":
                    session_id = msg.get("session_id") or uuid.uuid4().hex
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue
                    existing_task = chat_tasks.get(session_id)
                    if existing_task and not existing_task.done():
                        await push_to_extension(
                            "chat_reply", session_id=session_id,
                            text="正在处理上一条消息，请先等待完成或点击“停止”。", error=False,
                        )
                        continue
                    agent.restore_session(session_id, msg.get("history"))
                    task = asyncio.create_task(
                        agent.handle_chat(push_to_extension, send_to_extension, session_id, text)
                    )
                    chat_tasks[session_id] = task

                    def _clear_chat_task(done_task, sid=session_id):
                        if chat_tasks.get(sid) is done_task:
                            chat_tasks.pop(sid, None)

                    task.add_done_callback(_clear_chat_task)
                    continue
                # Manus 风格的长任务控制：允许用户从侧边栏主动停止当前任务。
                if msg_type == "cancel_chat":
                    session_id = msg.get("session_id")
                    task = chat_tasks.get(session_id)
                    if task and not task.done():
                        task.cancel()
                        await push_to_extension(
                            "chat_cancelled", session_id=session_id, text="任务已停止"
                        )
                    else:
                        await push_to_extension(
                            "chat_cancelled", session_id=session_id, text="当前没有正在执行的任务"
                        )
                    continue
                # 配置同步（扩展设置页优先于 config.json）
                if msg_type == "sync_config":
                    updates = msg.get("config") or {}
                    config.update_runtime(updates, persist=True)
                    logger.info("[WS] 收到扩展配置同步: %s", list(updates.keys()))
                    continue
                # 指令回复
                msg_id = msg.get("id")
                if msg_id and msg_id in pending_requests:
                    await pending_requests[msg_id].put(msg.get("result"))
            except json.JSONDecodeError:
                logger.warning("[WS] 无效消息: %s", raw[:200])
    except websockets.ConnectionClosed:
        pass
    finally:
        if extension_ws is websocket:
            extension_ws = None
            extension_version = None
        logger.info("[WS] 扩展已断开")


async def send_to_extension(command: str, params: dict = None, timeout: float = 15.0):
    """发送指令给扩展并等待回复"""
    if not extension_ws:
        return {"error": "浏览器扩展未连接"}

    msg_id = str(uuid.uuid4())
    queue: Queue = Queue()
    pending_requests[msg_id] = queue

    try:
        await extension_ws.send(json.dumps({
            "id": msg_id,
            "command": command,
            "params": params or {},
        }))
        result = await asyncio.wait_for(queue.get(), timeout=timeout)
        return result
    except asyncio.TimeoutError:
        return {"error": "指令超时，扩展未响应"}
    finally:
        pending_requests.pop(msg_id, None)


# ---- HTTP 接口 (外部脚本 / curl 调用) ----

async def http_command(request: web.Request):
    """POST /command — 发送任意指令给扩展"""
    try:
        body = await request.json()
    except Exception:
        return json_response({"error": "请求体必须是 JSON"}, status=400)

    command = body.get("command")
    params = body.get("params", {})
    if not command:
        return json_response({"error": "缺少 command 字段"}, status=400)

    result = await send_to_extension(command, params)
    return json_response(result)


async def http_status(request: web.Request):
    """GET /status — 查看状态"""
    return json_response({
        "extension_connected": extension_ws is not None,
        "extension_version": extension_version,
        "ws_port": config.get("ws_port"),
        "http_port": config.get("http_port"),
        "model": config.get("model"),
        "has_api_key": config.has_api_key(),
        "sessions": agent.session_count(),
        "active_tasks": sum(1 for task in chat_tasks.values() if not task.done()),
    })


async def _run_http_chat(session_id: str, text: str) -> dict:
    """HTTP 版对话：无 WS 推送通道，收集 tool_event 与最终 chat_reply"""
    events = []

    async def sink(type_, **payload):
        events.append({"type": type_, **payload})

    await agent.handle_chat(sink, send_to_extension, session_id, text)

    reply = next((e for e in reversed(events) if e["type"] == "chat_reply"), None)
    tool_events = [e for e in events if e["type"] == "tool_event"]
    plans = [e for e in events if e["type"] == "task_plan"]
    return {
        "reply": (reply or {}).get("text"),
        "error": (reply or {}).get("error", False),
        "tools": tool_events,
        "plans": plans,
    }


async def http_chat(request: web.Request):
    """POST /chat — 发起对话（无扩展连接时也可测试对话循环）"""
    try:
        body = await request.json()
    except Exception:
        return json_response({"error": "请求体必须是 JSON"}, status=400)

    text = (body.get("text") or "").strip()
    if not text:
        return json_response({"error": "缺少 text 字段"}, status=400)

    session_id = body.get("session_id") or uuid.uuid4().hex
    result = await _run_http_chat(session_id, text)
    return json_response(result)


async def http_config(request: web.Request):
    """POST /config — 配置同步（扩展设置页 / 外部脚本）"""
    try:
        body = await request.json()
    except Exception:
        return json_response({"error": "请求体必须是 JSON"}, status=400)

    config.update_runtime(body, persist=True)
    logger.info("[HTTP] 收到配置同步: %s", list(body.keys()))
    return json_response({"ok": True, "has_api_key": config.has_api_key(), "model": config.get("model")})


async def http_screenshot(request: web.Request):
    """GET /screenshot — 截取当前视口并保存到本地"""
    save_dir = request.query.get("dir", "screenshots")

    result = await send_to_extension("takeScreenshot", {})
    if "error" in result:
        return json_response(result, status=500)

    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    title = result.get("tabTitle", "screenshot")
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)[:50]
    filepath = out_dir / f"{safe_title}.png"

    filepath.write_bytes(base64.b64decode(result["data"]))

    return json_response({
        "saved": str(filepath.resolve()),
        "size_kb": round(filepath.stat().st_size / 1024, 1),
        "tabUrl": result.get("tabUrl"),
        "tabTitle": result.get("tabTitle"),
    })


# ---- 启动 ----

async def main():
    ws_port = int(config.get("ws_port"))
    http_port = int(config.get("http_port"))

    # WebSocket 服务
    ws_server = await websockets.serve(ws_handler, WS_HOST, ws_port)
    logger.info("[服务] WebSocket 监听 ws://%s:%s", WS_HOST, ws_port)

    # HTTP 服务
    app = web.Application()
    app.router.add_post("/command", http_command)
    app.router.add_get("/status", http_status)
    app.router.add_post("/chat", http_chat)
    app.router.add_post("/config", http_config)
    app.router.add_get("/screenshot", http_screenshot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", http_port)
    await site.start()
    logger.info("[服务] HTTP 接口监听 http://127.0.0.1:%s", http_port)
    print()
    print("浏览器 AI 助手服务已启动")
    print(f"  WebSocket: ws://{WS_HOST}:{ws_port}    (扩展连接)")
    print(f"  HTTP:      http://127.0.0.1:{http_port}")
    print(f"  模型:      {config.get('model')}   API Key: {'已配置' if config.has_api_key() else '未配置（在扩展设置页填写）'}")
    print()
    print("接口说明:")
    print(f"  GET  http://127.0.0.1:{http_port}/status        — 查看状态")
    print(f"  POST http://127.0.0.1:{http_port}/command       — 发送任意指令给扩展")
    print(f"  POST http://127.0.0.1:{http_port}/chat          — 发起对话（可脱离扩展测试）")
    print(f"  POST http://127.0.0.1:{http_port}/config        — 同步配置（API Key、模型）")
    print(f"  GET  http://127.0.0.1:{http_port}/screenshot    — 截取当前视口")
    print()

    # 保持运行
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
