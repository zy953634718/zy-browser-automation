"""
会话管理 + DeepSeek function calling 对话循环

会话存储于内存：sessions[session_id] = {"messages": [...], "busy": bool, "last_active": float}
会话上限 20 个（按最后活动淘汰），历史上限 40 条（丢最旧）。
"""

import asyncio
import json
import time

from . import config, deepseek_client, memory, skills, tools
from .log import logger

# ---- 会话存储 ----

SESSIONS_MAX = 20
HISTORY_MAX = 40

_sessions: dict[str, dict] = {}

SYSTEM_PROMPT = (
    "你是浏览器 AI Agent，通过工具操作用户的浏览器，也可以调用本地 Skill、保存文件和使用长期记忆。"
    "面对包含多个操作步骤、跨页面或需要生成交付物的复杂任务，先调用 set_task_plan 创建简短计划，"
    "并在每一步开始和结束时调用 update_task_plan 更新状态；简单问答不要创建计划。"
    "工具作用于当前活动标签页；工具返回 JSON，请直接引用其中的事实数据作答，不要编造。"
    "需要了解页面时先调用 get_page_info / get_page_content。"
    "执行页面操作（点击、输入、滚动）后，如需要可再次调用 get_page_content 确认效果。"
    "如果页面内容需要分批读取，请根据已有结果推进，不要重复相同的工具调用；信息足够后直接总结。"
    "用户明确说‘记住’时调用 remember；用户要求导出、下载或保存时调用 save_file。"
    "用户要求总结经验、生成 Skill 或保存工作流时调用 create_skill。后续任务若匹配某个 Skill，先调用 read_skill 读取它再执行。"
    "回答用中文、简洁。"
)


def _system_prompt() -> str:
    return (
        SYSTEM_PROMPT
        + "\n\n本机长期记忆（仅供本次决策参考）：\n" + memory.context()
        + "\n\n当前可用本地 Skill：\n" + skills.skill_context()
    )


def _get_or_create_session(session_id: str) -> dict:
    session = _sessions.get(session_id)
    if not session:
        # 超过上限时淘汰最久未活动的会话
        if len(_sessions) >= SESSIONS_MAX:
            oldest_id = min(_sessions, key=lambda sid: _sessions[sid]["last_active"])
            del _sessions[oldest_id]
        session = {
            "messages": [{"role": "system", "content": _system_prompt()}],
            "busy": False,
            "last_active": time.time(),
            "plan": None,
        }
        _sessions[session_id] = session
    session.setdefault("plan", None)
    session["last_active"] = time.time()
    return session


def restore_session(session_id: str, history: list[dict] | None) -> None:
    """Restore the user-visible part of a conversation after service restart."""
    if not history:
        return
    session = _get_or_create_session(session_id)
    if session["busy"] or len(session["messages"]) > 1:
        return
    restored = []
    for message in history[-(HISTORY_MAX - 1):]:
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and content:
            restored.append({"role": role, "content": str(content)})
    session["messages"].extend(restored)
    _repair_and_trim_history(session)


def _repair_and_trim_history(session: dict):
    """Repair orphan tool messages and trim history only at turn boundaries."""
    messages = session.get("messages") or []
    if not messages:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    system = messages[0] if messages[0].get("role") == "system" else {"role": "system", "content": _system_prompt()}
    system["content"] = _system_prompt()
    rest = messages[1:] if messages[0].get("role") == "system" else messages

    # Keep tool-call groups atomic. A tool message is valid only immediately
    # after the assistant tool_calls message that declared its id.
    repaired = []
    index = 0
    while index < len(rest):
        msg = rest[index]
        if msg.get("role") == "tool":
            index += 1  # orphan left by an older buggy version
            continue
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            expected = [tc.get("id") for tc in msg["tool_calls"] if tc.get("id")]
            group = [msg]
            found = []
            cursor = index + 1
            while cursor < len(rest) and rest[cursor].get("role") == "tool":
                tool_msg = rest[cursor]
                if tool_msg.get("tool_call_id") in expected:
                    group.append(tool_msg)
                    found.append(tool_msg.get("tool_call_id"))
                cursor += 1
            if expected and all(call_id in found for call_id in expected):
                repaired.extend(group)
            index = cursor
            continue
        repaired.append(msg)
        index += 1

    # Remove oldest complete turns until the configured limit is met. Start a
    # retained history at a user message so it never begins with a tool group.
    while len(repaired) > HISTORY_MAX - 1:
        next_user = next(
            (i for i in range(1, len(repaired)) if repaired[i].get("role") == "user"),
            None,
        )
        if next_user is None:
            repaired = repaired[-(HISTORY_MAX - 1):]
            while repaired and repaired[0].get("role") in {"tool", "assistant"}:
                repaired.pop(0)
            break
        repaired = repaired[next_user:]
    session["messages"] = [system, *repaired]


