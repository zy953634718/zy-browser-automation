"""
关闭标签页动作
"""


async def close_tab(send_to_extension, tab_id: int = None) -> dict:
    """
    关闭浏览器标签页。

    Args:
        send_to_extension: 发送指令给扩展的函数
        tab_id: 可选，指定要关闭的标签页 ID。不传则关闭当前活动标签页。

    Returns:
        操作结果

    用法示例:
        # 关闭当前活动标签页
        await close_tab(send)

        # 关闭指定标签页
        await close_tab(send, tab_id=123)

        # HTTP 调用
        # curl -X POST http://127.0.0.1:18768/actions/close-tab
        # curl -X POST http://127.0.0.1:18768/actions/close-tab -H 'Content-Type: application/json' -d '{"tab_id": 123}'
    """
    params = {}
    if tab_id is not None:
        params["tabId"] = tab_id

    result = await send_to_extension("closeTab", params)

    if isinstance(result, dict) and result.get("ok"):
        return {"ok": True, "closed": result.get("closed"), "url": result.get("url"), "title": result.get("title")}
    elif isinstance(result, dict) and result.get("error"):
        return {"error": "关闭标签页失败", "detail": result.get("error")}
    else:
        return result
