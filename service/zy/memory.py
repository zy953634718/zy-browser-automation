"""本地长期记忆存储。

数据保存在 service/data/agent_memory.json，不上传到模型服务之外的地方。
只保存用户明确要求记住的内容和精简的对话索引，避免无限膨胀。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MEMORY_FILE = DATA_DIR / "agent_memory.json"
MAX_MEMORIES = 200
MAX_TURNS = 500


def _empty() -> dict:
    return {"memories": [], "turns": []}


def _load() -> dict:
    try:
        if MEMORY_FILE.is_file():
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {"memories": data.get("memories", []), "turns": data.get("turns", [])}
    except (OSError, json.JSONDecodeError):
        pass
    return _empty()


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = MEMORY_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(MEMORY_FILE)


def remember(content: str, category: str = "general") -> dict:
    content = str(content or "").strip()
    if not content:
        return {"ok": False, "error": "记忆内容不能为空"}
    data = _load()
    duplicate = next((item for item in data["memories"] if item.get("content") == content), None)
    if duplicate:
        duplicate["updated_at"] = int(time.time())
        _save(data)
        return {"ok": True, "id": duplicate.get("id"), "duplicate": True}
    item = {"id": uuid.uuid4().hex, "content": content[:2000], "category": category[:40], "created_at": int(time.time())}
    data["memories"].append(item)
    data["memories"] = data["memories"][-MAX_MEMORIES:]
    _save(data)
    return {"ok": True, "id": item["id"], "content": item["content"]}


def recall(query: str = "", limit: int = 10) -> dict:
    query = str(query or "").strip().lower()
    limit = max(1, min(30, int(limit or 10)))
    data = _load()
    items = data["memories"]
    turns = data.get("turns", [])
    if query:
        terms = [term for term in query.split() if term]
        items = sorted(items, key=lambda item: sum(term in item.get("content", "").lower() for term in terms), reverse=True)
        items = [item for item in items if any(term in item.get("content", "").lower() for term in terms)]
        turns = [
            turn for turn in reversed(turns)
            if any(term in f"{turn.get('user', '')} {turn.get('assistant', '')}".lower() for term in terms)
        ]
        return {"memories": items[:limit], "turns": turns[:limit]}
    return {"memories": items[-limit:], "turns": turns[-limit:]}


def record_turn(session_id: str, user_text: str, assistant_text: str) -> None:
    data = _load()
    data["turns"].append({
        "session_id": str(session_id),
        "user": str(user_text or "")[:4000],
        "assistant": str(assistant_text or "")[:4000],
        "created_at": int(time.time()),
    })
    data["turns"] = data["turns"][-MAX_TURNS:]
    _save(data)


def context(limit: int = 20) -> str:
    items = _load().get("memories", [])[-limit:]
    if not items:
        return "（暂无长期记忆）"
    return "\n".join(f"- [{item.get('category', 'general')}] {item.get('content', '')}" for item in items)


def clear() -> dict:
    _save(_empty())
    return {"ok": True}
