"""
日志配置 — stdlib logging 实现（双输出：控制台 + 文件）
"""

import logging
import sys
from pathlib import Path

_LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "zy-bot.log"

logger = logging.getLogger("browser-assistant")
logger.setLevel(logging.DEBUG)
logger.propagate = False

if not logger.handlers:
    # 控制台输出
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S"))
    logger.addHandler(console)

    # 文件输出（utf-8，防止 Windows 控制台 GBK 乱码影响写入）
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
        logger.addHandler(file_handler)
    except OSError as e:
        print(f"[日志] 文件输出初始化失败（仅控制台）: {e}")

__all__ = ["logger"]
