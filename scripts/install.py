"""Browser AI Assistant - one-click installer.

The release archive contains a private Python runtime in ``runtime/``.  When
running from a source checkout we also accept an existing ``.venv`` or a
system Python and create the venv as a convenience.  This keeps the normal
user path free from Python/pip setup while retaining a useful developer path.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = PROJECT_ROOT / ".venv"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
REQUIREMENTS = PROJECT_ROOT / "service" / "requirements.txt"
SERVER = PROJECT_ROOT / "service" / "zy" / "server.py"
MANIFEST_DIR = PROJECT_ROOT / "native"
TEMPLATE = MANIFEST_DIR / "host-manifest.template.json"
MANIFEST = MANIFEST_DIR / "com.browser.assistant.json"
HOST_NAME = "com.browser.assistant"
HTTP_PORT = 18768
DEFAULT_EXTENSION_ID = "onegmgllhomnialihompnffflgabapnf"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def step(message: str) -> None:
    print(f"[install] {message}")


def _is_python(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        result = subprocess.run(
            [str(path), "-c", "import sys; print(sys.version_info >= (3, 10))"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "True"
    except (OSError, subprocess.SubprocessError):
        return False


def _runtime_python() -> Path | None:
    """Find a usable interpreter without asking the user to configure PATH."""
    if sys.platform == "darwin":
        candidates = [RUNTIME_DIR / "bin" / "python3", VENV_DIR / "bin" / "python"]
    else:
        candidates = [RUNTIME_DIR / "python.exe", VENV_DIR / "Scripts" / "python.exe"]
    for candidate in candidates:
        if _is_python(candidate):
            return candidate

    # Developer fallback.  A release user never reaches this branch because
    # the archive ships runtime/python.exe.
    for command in ("py", "python"):
        found = shutil.which(command)
        if found and _is_python(Path(found)):
            return Path(found)
    if _is_python(Path(sys.executable)):
        return Path(sys.executable)
    return None


def ensure_runtime() -> Path:
    python = _runtime_python()
    if python is None:
        raise SystemExit(
            "未找到可用的 Python 运行时。请使用官方发布压缩包（其中已内置 runtime\\python.exe），"
            "或安装 Python 3.10+ 后重新双击 install.bat。"
        )

    # Do not create a venv when a packaged runtime or an existing venv is
    # available.  Source checkouts using system Python still get isolation.
    packaged = RUNTIME_DIR in python.parents
    in_venv = VENV_DIR in python.parents
    if packaged or in_venv:
        return python
    if python.resolve() == Path(sys.executable).resolve() and not VENV_DIR.exists():
        step("创建本地运行环境 .venv ...")
        subprocess.run([str(python), "-m", "venv", str(VENV_DIR)], check=True)
        venv_python = (
            VENV_DIR / "bin" / "python" if sys.platform == "darwin"
            else VENV_DIR / "Scripts" / "python.exe"
        )
        if _is_python(venv_python):
            return venv_python
    return python


# Backwards-compatible name used by older automation scripts.
def ensure_venv() -> Path:
    return ensure_runtime()


def _imports_ok(python: Path) -> bool:
    result = subprocess.run(
        [str(python), "-c", "import aiohttp, websockets"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.returncode == 0


def install_deps(python: Path, offline: bool = False) -> None:
    if _imports_ok(python):
        step("服务依赖已就绪（跳过 pip）")
        return
    if not REQUIREMENTS.is_file():
        raise SystemExit(f"找不到依赖清单: {REQUIREMENTS}")
    step("安装服务依赖 ...")
    command = [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)]
    if offline:
        command.insert(4, "--no-index")
    result = subprocess.run(command, check=False)
    if result.returncode or not _imports_ok(python):
        mode = "离线包中未包含依赖" if offline else "请检查网络连接后重试"
        raise SystemExit(f"依赖安装失败（{mode}）。")


def _extension_id(value: str | None) -> str | None:
    value = (value or os.environ.get("BROWSER_ASSISTANT_EXTENSION_ID") or "").strip()
    if not value:
        marker = PROJECT_ROOT / "browser-extension" / ".extension-id"
        if marker.is_file():
            value = marker.read_text(encoding="utf-8").strip()
    if not value:
        value = DEFAULT_EXTENSION_ID
    if len(value) == 32 and all(c in "abcdefghijklmnop" for c in value):
        return value
    return None


def write_manifest(extension_id: str | None = None, python: Path | None = None) -> Path:
    """Generate a manifest with absolute paths and optional extension ACL."""
    python = python or ensure_runtime()
    pythonw = python.parent / "pythonw.exe" if python.name.lower() == "python.exe" else python
    if not pythonw.is_file():
        pythonw = python
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    host = (MANIFEST_DIR / "host.py").resolve()
    if sys.platform == "darwin":
        launcher = MANIFEST_DIR / HOST_NAME
        launcher.write_text(
            "#!/bin/sh\nexec " + shlex.quote(str(python.resolve())) + " "
            + shlex.quote(str(host)) + "\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        data["path"] = str(launcher.resolve())
        data.pop("args", None)
    else:
        data["path"] = str(pythonw.resolve())
        data["args"] = [str(host)]
    ext_id = _extension_id(extension_id)
    if ext_id:
        data["allowed_origins"] = [f"chrome-extension://{ext_id}/"]
    else:
        data.pop("allowed_origins", None)
        step("扩展 ID 无效：Native Messaging 将无法连接，请检查扩展页面显示的 ID。")
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    step(f"Native Host 清单已生成: {MANIFEST}")
    return MANIFEST


def register_native_host(manifest: Path) -> bool:
    if sys.platform == "darwin":
        import shutil
        registered = False

        browser_dirs = {
            "Google/Chrome": Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts",
            "Microsoft Edge": Path.home() / "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
            "Chromium": Path.home() / "Library/Application Support/Chromium/NativeMessagingHosts",
        }
        for browser, directory in browser_dirs.items():
            try:
                directory.mkdir(parents=True, exist_ok=True)
                shutil.copy2(manifest, directory / f"{HOST_NAME}.json")
                step(f"已注册 {browser} Native Messaging")
                registered = True
            except OSError as exc:
                step(f"注册 {browser} 失败: {exc}")
        return registered
    if sys.platform != "win32":
        step("当前平台未提供自动注册，请按浏览器文档注册 Native Host")
        return False
    try:
        import winreg
    except ImportError:
        step("无法访问 winreg，跳过注册表配置")
        return False
    registered = False
    for browser in ("Google/Chrome", "Microsoft/Edge"):
        key_path = rf"Software\{browser}\NativeMessagingHosts\{HOST_NAME}"
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, str(manifest.resolve()))
            step(f"已注册 {browser} NativeMessagingHosts")
            registered = True
        except OSError as exc:
            step(f"注册 {browser} 失败: {exc}")
    return registered


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def start_service(python: Path | None = None) -> None:
    python = python or ensure_runtime()
    if port_open(HTTP_PORT):
        step(f"服务已运行（http://127.0.0.1:{HTTP_PORT}），跳过启动")
        return
    pythonw = python.parent / "pythonw.exe" if python.name.lower() == "python.exe" else python
    if not pythonw.is_file():
        pythonw = python
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "server.log", "a", encoding="utf-8")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS
    proc = subprocess.Popen(
        [str(pythonw), str(SERVER)], cwd=str(PROJECT_ROOT), stdout=log_file,
        stderr=log_file, stdin=subprocess.DEVNULL, **kwargs,
    )
    step(f"服务已启动（pid={proc.pid}）")


def main() -> None:
    parser = argparse.ArgumentParser(description="浏览器 AI 助手一键安装")
    parser.add_argument("--extension-id", help="扩展 ID，用于 Native Messaging 授权")
    parser.add_argument("--offline", action="store_true", help="仅使用本地依赖包")
    parser.add_argument("--no-start", action="store_true", help="安装后不启动服务")
    args = parser.parse_args()

    step(f"项目目录: {PROJECT_ROOT}")
    python = ensure_runtime()
    install_deps(python, offline=args.offline)
    manifest = write_manifest(args.extension_id, python)
    native_registered = register_native_host(manifest)
    if not args.no_start:
        start_service(python)

    print("\n安装完成。下一步：")
    print("  1. 在 Chrome/Edge 打开 chrome://extensions，开启开发者模式")
    print("  2. 选择‘加载已解压的扩展’，指向 browser-extension 文件夹")
    print("  3. 打开扩展设置，填写 DeepSeek API Key（仅保存在本机）")
    if not native_registered:
        print("  警告：Native Messaging 注册失败，请以管理员权限重跑安装脚本。")
    print("  以后打开扩展会自动启动本地服务，无需手动运行 Python。")


if __name__ == "__main__":
    main()
