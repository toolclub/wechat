"""
RAG 写入层：在压缩时批量将 Q&A 对写入 Qdrant
与 retriever 分开，让职责更清晰。
"""
import logging
from memory.schema import Message
from rag import retriever

logger = logging.getLogger("rag.ingestor")


async def batch_store_pairs(
    conv_id: str,
    messages: list[Message],
    base_idx: int,
) -> None:
    """
    将待压缩的消息列表中的 user/assistant 对批量写入 Qdrant。
    仅在压缩触发时调用，不在每轮对话后写入（批量更高效）。

    Args:
        conv_id:   对话 ID
        messages:  待摘要的消息列表（从游标到滑动窗口起点）
        base_idx:  messages[0] 在完整历史中的索引（用于生成稳定 point_id）
    """
    i = 0
    stored = 0
    while i + 1 < len(messages):
        if messages[i].role == "user" and messages[i + 1].role == "assistant":
            await retriever.store_pair(
                conv_id,
                messages[i].content,
                messages[i + 1].content,
                base_idx + i,
            )
            stored += 1
        i += 2
    logger.info("RAG 批量写入完成: conv=%s 写入 %d 对", conv_id, stored)
