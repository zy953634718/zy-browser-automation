"""
DeepSeek 客户端 — OpenAI 兼容 /chat/completions 调用（aiohttp，无新依赖）

支持 function calling：返回 model 决策的工具调用列表。
"""

import asyncio
import json

import aiohttp

from . import config
from .log import logger


class DeepSeekError(Exception):
    """DeepSeek API 调用错误（含面向用户的中文提示）"""


async def chat_once(messages: list, tools: list, timeout: float | None = None) -> dict:
    """
    调用一次 DeepSeek chat/completions。

    Args:
        messages: OpenAI 格式消息列表
        tools: 工具 JSON Schema 列表（可空）

    Returns:
        {"content": str|None, "tool_calls": [{"id", "name", "arguments"(dict)}]}

    Raises:
        DeepSeekError: API Key 缺失/无效、网络错误等（含中文提示）
    """
    api_key = config.get("api_key")
    if not api_key:
        raise DeepSeekError("尚未配置 DeepSeek API Key，请在扩展设置页填写后重试")

    url = config.get("base_url").rstrip("/") + "/chat/completions"
    body = {
        "model": config.get("model"),
        "messages": messages,
        "stream": False,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    timeout = timeout or config.get("api_timeout", 60)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 429/5xx 退避重试 1 次
    last_error = None
    for attempt in range(2):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    text = await resp.text()
                    if resp.status == 200:
                        return _parse_response(json.loads(text))
                    if resp.status == 401:
                        raise DeepSeekError("API Key 无效（401），请在扩展设置页检查")
                    if resp.status == 429:
                        last_error = DeepSeekError(f"请求过于频繁（429），请稍后重试")
                    elif resp.status >= 500:
                        last_error = DeepSeekError(f"DeepSeek 服务异常（{resp.status}）")
                    else:
                        raise DeepSeekError(f"DeepSeek API 错误（{resp.status}）: {text[:300]}")
        except aiohttp.ClientError as e:
            last_error = DeepSeekError(f"无法连接 DeepSeek 服务，请检查网络: {e}")
        if last_error and attempt == 0:
            await asyncio.sleep(2)
            continue
        raise last_error

    raise last_error  # 不可达，兜底


def _parse_response(data: dict) -> dict:
    """解析 chat/completions 响应，规范化 tool_calls"""
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {})

    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": args})

    return {"content": msg.get("content"), "tool_calls": tool_calls}
