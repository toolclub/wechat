"""
上下文压缩器：对话过长时生成滚动摘要，推进游标
替代原来 harness.py 中的 maybe_compress() 逻辑

压缩流程：
  1. should_compress() 检查阈值
  2. slice_for_compression() 确定待摘要范围
  3. batch_store_pairs() 将待摘要消息写入 Qdrant（RAG 长期记忆）
  4. 调用摘要模型生成新摘要
  5. 更新 conv.mid_term_summary + mid_term_cursor，持久化
"""
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from config import LONGTERM_MEMORY_ENABLED, SUMMARY_SYSTEM_PROMPT
from llm.chat import get_summary_llm
from memory import store as memory_store
from memory.context_builder import should_compress, slice_for_compression

logger = logging.getLogger("memory.compressor")


async def maybe_compress(conv_id: str) -> bool:
    """
    检查并按需执行压缩。

    Returns:
        True 表示执行了压缩，False 表示未执行。
    """
    conv = memory_store.get(conv_id)
    if not conv or not should_compress(conv):
        return False

    to_summarise, new_cursor = slice_for_compression(conv)
    if not to_summarise:
        return False

    # 先写入长期记忆（压缩触发时批量，而非每轮写入）
    if LONGTERM_MEMORY_ENABLED:
        from rag.ingestor import batch_store_pairs
        await batch_store_pairs(conv_id, to_summarise, conv.mid_term_cursor)

    # 构建摘要提示
    history_text = "\n".join(
        f"{'用户' if m.role == 'user' else 'AI'}: {m.content}"
        for m in to_summarise
    )
    existing = conv.mid_term_summary
    prompt_content = (
        (f"已有摘要：\n{existing}\n\n" if existing else "")
        + f"新增对话：\n{history_text}\n\n"
        + "请将以上内容更新为一段完整的中文摘要，保留关键信息、用户偏好、重要结论。"
    )

    llm = get_summary_llm()
    resp = await llm.ainvoke([
        SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
        HumanMessage(content=prompt_content),
    ])
    new_summary = resp.content.strip()

    conv.mid_term_summary = new_summary
    conv.mid_term_cursor = new_cursor
    memory_store.save(conv)

    logger.info(
        "压缩完成 conv=%s 摘要了%d条消息，窗口=%d，摘要长度=%d",
        conv_id,
        len(to_summarise),
        len(conv.messages) - new_cursor,
        len(new_summary),
    )
    return True
