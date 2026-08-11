"""
工具集 — DeepSeek function calling 的工具定义与执行分发

工具作用于浏览器当前活动标签页；wait 为服务端本地延时，不转发扩展。
"""

import asyncio
import json
from pathlib import Path

from . import config
from . import memory, skills
from .actions.click_text import click_text as _click_text
from .actions.input_text import input_text as _input_text

# ---- 工具 JSON Schema 定义（OpenAI format） ----

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_page_info",
            "description": "获取当前活动页面的基本信息（标题、URL、标签页 id）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_content",
            "description": "获取当前页面的内容：正文文本（截断）、链接列表、图片列表。回答页面内容相关问题前先调用它",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_text_len": {"type": "integer", "description": "正文最大字符数", "default": 2000},
                    "include_links": {"type": "boolean", "description": "是否包含链接列表", "default": True},
                    "include_images": {"type": "boolean", "description": "是否包含图片列表", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_element",
            "description": "点击页面元素。优先用 text（精确文本）或 text_contains（包含文本）匹配；复杂场景用 selector。text 匹配时若目标是链接/按钮会自动点击其可点击祖先",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要点击元素的精确文本"},
                    "text_contains": {"type": "string", "description": "要点击元素文本的包含匹配"},
                    "selector": {"type": "string", "description": "CSS 选择器"},
                    "tag_name": {"type": "string", "description": "限定标签名（如 a、button、div）"},
                },
                "oneOf": [
                    {"required": ["text"]},
                    {"required": ["text_contains"]},
                    {"required": ["selector"]},
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "input_text",
            "description": "在输入框输入文本。用 placeholder（推荐，如“搜索”/“请输入关键词”）或 selector 定位输入框，支持 React/Vue 受控输入",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要输入的文本"},
                    "placeholder": {"type": "string", "description": "输入框的 placeholder 文本"},
                    "selector": {"type": "string", "description": "CSS 选择器"},
                    "clear": {"type": "boolean", "description": "输入前是否清空", "default": True},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll_to",
            "description": "滚动当前页面（顶部/底部/相对位移）",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "enum": ["top", "bottom"], "description": "滚动到顶部或底部"},
                    "y": {"type": "integer", "description": "相对当前滚动位置向下移动的像素"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "打开 URL。不指定 tab_id 时新建标签页；指定 tab_id 时复用该标签页跳转",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要打开的完整 URL"},
                    "tab_id": {"type": "integer", "description": "复用的标签页 id"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_tab",
            "description": "关闭标签页。不指定 tab_id 时关闭当前活动标签页",
            "parameters": {
                "type": "object",
                "properties": {"tab_id": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tabs",
            "description": "列出浏览器所有标签页（id、URL、标题、是否活动）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_images",
            "description": "获取当前页面的图片列表（URL、尺寸、来源标签）",
            "parameters": {
                "type": "object",
                "properties": {"min_size": {"type": "integer", "description": "最小边长过滤（像素），0 为不过滤", "default": 0}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "截取当前页面视口截图（返回 base64，可能较大）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_script",
            "description": "在当前页面执行任意 JavaScript 代码，返回结果。用于扩展指令覆盖不到的自定义操作",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "JavaScript 代码，return 的结果作为返回值"},
                    "args": {"type": "array", "description": "代码可用的额外参数（代码中通过 arguments[i] 访问）"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_file",
            "description": "将生成的文本、JSON、CSV、Markdown 或代码保存到本机 outputs 文件夹。用户要求下载/保存结果时使用，不能写入其他目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "文件名，例如 products.csv 或 report.md"},
                    "content": {"type": "string", "description": "要保存的完整文本内容"},
                    "overwrite": {"type": "boolean", "description": "同名文件是否覆盖，默认 false"},
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "列出当前 Agent 可以调用的本地 Skill。需要专门工作流时先调用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": "读取一个本地 Skill 的使用说明，获取工作流和约束后再执行任务。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "list_skills 返回的 Skill 名称"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_skill",
            "description": "把当前对话中验证过的操作经验总结为可复用的本地 Skill，并保存到 skills 文件夹。用户明确要求总结经验、生成 Skill 或保存工作流时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill 名称，例如 product-table-export"},
                    "description": {"type": "string", "description": "一句话说明什么时候使用该 Skill"},
                    "content": {"type": "string", "description": "完整 Markdown 工作流：适用场景、前置条件、步骤、验证方式和注意事项"},
                    "overwrite": {"type": "boolean", "description": "同名 Skill 是否覆盖，默认 false"},
                },
                "required": ["name", "description", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "将用户明确要求长期记住的偏好、身份或规则保存到本机长期记忆。只有用户明确要求记住时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要长期记住的内容"},
                    "category": {"type": "string", "description": "分类，例如 preference、profile、workflow"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "查询本机长期记忆。需要使用用户偏好或过去约定时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询关键词，为空则返回最近记忆"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_task_plan",
            "description": "为包含多个步骤的复杂任务创建可追踪计划。创建计划后再执行浏览器操作；简单的一问一答不需要调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "任务目标"},
                    "steps": {
                        "type": "array",
                        "description": "按执行顺序排列的步骤，最多 12 步",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "稳定的步骤标识，例如 collect-data"},
                                "title": {"type": "string", "description": "给用户看的步骤名称"},
                            },
                            "required": ["id", "title"],
                        },
                    },
                },
                "required": ["goal", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_plan",
            "description": "更新任务计划中某一步的状态。开始执行时设为 running，完成后设为 completed，无法完成时设为 failed。",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string", "description": "set_task_plan 返回的步骤 id"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "running", "completed", "failed", "skipped"],
                    },
                    "detail": {"type": "string", "description": "可选的进度或失败原因"},
                },
                "required": ["step_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "等待指定秒数（如等待页面加载、动画完成）。1-30 秒",
            "parameters": {
                "type": "object",
                "properties": {"seconds": {"type": "integer", "minimum": 1, "maximum": 30}},
                "required": ["seconds"],
            },
        },
    },
]

