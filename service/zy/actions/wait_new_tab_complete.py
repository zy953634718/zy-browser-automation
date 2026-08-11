"""
等待新标签页打开并加载完成 — 在某个操作（如点击链接）后，检测新标签页并等待其加载完成
"""

import asyncio


async def wait_new_tab_complete(send_to_extension, before_tab_ids: set = None, timeout: float = 30.0) -> dict:
    """
    等待新标签页打开并加载完成。

    典型用法：先获取当前 tab 列表，执行点击操作，再调用此函数等待新 tab。

    Args:
        send_to_extension: 发送指令给扩展的函数
        before_tab_ids: 操作前的 tab id 集合（由 get_tab_ids 获取），为 None 时自动获取
        timeout: 等待超时时间（秒）

    Returns:
        {ok: True, tab_id: int} 或 {error: str}

    用法示例:
        # 先记录当前 tab 列表
        before = await get_tab_ids(send)
        # 执行点击（会打开新标签页）
        await click_text(send, "链接文字")
        # 等待新 tab 加载完成
        result = await wait_new_tab_complete(send, before_tab_ids=before)
    """
    if before_tab_ids is None:
        before_tab_ids = await _get_tab_ids(send_to_extension)

    # 等待新标签页出现
    new_tab_id = None
    for _ in range(20):  # 最多等 10 秒
        await asyncio.sleep(0.5)
        after_ids = await _get_tab_ids(send_to_extension)
        new_ids = after_ids - before_tab_ids
        if new_ids:
            new_tab_id = new_ids.pop()
            break

    if new_tab_id is None:
        return {"error": "未检测到新标签页"}

    # 轮询 document.readyState 直到加载完成
    elapsed = 0.0
    while elapsed < timeout:
        result = await send_to_extension("executeScript", {
            "code": "return document.readyState",
            "tabId": new_tab_id,
        })
        inner = result.get("result") if isinstance(result, dict) else result
        state = inner if isinstance(inner, str) else (inner.get("result") if isinstance(inner, dict) else inner)
        if state == "complete":
            return {"ok": True, "tab_id": new_tab_id}
        await asyncio.sleep(0.5)
        elapsed += 0.5

    return {"error": "页面加载超时", "tab_id": new_tab_id}


async def get_tab_ids(send_to_extension) -> set:
    """获取当前所有 tab id 集合"""
    return await _get_tab_ids(send_to_extension)


async def _get_tab_ids(send_to_extension) -> set:
    result = await send_to_extension("getTabs")
    tabs = result.get("result") if isinstance(result, dict) else result
    if isinstance(tabs, list):
        return {t["id"] for t in tabs}
    return set()
