"""Build a clean Windows/macOS end-user release directory.

This is deliberately a whitelist packager.  It never copies the workspace
recursively, so logs, tests, generated Skills, API keys, memory and outputs
cannot accidentally enter a release archive.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "browser-ai-assistant"

ROOT_FILES = ["install.bat", "install.command", "README.md", "使用说明.html"]
DIRECTORIES = {
    "browser-extension": None,
    "docs/images": None,
    "native": {"host.py", "host-manifest.template.json"},
    "service": {"config.json", "requirements.txt", "zy"},
    "scripts": {"install.py", "install.bat", "run_service.py"},
}
FORBIDDEN_NAMES = {
    ".venv", "logs", "outputs", "tests", "test", "agents", "dist", "__pycache__",
    "config.local.json", "agent_memory.json", ".extension-id",
}
RUNTIME_EXCLUDE_DIRS = {
    "Doc", "docs", "Scripts", "include", "libs", "tcl", "Tools", "idlelib",
    "ensurepip", "venv", "tkinter", "test", "tests", "__pycache__", "share",
    "pip", "setuptools", "wheel",
}
RUNTIME_EXCLUDE_FILES = {"NEWS.txt"}


def _copy_tree(source: Path, target: Path) -> None:
    """Copy source recursively while excluding generated/cache/private files."""
    for item in source.iterdir():
        if item.name in FORBIDDEN_NAMES:
            continue
        destination = target / item.name
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            _copy_tree(item, destination)
        elif item.is_file():
            shutil.copy2(item, destination)


def _copy_selected(relative: str, selection) -> None:
    source = ROOT / relative
    target = CURRENT_OUTPUT / relative
    if source.is_dir() and selection is None:
        target.mkdir(parents=True, exist_ok=True)
        _copy_tree(source, target)
        return
    if source.is_dir() and selection:
        target.mkdir(parents=True, exist_ok=True)
        for name in selection:
            item = source / name
            if item.is_dir():
                destination = target / name
                destination.mkdir(parents=True, exist_ok=True)
                _copy_tree(item, destination)
            elif item.is_file():
                shutil.copy2(item, target / name)
        return
    raise SystemExit(f"发布所需文件不存在: {source}")


def _validate_release(output: Path) -> None:
    required = [
        output / "install.bat",
        output / "browser-extension" / "manifest.json",
        output / "native" / "host.py",
        output / "native" / "host-manifest.template.json",
        output / "service" / "zy" / "server.py",
        output / "scripts" / "install.py",
    ]
    missing = [str(path.relative_to(output)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"发布包缺少必要文件: {', '.join(missing)}")
    leaked = []
    for path in output.rglob("*"):
        if path.name in FORBIDDEN_NAMES:
            leaked.append(str(path.relative_to(output)))
    if leaked:
        raise SystemExit(f"检测到不应打包的私有/临时文件: {', '.join(leaked)}")


def _copy_runtime(output: Path) -> None:
    venv = ROOT / ".venv"
    if sys.platform == "darwin":
        venv_python = venv / "bin" / "python"
        lib_dir = venv / "lib"
        site_packages = next(lib_dir.glob("python*/site-packages"), None) if lib_dir.is_dir() else None
        base_python = Path(sys.base_prefix)
        base_executable = base_python / "bin" / "python3"
    else:
        venv_python = venv / "Scripts" / "python.exe"
        site_packages = venv / "Lib" / "site-packages"
        base_python = Path(sys.base_prefix)
        base_executable = base_python / "python.exe"
    if not venv_python.is_file():
        raise SystemExit("当前项目没有可用 .venv，请先运行 python scripts/install.py 安装依赖。")
    if not base_executable.is_file():
        raise SystemExit(f"找不到基础 Python 运行时: {base_python}")

    runtime = output / "runtime"
    base_lib = (base_python / "Lib").resolve()

    def ignore_runtime(path: str, names: list[str]):
        ignored = {name for name in names if name in FORBIDDEN_NAMES or name in RUNTIME_EXCLUDE_DIRS or name in RUNTIME_EXCLUDE_FILES or name.endswith(".pyc")}
        # The base interpreter may have unrelated developer-wide packages.
        # Only the project's venv packages are overlaid below.
        if Path(path).resolve() == base_lib:
            ignored.add("site-packages")
        return ignored

    shutil.copytree(base_python, runtime, ignore=ignore_runtime)
    if site_packages and site_packages.is_dir():
        if sys.platform == "darwin":
            lib = runtime / "lib"
            target_packages = next(lib.glob("python*/site-packages"), lib / "site-packages")
        else:
            target_packages = runtime / "Lib" / "site-packages"
        shutil.copytree(site_packages, target_packages, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*FORBIDDEN_NAMES, *RUNTIME_EXCLUDE_DIRS, "*.pyc", "pip-*.dist-info", "setuptools-*.dist-info", "wheel-*.dist-info"))


def main() -> None:
    global CURRENT_OUTPUT
    parser = argparse.ArgumentParser(description="构建仅包含必要文件的免环境安装包")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    CURRENT_OUTPUT = args.output.resolve()
    if CURRENT_OUTPUT.exists():
        shutil.rmtree(CURRENT_OUTPUT)
    CURRENT_OUTPUT.mkdir(parents=True)

    for relative in ROOT_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise SystemExit(f"发布所需文件不存在: {source}")
        shutil.copy2(source, CURRENT_OUTPUT / relative)
    for relative, selection in DIRECTORIES.items():
        _copy_selected(relative, selection)
    _copy_runtime(CURRENT_OUTPUT)
    if sys.platform == "darwin" and (CURRENT_OUTPUT / "install.command").is_file():
        (CURRENT_OUTPUT / "install.command").chmod(0o755)
    _validate_release(CURRENT_OUTPUT)

    print(f"发布包已生成: {CURRENT_OUTPUT}")
    print("已排除 API Key、长期记忆、outputs、日志、测试、开发脚本和缓存文件。")
    print("将整个目录压缩后分发，用户双击 install.bat（macOS 使用 install.command）即可安装。")


if __name__ == "__main__":
    main()
