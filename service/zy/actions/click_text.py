"""
点击文本动作 — 在页面中查找包含指定文本的元素并点击
"""

import asyncio


async def click_text(send_to_extension, text: str, parent_selector: str = None, exact: bool = False, tag_name: str = None) -> dict:
    """
    在页面中查找包含指定文本的元素并点击。

    适用于：<div class="text-overflow">TeenieWeenie官方旗舰店</div>
    调用 click_text(send, "TeenieWeenie官方旗舰店") 即可点击。

    Args:
        send_to_extension: 发送指令给扩展的函数
        text: 要匹配的文本内容
        parent_selector: 可选，限定在某个父元素内查找（CSS 选择器）
        exact: 是否精确匹配文本（默认 False，即包含匹配）
        tag_name: 可选，限定目标元素的标签名（如 "div", "span"）

    Returns:
        操作结果

    用法示例:
        # 点击包含文本的 div（精确匹配，推荐）
        await click_text(send, "TeenieWeenie官方旗舰店", tag_name="div", exact=True)

        # 点击链接
        await click_text(send, "全部", tag_name="a", exact=True)

        # 限定在某个父元素内查找（避免页面其他位置有同名文本）
        await click_text(send, "TeenieWeenie官方旗舰店", parent_selector=".zyCustomDisplay", tag_name="div")

        # HTTP 调用
        # curl -X POST http://127.0.0.1:18768/actions/click-text \
        #   -H 'Content-Type: application/json' \
        #   -d '{"text":"TeenieWeenie官方旗舰店","tag_name":"div","exact":true}'
    """
    params = {
        "textContains" if not exact else "text": text,
    }
    if tag_name:
        params["tagName"] = tag_name

    # 如果指定了父选择器，通过 executeScript 在限定范围内查找
    if parent_selector:
        js_click_in_parent = """
        var parent = document.querySelector(arguments[0]);
        if (!parent) return {ok: false, error: '未找到父元素', selector: arguments[0]};

        var searchText = arguments[1];
        var exactMatch = arguments[2];
        var tagFilter = arguments[3];
        var allEls = parent.querySelectorAll(tagFilter || '*');

        // 收集所有匹配的元素，优先选择 textContent 最短（最精确）的
        var bestEl = null;
        var bestLen = Infinity;

        for (var i = 0; i < allEls.length; i++) {
            var el = allEls[i];
            var text = el.textContent.trim();
            var matched = exactMatch ? (text === searchText) : (text.indexOf(searchText) !== -1);
            if (matched && text.length < bestLen) {
                bestEl = el;
                bestLen = text.length;
            }
        }

        if (!bestEl) return {ok: false, error: '未找到匹配文本的元素', text: searchText};

        bestEl.scrollIntoView({block: 'center', behavior: 'instant'});

        var clickTarget = bestEl;
        if (bestEl.tagName !== 'A' && bestEl.tagName !== 'BUTTON' && bestEl.tagName !== 'INPUT') {
            var ancestor = bestEl.closest('a, button, [role=button], [onclick]');
            if (ancestor) clickTarget = ancestor;
        }

        clickTarget.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true}));
        clickTarget.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true}));
        clickTarget.click();

        return {ok: true, tagName: clickTarget.tagName, text: clickTarget.textContent.trim().substring(0, 100), href: clickTarget.href || null};
        """
        result = await send_to_extension("executeScript", {
            "code": js_click_in_parent,
            "args": [parent_selector, text, exact, tag_name or ""],
        })
        # executeOnPage 返回 {result: <JS返回值>}，需要解包
        inner = result.get("result") if isinstance(result, dict) else result
        return inner if isinstance(inner, dict) else result

    # 无父选择器，直接使用 clickElement 指令
    result = await send_to_extension("clickElement", params)

    if isinstance(result, dict) and result.get("ok"):
        return {"ok": True, "text": text, "clicked": result.get("text", ""), "tagName": result.get("tagName")}
    elif isinstance(result, dict) and result.get("error"):
        return {"error": f"未找到包含文本: {text}", "detail": result.get("error")}
    else:
        return result
