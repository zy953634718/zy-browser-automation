"""启动 skill 自带的 Python WebSocket/HTTP 服务。

脚本通过绝对路径定位副本，因此可以从任意工作目录运行，并将额外命令行参数
原样传递给服务进程。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    skill_root = Path(__file__).resolve().parents[1]
    server = skill_root / "service" / "zy" / "server.py"
    if not server.is_file():
        raise SystemExit(f"找不到服务入口: {server}")

    # 将相对路径输出固定在 skill 根目录，避免从不同工作目录启动时产生分散文件。
    completed = subprocess.run(
        [sys.executable, str(server), *sys.argv[1:]],
        cwd=skill_root,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
