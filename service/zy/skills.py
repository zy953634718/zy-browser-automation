"""本地 Skill 目录发现与读取。

Skill 是项目内的 Markdown 指令文件。Agent 只允许读取已发现的文件名，
不会根据模型输入访问任意磁盘路径。
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = PROJECT_ROOT / "skills"


def _catalog() -> dict[str, Path]:
    result = {}
    root_skill = PROJECT_ROOT / "SKILL.md"
    if root_skill.is_file():
        result["browser-ai-assistant"] = root_skill
    if SKILL_ROOT.is_dir():
        for path in SKILL_ROOT.glob("*/SKILL.md"):
            result[path.parent.name] = path
    return result


def list_skills() -> dict:
    skills = []
    for name, path in _catalog().items():
        description = ""
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[:20]:
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"')
                    break
        except OSError:
            continue
        skills.append({"name": name, "description": description, "file": str(path)})
    return {"skills": skills}


def read_skill(name: str) -> dict:
    name = str(name or "").strip()
    path = _catalog().get(name)
    if not path:
        return {"error": f"未找到 Skill: {name}", "available": list(_catalog())}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"Skill 读取失败: {exc}"}
    return {"name": name, "content": content[:20000], "truncated": len(content) > 20000}


def skill_context() -> str:
    """Return a compact catalog for the Agent system prompt."""
    items = list_skills().get("skills", [])
    if not items:
        return "（暂无可用 Skill）"
    return "\n".join(f"- {item['name']}: {item.get('description') or '本地工作流'}" for item in items[:30])


def create_skill(name: str, description: str, content: str, overwrite: bool = False) -> dict:
    """Create a reusable local Skill under skills/<name>/SKILL.md."""
    raw_name = str(name or "").strip()
    slug = re.sub(r"[^\w-]+", "-", raw_name, flags=re.UNICODE).strip("-_")[:64]
    if not slug or slug in {".", ".."}:
        return {"error": "Skill 名称无效，请使用字母、数字、中文、短横线或下划线"}
    description = str(description or "通用本地工作流").strip().replace("\n", " ")[:300]
    content = str(content or "").strip()
    if not content:
        return {"error": "Skill 内容不能为空"}
    if len(content.encode("utf-8")) > 100 * 1024:
        return {"error": "Skill 内容不能超过 100KB"}
    skill_dir = SKILL_ROOT / slug
    path = skill_dir / "SKILL.md"
    if path.exists() and not overwrite:
        return {"error": f"Skill 已存在：{slug}，如需更新请设置 overwrite=true"}
    skill_dir.mkdir(parents=True, exist_ok=True)
    document = f"---\nname: {raw_name[:100]}\ndescription: {description}\n---\n\n{content}\n"
    path.write_text(document, encoding="utf-8")
    return {"ok": True, "name": slug, "path": str(path.resolve()), "description": description}
