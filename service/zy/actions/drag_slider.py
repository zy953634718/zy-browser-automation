"""
拖拽滑块动作 — 模拟拖拽滑块验证码（如阿里云 WAF 验证码）
"""

import asyncio
import math
import random


def _generate_trajectory(distance: int, steps: int) -> list:
    """
    生成模拟人工拖拽的轨迹点。

    特征：
    - 起步慢（反应时间），中间加速，尾部减速
    - 每步带有随机的 X 偏移（偶尔微回退）和 Y 抖动
    - 步间延迟不均匀（偶尔犹豫/加速）
    """
    points = []
    prev_x_ratio = 0.0

    for i in range(steps):
        t = (i + 1) / steps  # 0..1

        # 基础曲线：sigmoid 型，起步和结束慢
        base = 1 / (1 + math.exp(-10 * (t - 0.5)))
        # 归一化到 0..1
        base_norm = (base - 1 / (1 + math.exp(5))) / (1 / (1 + math.exp(-5)) - 1 / (1 + math.exp(5)))

        # 加入随机扰动：让速度不均匀
        noise = random.gauss(0, 0.02)
        # 偶尔大幅变速（模拟犹豫或突然加速）
        if random.random() < 0.08:
            noise += random.uniform(-0.06, 0.06)

        x_ratio = base_norm + noise
        # 保证单调递增（不回退太多），且不超过 1
        x_ratio = min(max(prev_x_ratio + 0.003, x_ratio), 1.0)
        prev_x_ratio = x_ratio

        # X 方向偶尔微回退（1-2 步）
        backtrack = 0
        if 0.2 < t < 0.85 and random.random() < 0.06:
            backtrack = -random.uniform(1, 4)  # 回退 1-4px

        # Y 方向抖动：小幅随机，偶尔跳一下
        y_jitter = random.gauss(0, 1.0)
        if random.random() < 0.1:
            y_jitter += random.uniform(-3, 3)

        # 步间延迟：基础延迟 + 随机，偶尔犹豫（长暂停）或加速（短暂停）
        base_delay = 15  # ms
        if random.random() < 0.08:
            delay = random.randint(40, 80)  # 犹豫
        elif random.random() < 0.15:
            delay = random.randint(5, 10)   # 加速
        else:
            delay = max(5, int(base_delay + random.gauss(0, 5)))

        points.append({
            "x_ratio": x_ratio,
            "y_jitter": y_jitter,
            "backtrack": backtrack,
            "delay_ms": delay,
        })

    # 最后一步确保到达终点
    if points:
        points[-1]["x_ratio"] = 1.0
        points[-1]["backtrack"] = 0

    return points