def _append_message(session: dict, msg: dict, *, trim: bool = True):
    session["messages"].append(msg)
    if trim:
        _repair_and_trim_history(session)


PLAN_STEP_STATUSES = {"pending", "running", "completed", "failed", "skipped"}


def _set_task_plan(session: dict, args: dict) -> dict:
    """Validate and store a user-visible execution plan for the current task."""
    goal = str(args.get("goal") or "").strip()[:240]
    raw_steps = args.get("steps")
    if not goal or not isinstance(raw_steps, list) or not raw_steps:
        return {"error": "goal 和 steps 不能为空"}

    steps = []
    used_ids = set()
    for index, raw in enumerate(raw_steps[:12], 1):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()[:160]
        if not title:
            continue
        base_id = str(raw.get("id") or f"step-{index}").strip()[:64] or f"step-{index}"
        step_id = base_id
        suffix = 2
        while step_id in used_ids:
            step_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(step_id)
        steps.append({"id": step_id, "title": title, "status": "pending", "detail": ""})

    if not steps:
        return {"error": "计划至少需要一个有效步骤"}

    now = time.time()
    session["plan"] = {
        "goal": goal,
        "status": "running",
        "steps": steps,
        "created_at": now,
        "updated_at": now,
    }
    return {"ok": True, "plan": session["plan"]}


def _update_task_plan(session: dict, args: dict) -> dict:
    """Update one plan step and derive the overall task state."""
    plan = session.get("plan")
    if not plan:
        return {"error": "当前任务还没有计划，请先调用 set_task_plan"}
    step_id = str(args.get("step_id") or "").strip()
    status = str(args.get("status") or "").strip()
    if status not in PLAN_STEP_STATUSES:
        return {"error": f"无效状态: {status}"}

    step = next((item for item in plan["steps"] if item["id"] == step_id), None)
    if step is None:
        return {"error": f"未找到计划步骤: {step_id}"}
    step["status"] = status
    step["detail"] = str(args.get("detail") or "").strip()[:300]
    statuses = {item["status"] for item in plan["steps"]}
    if "failed" in statuses:
        plan["status"] = "failed"
    elif statuses.issubset({"completed", "skipped"}):
        plan["status"] = "completed"
    else:
        plan["status"] = "running"
    plan["updated_at"] = time.time()
    return {"ok": True, "plan": plan}


def _finish_task_plan(session: dict, status: str = "finished") -> dict | None:
    """Close a still-running plan without pretending unfinished steps succeeded."""
    plan = session.get("plan")
    if plan and plan.get("status") == "running":
        plan["status"] = status
        plan["updated_at"] = time.time()
    return plan


