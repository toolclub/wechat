"""
上下文构建器：将对话历史组装为发送给 LLM 的 LangChain 消息列表
替代原来的 layers/context.py，输出 BaseMessage 而非原始 dict。

组装顺序：
  1. SystemMessage（系统提示 + 工具说明 + 中期摘要 + 长期记忆）
  2. 滑动窗口内的历史消息（HumanMessage / AIMessage）
     ─ forget_mode=True 时只保留最近 SHORT_TERM_FORGET_TURNS 轮
"""
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config import SHORT_TERM_FORGET_TURNS, SHORT_TERM_MAX_TURNS, DEFAULT_SYSTEM_PROMPT
from memory.schema import Conversation


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
        forget_mode:        True 时只发最近几轮，不注入任何记忆（降低干扰）
        tool_names:         可用工具名称列表，注入到系统提示中

    Returns:
        list[BaseMessage]，可直接传给 ChatOllama.ainvoke()
    """
    # ── 1. 系统提示 ────────────────────────────────────────────────────────────
    system_parts: list[str] = [
        (conv.system_prompt if conv and conv.system_prompt else DEFAULT_SYSTEM_PROMPT)
    ]

    if tool_names:
        tools_str = "、".join(tool_names)
        system_parts.append(f"\n你拥有以下工具可以调用：{tools_str}。遇到需要计算、搜索、查询时间等任务请主动使用。")

    if not forget_mode:
        # 中期摘要
        if conv and conv.mid_term_summary:
            system_parts.append(
                f"\n【对话背景摘要】以下是之前对话的压缩摘要，请结合这些背景来回答：\n{conv.mid_term_summary}"
            )
        # 长期记忆（RAG 检索结果）
        if long_term_memories:
            memories_text = "\n\n".join(long_term_memories)
            system_parts.append(
                f"\n【长期记忆】以下是与当前问题高度相关的历史对话记录，请参考这些内容来回答：\n{memories_text}"
            )

    messages: list[BaseMessage] = [SystemMessage(content="\n".join(system_parts))]

    # ── 2. 滑动窗口历史 ────────────────────────────────────────────────────────
    if conv:
        if forget_mode:
            window = conv.messages[-(SHORT_TERM_FORGET_TURNS * 2):]
        else:
            window = conv.messages[-(SHORT_TERM_MAX_TURNS * 2):]

        for msg in window:
            if msg.role == "user":
                messages.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                messages.append(AIMessage(content=msg.content))

    return messages


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