async def drag_slider(send_to_extension, slider_selector: str = "#aliyunCaptcha-sliding-slider", track_selector: str = "#aliyunCaptcha-sliding-body", steps: int = 30, delay_ms: int = 20) -> dict:
    """
    拖拽滑块到最右边，用于通过滑块验证码。

    模拟人工操作特征：
    - 起步慢 → 中间快 → 尾部慢的 sigmoid 曲线
    - 每步带有随机速度波动（偶尔犹豫/加速）
    - Y 轴随机抖动
    - 偶尔微小回退

    Args:
        send_to_extension: 发送指令给扩展的函数
        slider_selector: 滑块元素的 CSS 选择器
        track_selector: 滑轨元素的 CSS 选择器（用于计算拖拽距离）
        steps: 拖拽分步数（越多越像人工操作）
        delay_ms: 每步之间的基础延迟（毫秒，实际会随机波动）

    Returns:
        操作结果

    用法示例:
        await drag_slider(send)

        # HTTP 调用
        # curl -X POST http://127.0.0.1:18768/actions/drag-slider \
        #   -H 'Content-Type: application/json' \
        #   -d '{}'
    """
    # 第一步：获取滑块位置信息
    js_get_info = """
    var slider = document.querySelector(arguments[0]);
    if (!slider) return {ok: false, error: '未找到滑块元素', selector: arguments[0]};

    var track = document.querySelector(arguments[1]);
    if (!track) return {ok: false, error: '未找到滑轨元素', selector: arguments[1]};

    var sr = slider.getBoundingClientRect();
    var tr = track.getBoundingClientRect();

    var startX = sr.left + sr.width / 2;
    var startY = sr.top + sr.height / 2;
    var endX = tr.right - sr.width / 2;
    var distance = endX - startX;

    if (distance <= 0) return {ok: false, error: '滑块已在最右端', startX: startX, endX: endX};

    return {ok: true, startX: startX, startY: startY, endX: endX, distance: distance};
    """

    info = await send_to_extension("executeScript", {
        "code": js_get_info,
        "args": [slider_selector, track_selector],
    })

    if isinstance(info, dict) and "result" in info:
        info = info["result"]

    if not isinstance(info, dict) or not info.get("ok"):
        return {"error": "获取滑块信息失败", "detail": info}

    start_x = info["startX"]
    start_y = info["startY"]
    end_x = info["endX"]
    distance = info["distance"]

    # 第二步：按下鼠标
    js_press = """
    var slider = document.querySelector(arguments[0]);
    if (!slider) return {ok: false, error: '未找到滑块'};

    slider.dispatchEvent(new PointerEvent('pointerdown', {
        bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse',
        clientX: arguments[1], clientY: arguments[2], button: 0, buttons: 1
    }));
    slider.dispatchEvent(new MouseEvent('mousedown', {
        bubbles: true, cancelable: true,
        clientX: arguments[1], clientY: arguments[2], button: 0, buttons: 1
    }));

    return {ok: true};
    """

    await send_to_extension("executeScript", {
        "code": js_press,
        "args": [slider_selector, start_x, start_y],
    })

    # 起步前短暂犹豫
    await asyncio.sleep(random.uniform(0.08, 0.2))

    # 第三步：生成轨迹并分步移动
    trajectory = _generate_trajectory(distance, steps)

    js_move = """
    document.dispatchEvent(new PointerEvent('pointermove', {
        bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse',
        clientX: arguments[0], clientY: arguments[1], button: 0, buttons: 1
    }));
    document.dispatchEvent(new MouseEvent('mousemove', {
        bubbles: true, cancelable: true,
        clientX: arguments[0], clientY: arguments[1], button: 0, buttons: 1
    }));
    return {ok: true};
    """

    for i, pt in enumerate(trajectory):
        # 已到终点后跳过剩余移动事件
        if pt["x_ratio"] >= 1.0 and i > 0 and trajectory[i - 1]["x_ratio"] >= 1.0:
            await asyncio.sleep(pt["delay_ms"] / 1000)
            continue

        current_x = start_x + distance * pt["x_ratio"] + pt["backtrack"]
        current_y = start_y + pt["y_jitter"]

        await send_to_extension("executeScript", {
            "code": js_move,
            "args": [current_x, current_y],
        })

        if i < len(trajectory) - 1:
            await asyncio.sleep(pt["delay_ms"] / 1000)

    # 第四步：松开鼠标（最后一步延迟后释放，模拟确认）
    await asyncio.sleep(random.uniform(0.03, 0.08))

    js_release = """
    document.dispatchEvent(new PointerEvent('pointerup', {
        bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse',
        clientX: arguments[0], clientY: arguments[1], button: 0, buttons: 0
    }));
    document.dispatchEvent(new MouseEvent('mouseup', {
        bubbles: true, cancelable: true,
        clientX: arguments[0], clientY: arguments[1], button: 0, buttons: 0
    }));
    return {ok: true};
    """

    await send_to_extension("executeScript", {
        "code": js_release,
        "args": [end_x, start_y],
    })

    return {"ok": True, "distance": distance, "steps": steps}