async def handle_chat(send_message, send_to_extension, session_id: str, text: str):
    """
    处理一条对话消息（异步任务，不阻塞 WS 消息循环）。

    Args:
        send_message: async (type, **payload) -> None，向扩展推送消息
        send_to_extension: 发送指令给扩展的函数（server.py 注入）
        session_id: 会话 id（popup 生成）
        text: 用户消息
    """
    session = _get_or_create_session(session_id)

    if session["busy"]:
        await send_message("chat_reply", session_id=session_id,
                           text="正在处理上一条消息，请稍候……", error=False)
        return
    session["busy"] = True

    try:
        # Heal sessions created by versions that stored tool/assistant messages
        # in the wrong order, so upgrading doesn't require clearing storage.
        _repair_and_trim_history(session)
        # Each user turn starts a fresh visible plan. The conversation history
        # remains available to the model for follow-up questions.
        if session.get("plan") is not None:
            session["plan"] = None
            await send_message("task_plan", session_id=session_id, plan=None)
        _append_message(session, {"role": "user", "content": text})
        await send_message("tool_event", session_id=session_id, status="thinking",
                           tool="", args={}, result=None)

        max_rounds = max(1, min(40, int(config.get("max_tool_rounds", 16))))
        repeated_calls: dict[str, int] = {}
        for _round in range(max_rounds):
            session["messages"][0]["content"] = _system_prompt()
            resp = await deepseek_client.chat_once(session["messages"], tools.TOOLS)

            # 无工具调用 → 最终回答
            if not resp.get("tool_calls"):
                reply = resp.get("content") or "（模型未返回内容）"
                _append_message(session, {"role": "assistant", "content": reply})
                memory.record_turn(session_id, text, reply)
                if _finish_task_plan(session):
                    await send_message("task_plan", session_id=session_id, plan=session["plan"])
                await send_message("chat_reply", session_id=session_id, text=reply, error=False)
                return

            # DeepSeek/OpenAI protocol requires the assistant tool_calls
            # message first, followed by one tool response for each call.
            assistant_tool_calls = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                    },
                }
                for tc in resp["tool_calls"]
            ]
            _append_message(session, {
                "role": "assistant",
                "content": resp.get("content"),
                "tool_calls": assistant_tool_calls,
            }, trim=False)

            # 逐个执行工具调用，并按声明顺序追加 tool 结果。
            for tc in resp["tool_calls"]:
                name, args = tc["name"], tc.get("arguments") or {}
                signature = json.dumps({"name": name, "arguments": args}, ensure_ascii=False, sort_keys=True)
                repeated_calls[signature] = repeated_calls.get(signature, 0) + 1
                logger.info("[agent] 工具调用 %s(%s)", name, json.dumps(args, ensure_ascii=False))
                await send_message("tool_event", session_id=session_id, status="started",
                                   tool=name, args=args, result=None)

                if repeated_calls[signature] > 2:
                    result = {"error": "相同工具调用已重复多次，请基于已有结果继续并给出回答。"}
                elif name == "set_task_plan":
                    result = _set_task_plan(session, args)
                elif name == "update_task_plan":
                    result = _update_task_plan(session, args)
                else:
                    result = await tools.execute_tool(name, args, send_to_extension)

                if name in {"set_task_plan", "update_task_plan"}:
                    await send_message(
                        "task_plan", session_id=session_id, plan=session.get("plan"),
                    )

                await send_message("tool_event", session_id=session_id, status="done",
                                   tool=name, args=args, result=result)

                # 工具结果入历史（截断）
                result_text = tools.result_to_text(result, name)
                _append_message(session, {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": name,
                    "content": result_text,
                }, trim=False)
            _repair_and_trim_history(session)

        # 工具预算耗尽时再请求一次不带 tools 的回答，强制模型基于已经
        # 收集到的数据收敛，而不是直接把“轮次过多”暴露给用户。
        try:
            final_resp = await deepseek_client.chat_once(session["messages"], [])
            final_reply = final_resp.get("content") or f"已完成 {max_rounds} 轮浏览器操作，但模型没有返回总结。"
            _append_message(session, {"role": "assistant", "content": final_reply})
            memory.record_turn(session_id, text, final_reply)
            if _finish_task_plan(session):
                await send_message("task_plan", session_id=session_id, plan=session["plan"])
            await send_message("chat_reply", session_id=session_id, text=final_reply, error=False)
        except deepseek_client.DeepSeekError:
            limit_message = f"已执行 {max_rounds} 轮浏览器操作。请缩小任务范围，或在 service/config.json 增大 max_tool_rounds。"
            _append_message(session, {"role": "assistant", "content": limit_message})
            if _finish_task_plan(session, "failed"):
                await send_message("task_plan", session_id=session_id, plan=session["plan"])
            await send_message("chat_reply", session_id=session_id, text=limit_message, error=True)
    except asyncio.CancelledError:
        if session.get("plan"):
            session["plan"]["status"] = "cancelled"
            session["plan"]["updated_at"] = time.time()
            await send_message("task_plan", session_id=session_id, plan=session["plan"])
        logger.info("[agent] 任务已取消: %s", session_id)
        raise
    except deepseek_client.DeepSeekError as e:
        if _finish_task_plan(session, "failed"):
            await send_message("task_plan", session_id=session_id, plan=session["plan"])
        await send_message("chat_reply", session_id=session_id, text=str(e), error=True)
    except Exception as e:
        logger.exception("[agent] 对话处理异常")
        if _finish_task_plan(session, "failed"):
            await send_message("task_plan", session_id=session_id, plan=session["plan"])
        await send_message("chat_reply", session_id=session_id,
                           text=f"内部错误: {e}", error=True)
    finally:
        session["busy"] = False


def session_count() -> int:
    return len(_sessions)
