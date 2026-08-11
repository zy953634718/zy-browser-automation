"""
输入文本动作 — 在输入框中输入文本
"""


async def input_text(send_to_extension, text: str, selector: str = None, placeholder: str = None, clear: bool = True) -> dict:
    """
    在输入框中输入文本。支持 React/Vue 受控输入框。

    Args:
        send_to_extension: 发送指令给扩展的函数
        text: 要输入的文本
        selector: CSS 选择器（如 ".zyInput", "#search"）
        placeholder: 通过 placeholder 属性查找输入框（如 "搜索行业和品类"）
        clear: 输入前是否清空已有内容（默认 True）

    Returns:
        操作结果

    用法示例:
        # 通过 placeholder 查找（推荐，最直观）
        await input_text(send, "TeenieWeenie", placeholder="搜索行业和品类")

        # 通过 CSS 选择器
        await input_text(send, "TeenieWeenie", selector=".zyInput")

        # 不清空已有内容，追加输入
        await input_text(send, "TeenieWeenie", selector=".zyInput", clear=False)

        # HTTP 调用
        # curl -X POST http://127.0.0.1:18768/actions/input-text \
        #   -H 'Content-Type: application/json' \
        #   -d '{"text":"TeenieWeenie","placeholder":"搜索行业和品类"}'
    """
    if not selector and not placeholder:
        return {"error": "必须提供 selector 或 placeholder 其中之一"}

    js_input = """
    var selector = arguments[0];
    var placeholder = arguments[1];
    var text = arguments[2];
    var doClear = arguments[3];

    var input = null;
    if (selector) {
        input = document.querySelector(selector);
    } else if (placeholder) {
        var inputs = document.querySelectorAll('input');
        for (var i = 0; i < inputs.length; i++) {
            if (inputs[i].placeholder === placeholder) {
                input = inputs[i];
                break;
            }
        }
    }

    if (!input) return {ok: false, error: '未找到输入框'};

    input.scrollIntoView({block: 'center', behavior: 'instant'});
    input.focus();
    input.click();

    if (doClear) {
        var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(input, '');
        input.dispatchEvent(new Event('input', {bubbles: true}));
    }

    var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeSetter.call(input, text);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));

    return {ok: true, value: input.value, placeholder: input.placeholder || null};
    """

    result = await send_to_extension("executeScript", {
        "code": js_input,
        "args": [selector or "", placeholder or "", text, clear],
    })

    # executeOnPage 返回 {result: <JS返回值>}，需要解包
    if isinstance(result, dict) and "result" in result:
        result = result["result"]

    if isinstance(result, dict) and result.get("ok"):
        return {"ok": True, "text": text, "value": result.get("value")}
    elif isinstance(result, dict) and result.get("error"):
        return {"error": "输入文本失败", "detail": result.get("error")}
    else:
        return result
