#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "浏览器 AI 助手 macOS 安装程序"
echo "如果 macOS 阻止脚本，请在终端运行：bash install.command"
python_candidates=("runtime/bin/python3" ".venv/bin/python" "$(command -v python3 2>/dev/null || true)")
for candidate in "${python_candidates[@]}"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    exec "$candidate" scripts/install.py "$@"
  fi
done
echo "未找到 Python 3。请安装 Python 3.10+，或使用包含 runtime 文件夹的正式发布包。"
exit 1
