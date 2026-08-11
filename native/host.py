"""
Native Messaging Host — 浏览器 AI 助手服务拉起器

由 Chrome 通过 chrome.runtime.connectNative("com.browser.assistant") 自动启动。
职责：探活本地服务端口，未监听时用 venv Python 拉起服务进程。

Chrome Native Messaging 协议：
  - 消息以 4 字节小端序长度前缀 + UTF-8 JSON 传输（stdin/stdout）
"""

import json
import socket
import struct
import subprocess
import sys
from pathlib import Path

# 项目根：native/host.py 的上上级
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Windows 无窗口启动标志
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

LOG_FILE = PROJECT_ROOT / "logs" / "native-host.log"


def _log(msg: str):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except OSError:
        pass


def _read_message() -> dict | None:
    """读一条 Chrome 消息；EOF 返回 None"""
    raw_len = sys.stdin.buffer.read(4)
    if not raw_len:
        return None
    (length,) = struct.unpack("<I", raw_len)
    payload = sys.stdin.buffer.read(length)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _write_message(msg: dict):
    """写一条 Chrome 消息"""
    payload = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _port_open(port: int) -> bool:
    """探活 127.0.0.1:port"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _pythonw() -> Path:
    """优先使用 venv 的 pythonw（无控制台窗口）"""
    venv_pythonw = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv_pythonw.is_file():
        return venv_pythonw
    # 兜底：用当前解释器（host 本身由 manifest 中的解释器启动）
    return Path(sys.executable)


def _ensure_service(port: int) -> dict:
    """确保本地服务在运行；未监听则拉起"""
    if _port_open(port):
        return {"ok": True, "started": False}

    server = PROJECT_ROOT / "service" / "zy" / "server.py"
    if not server.is_file():
        return {"ok": False, "error": f"服务入口不存在: {server}"}

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "server.log", "a", encoding="utf-8")

    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS

    try:
        proc = subprocess.Popen(
            [str(_pythonw()), str(server)],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
        _log(f"已启动服务: pid={proc.pid} pythonw={_pythonw()}")
        return {"ok": True, "started": True, "pid": proc.pid}
    except Exception as e:
        _log(f"启动服务失败: {e}")
        return {"ok": False, "error": str(e)}


def main():
    _log("Native host 启动")
    while True:
        msg = _read_message()
        if msg is None:
            _log("stdin 关闭，退出")
            break

        msg_type = msg.get("type")
        if msg_type == "ensure_service":
            port = int(msg.get("http_port") or 18768)
            _log(f"ensure_service port={port}")
            _write_message(_ensure_service(port))
        elif msg_type == "ping":
            _write_message({"ok": True, "pong": True})
        else:
            _log(f"未知消息类型: {msg_type}")
            _write_message({"ok": False, "error": f"unknown type: {msg_type}"})


if __name__ == "__main__":
    main()
