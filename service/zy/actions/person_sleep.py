"""
模拟人工操作的随机等待 — 在操作步骤之间增加随机延时，避免被检测
"""

import asyncio
import random


async def person_sleep(min_sec: float = 2.0, max_sec: float = 4.0):
    """
    随机等待一段时间，模拟人工操作节奏。

    Args:
        min_sec: 最小等待秒数
        max_sec: 最大等待秒数
    """
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)