# 工具结果入对话历史时的默认截断长度。页面读取和脚本提取通常包含
# 结构化数据，使用更大的独立限额，避免模型因看不到完整结果而重复调用。
TOOL_RESULT_MAX_LEN = 4000
TOOL_RESULT_LIMIT_KEYS = {
    "get_page_content": "page_content_result_max_len",
    "execute_script": "execute_script_result_max_len",
}


def _truncate_result(result) -> dict:
    """截断工具结果（用于入历史）"""
    if isinstance(result, dict) and "data" in result:
        result = {**result, "data": f"[截断 {len(result.get('data', ''))} 字符]"}
    return result


async def execute_tool(name: str, args: dict, send_to_extension) -> dict:
    """
    执行工具调用，返回结果 dict。任何异常包装为 {"error": str}，供模型继续决策。
    """
    try:
        if name == "get_page_info":
            return await send_to_extension("getPageInfo", {})
        elif name == "get_page_content":
            return await send_to_extension("getPageContent", {
                "maxTextLen": args.get("max_text_len", 2000),
                "includeLinks": args.get("include_links", True),
                "includeImages": args.get("include_images", False),
            })
        elif name == "click_element":
            if args.get("selector"):
                return await send_to_extension("clickElement", {"selector": args["selector"]})
            return await _click_text(
                send_to_extension,
                text=args.get("text") or args.get("text_contains"),
                exact=bool(args.get("text")),
                tag_name=args.get("tag_name"),
            )
        elif name == "input_text":
            return await _input_text(
                send_to_extension,
                text=args.get("text", ""),
                selector=args.get("selector"),
                placeholder=args.get("placeholder"),
                clear=args.get("clear", True),
            )
        elif name == "scroll_to":
            return await send_to_extension("scrollTo", {
                "to": args.get("to"),
                "y": args.get("y"),
            })
        elif name == "open_url":
            return await send_to_extension("openUrl", {
                "url": args.get("url"),
                "tabId": args.get("tab_id"),
            })
        elif name == "close_tab":
            return await send_to_extension("closeTab", {"tabId": args.get("tab_id")})
        elif name == "list_tabs":
            return await send_to_extension("getTabs", {})
        elif name == "get_images":
            return await send_to_extension("getImages", {"minSize": args.get("min_size", 0)})
        elif name == "take_screenshot":
            return await send_to_extension("takeScreenshot", {})
        elif name == "execute_script":
            return await send_to_extension("executeScript", {
                "code": args.get("code", ""),
                "args": args.get("args") or [],
            })
        elif name == "save_file":
            return _save_file(args)
        elif name == "list_skills":
            return skills.list_skills()
        elif name == "read_skill":
            return skills.read_skill(args.get("name", ""))
        elif name == "create_skill":
            return skills.create_skill(
                args.get("name", ""), args.get("description", ""),
                args.get("content", ""), bool(args.get("overwrite", False)),
            )
        elif name == "remember":
            return memory.remember(args.get("content", ""), args.get("category", "general"))
        elif name == "recall_memory":
            return memory.recall(args.get("query", ""), args.get("limit", 10))
        elif name == "wait":
            seconds = max(1, min(30, int(args.get("seconds", 1))))
            await asyncio.sleep(seconds)
            return {"ok": True, "waited": seconds}
        else:
            return {"error": f"未知工具: {name}"}
    except Exception as e:
        return {"error": f"工具执行异常: {e}"}


def result_to_text(result: dict, tool_name: str | None = None) -> str:
    """把工具结果序列化为历史消息，并按工具类型使用不同容量。"""
    result = _truncate_result(result)
    text = json.dumps(result, ensure_ascii=False)
    config_key = TOOL_RESULT_LIMIT_KEYS.get(tool_name, "tool_result_max_len")
    limit = max(500, min(30000, int(config.get(config_key, TOOL_RESULT_MAX_LEN))))
    if len(text) > limit:
        total = len(text)
        text = (
            text[:limit]
            + f"... [结果截断：保留前 {limit}/{total} 字符。请按范围继续读取，不要重复相同调用]"
        )
    return text


def _save_file(args: dict) -> dict:
    """Save generated text beneath the project-local outputs directory."""
    root = Path(__file__).resolve().parents[2] / "outputs"
    filename = str(args.get("filename") or "").strip().replace("\\", "/")
    content = args.get("content")
    if not filename or not isinstance(content, str):
        return {"error": "filename 和 content 不能为空"}
    if len(content.encode("utf-8")) > 10 * 1024 * 1024:
        return {"error": "文件内容超过 10MB 限制"}
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        return {"error": "只能保存到 outputs 文件夹，文件名不能包含绝对路径或 .."}
    target = (root / relative).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        return {"error": "无效的保存路径"}
    if target.exists() and not args.get("overwrite", False):
        return {"error": f"文件已存在：{target}，如需覆盖请设置 overwrite=true"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target), "size": target.stat().st_size}
