"""
核心记忆：由 LLM 通过 remember_preference 工具显式写入的长期偏好与项目规则。

设计原则：
  - 不做隐式抽取（不扫 regex / 关键词）
  - 只接受显式调用：由工具或 API 写入
  - 渲染由 context_builder 负责（按分层分别注入系统提示）
"""
from __future__ import annotations

from memory.schema import Conversation

_LIST_FIELDS = ("user_profile", "project_rules", "learned_preferences")
_MAX_ITEMS_PER_FIELD = 12

# 合法的 category，供 remember_preference 工具校验
VALID_CATEGORIES = (*_LIST_FIELDS, "current_task")


def ensure_core_memory(core_memory: dict | None) -> dict:
    """归一化 core_memory 数据结构，缺失字段用默认值补齐。"""
    data = dict(core_memory or {})
    for field in _LIST_FIELDS:
        value = data.get(field, [])
        data[field] = list(value) if isinstance(value, list) else []
    current_task = data.get("current_task", "")
    data["current_task"] = current_task.strip() if isinstance(current_task, str) else ""
    return data


def add_to_core_memory(conv: Conversation, category: str, content: str) -> bool:
    """
    向 core_memory 写入一条内容。仅供显式调用路径（工具 / API）使用。

    Returns:
        True 表示实际发生变更；False 表示重复或无效内容。
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(f"非法的 category: {category}")

    clean = (content or "").strip()
    if not clean:
        return False

    base = ensure_core_memory(getattr(conv, "core_memory", {}))

    if category == "current_task":
        if base["current_task"] == clean:
            return False
        base["current_task"] = clean
        conv.core_memory = base
        return True

    existing = base[category]
    if any(_normalize(item) == _normalize(clean) for item in existing):
        return False
    existing.append(clean)
    base[category] = existing[-_MAX_ITEMS_PER_FIELD:]
    conv.core_memory = base
    return True


def _normalize(text: str) -> str:
    return "".join((text or "").split()).lower()
