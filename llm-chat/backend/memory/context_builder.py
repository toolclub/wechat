"""
上下文构建器：将对话历史组装为发送给 LLM 的 LangChain 消息列表

改进点（相比原版）：
  1. 长期记忆去重：过滤与近期对话高度重叠的记忆，减少噪音
  2. 渐进式 forget_mode：不是二元的"全要/只要几条"，而是梯度截断
  3. 结构化系统提示：记忆内容用明确标签区分，LLM 更容易理解层次
"""
from __future__ import annotations

from datetime import date

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config import SHORT_TERM_FORGET_TURNS, SHORT_TERM_MAX_TURNS, DEFAULT_SYSTEM_PROMPT
from memory.schema import Conversation, Message


def build_messages(
    conv: Conversation | None,
    long_term_memories: list[str] | None = None,
    forget_mode: bool = False,
    tool_names: list[str] | None = None,
) -> list[BaseMessage]:
    """
    构建发送给 LLM 的完整消息列表。

    Args:
        conv:               当前对话对象（为 None 时使用默认提示词）
        long_term_memories: 从 Qdrant 检索到的相关历史记录
        forget_mode:        True 时缩短历史窗口，且不注入远期记忆（降低干扰）
        tool_names:         可用工具名称列表，注入到系统提示中

    Returns:
        list[BaseMessage]，可直接传给 LLM.ainvoke()
    """
    today = date.today().strftime("%Y年%m月%d日")
    base_prompt = (conv.system_prompt if conv and conv.system_prompt else DEFAULT_SYSTEM_PROMPT)

    # ── 1. 系统提示（结构化分段，LLM 更易解析） ─────────────────────────────────
    system_parts: list[str] = [
        f"{base_prompt}\n\n当前日期：{today}。搜索时直接用核心关键词，不要手动添加年份。"
    ]

    if not forget_mode:
        # 中期摘要：远期对话的语义压缩
        if conv and conv.mid_term_summary:
            system_parts.append(
                "\n【对话背景摘要】\n"
                "以下是之前对话的压缩摘要，请结合这些背景来回答：\n"
                f"{conv.mid_term_summary}"
            )

        # 长期记忆：RAG 检索结果（去重后注入）
        cleaned_memories = _deduplicate_memories(
            long_term_memories or [],
            conv.messages if conv else [],
        )
        if cleaned_memories:
            memories_text = "\n\n".join(cleaned_memories)
            system_parts.append(
                "\n【长期记忆】\n"
                "以下是与当前问题高度相关的历史对话记录，请参考这些内容来回答：\n"
                f"{memories_text}"
            )

    messages: list[BaseMessage] = [SystemMessage(content="\n".join(system_parts))]

    # ── 2. 滑动窗口历史 ───────────────────────────────────────────────────────
    if conv and conv.messages:
        window = _select_history_window(conv.messages, forget_mode)
        for msg in window:
            if msg.role == "user":
                messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                # 截断过长的 AI 历史回复（多步执行结果可能很长）
                content = _truncate_assistant_history(msg.content)
                messages.append(AIMessage(content=content))

    return messages


def _select_history_window(messages: list[Message], forget_mode: bool) -> list[Message]:
    """
    选择历史消息窗口。

    正常模式：最近 SHORT_TERM_MAX_TURNS 轮（取 *2 条，含 user+assistant）
    forget_mode：缩减到 SHORT_TERM_FORGET_TURNS 轮，减少干扰

    渐进式策略：forget_mode 不是硬截断到 0，而是给一个中间值，
    保留最近几轮以维持基本对话连贯性。
    """
    max_msgs = (SHORT_TERM_MAX_TURNS * 2) if not forget_mode else (SHORT_TERM_FORGET_TURNS * 2)
    return messages[-max_msgs:]


def _truncate_assistant_history(content: str, max_len: int = 800) -> str:
    """
    截断历史 AI 回复中过长的多步执行摘要部分。

    多步任务保存时会附带"执行过程摘要"，这在历史上下文中会占大量 token。
    保留开头（核心答案）和标记后的部分，中间过长时截断。
    """
    if len(content) <= max_len:
        return content

    # 若含执行过程摘要，只保留核心答案部分
    summary_marker = "【执行过程摘要】"
    if summary_marker in content:
        idx = content.index(summary_marker)
        core = content[:idx].strip()
        return core[:max_len] + ("..." if len(core) > max_len else "")

    return content[:max_len] + "..."


def _deduplicate_memories(
    long_term_memories: list[str],
    recent_messages: list[Message],
) -> list[str]:
    """
    过滤与近期对话内容高度重叠的长期记忆，避免重复注入。

    策略：提取近期消息的关键词集合，若记忆内容的关键词重叠率超过阈值，则跳过。
    简单且高效，不引入额外 embedding 调用。
    """
    if not long_term_memories:
        return []

    # 构建近期对话的关键词集合（最近 6 条消息）
    recent_text = " ".join(
        m.content for m in recent_messages[-6:]
    ).lower()
    recent_words = set(w for w in recent_text.split() if len(w) > 1)

    result: list[str] = []
    for mem in long_term_memories:
        mem_words = [w for w in mem.lower().split() if len(w) > 1]
        if len(mem_words) < 5:
            # 极短记忆直接保留，避免误删
            result.append(mem)
            continue

        overlap = sum(1 for w in mem_words if w in recent_words) / len(mem_words)
        if overlap >= 0.55:
            # 超过 55% 关键词已在近期对话中出现 → 记忆为冗余信息，跳过
            continue
        result.append(mem)

    return result


def should_compress(conv: Conversation) -> bool:
    """当未摘要的消息累积到阈值时返回 True。"""
    from config import COMPRESS_TRIGGER
    unsummarised = len(conv.messages) - conv.mid_term_cursor
    return unsummarised >= COMPRESS_TRIGGER * 2


def slice_for_compression(conv: Conversation):
    """
    返回 (待摘要消息列表, 新游标位置)。
    只将游标到滑动窗口起点之间的消息发送给摘要模型——保持滑动窗口完整。
    """
    keep_count = (SHORT_TERM_MAX_TURNS // 2) * 2
    new_cursor = max(conv.mid_term_cursor, len(conv.messages) - keep_count)
    to_summarise = conv.messages[conv.mid_term_cursor:new_cursor]
    return to_summarise, new_cursor
