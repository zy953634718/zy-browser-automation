"""
配置管理 — 加载优先级：运行时覆盖（扩展 POST /config）→ 环境变量 → config.json → 默认值
"""

import json
import os
from pathlib import Path

_CONFIG_FILE = Path(__file__).resolve().parents[1] / "config.json"
# Runtime settings are kept separately from the shipped defaults.  This lets
# the extension remember the API key across service restarts without changing
# the distributable config.json.
_USER_CONFIG_FILE = Path(__file__).resolve().parents[1] / "config.local.json"

# 默认值（config.json 缺失时使用）
_DEFAULTS = {
    "api_key": "",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "ws_port": 18767,
    "http_port": 18768,
    # 复杂页面（例如分批读取表格）需要多次工具调用；同时仍保留上限
    # 防止模型异常循环。
    "max_tool_rounds": 16,
    "tool_result_max_len": 4000,
    "page_content_result_max_len": 8000,
    "execute_script_result_max_len": 12000,
    "api_timeout": 60,
}

# 模块级缓存（启动时加载一次）
_runtime: dict = {}  # 运行时覆盖，优先级最高
_env = {}            # 环境变量
_file = {}           # config.json


def _load_file_config() -> dict:
    """读取默认配置和本机覆盖；损坏文件不会阻止服务启动。"""
    result = {}
    for path in (_CONFIG_FILE, _USER_CONFIG_FILE):
        try:
            if path.is_file():
                with open(path, encoding="utf-8") as f:
                    value = json.load(f)
                if isinstance(value, dict):
                    result.update(value)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[config] {path.name} 读取失败: {e}")
    return result


def _load_env_config() -> dict:
    """读取环境变量覆盖（显式提供才覆盖，避免污染）"""
    env = {}
    if os.environ.get("DEEPSEEK_API_KEY"):
        env["api_key"] = os.environ["DEEPSEEK_API_KEY"]
    if os.environ.get("DEEPSEEK_MODEL"):
        env["model"] = os.environ["DEEPSEEK_MODEL"]
    if os.environ.get("DEEPSEEK_BASE_URL"):
        env["base_url"] = os.environ["DEEPSEEK_BASE_URL"]
    return env


_env = _load_env_config()
_file = _load_file_config()


def get(key: str, default=None):
    """获取配置值。优先级：运行时覆盖 > 环境变量 > config.json > 默认值"""
    for source in (_runtime, _env, _file):
        if key in source:
            return source[key]
    return _DEFAULTS.get(key, default)


def update_runtime(updates: dict, *, persist: bool = False):
    """运行时覆盖配置；可选持久化到本机覆盖文件。"""
    changed = {}
    for k, v in updates.items():
        if v is not None and k in _DEFAULTS:
            _runtime[k] = v
            changed[k] = v
    if persist and changed:
        try:
            existing = {}
            if _USER_CONFIG_FILE.is_file():
                with open(_USER_CONFIG_FILE, encoding="utf-8") as f:
                    existing = json.load(f)
            existing.update(changed)
            _USER_CONFIG_FILE.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except (OSError, json.JSONDecodeError) as e:
            print(f"[config] 本机配置保存失败: {e}")


def has_api_key() -> bool:
    return bool(get("api_key"))
