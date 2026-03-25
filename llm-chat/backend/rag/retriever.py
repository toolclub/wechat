"""
RAG 检索层：Qdrant 向量存储
替代原来的 layers/longterm.py

存储策略：每轮 Q&A 对在压缩时批量写入（见 rag/ingestor.py）
检索策略：按 conv_id 过滤 + 余弦相似度 Top-K
忘记模式：RAG 未命中时，计算 query 与摘要/近期消息的余弦相似度判断话题连续性
"""
import asyncio
import hashlib
import logging
import math
from typing import Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import (
    EMBEDDING_DIM,
    LONGTERM_SCORE_THRESHOLD,
    LONGTERM_TOP_K,
    QDRANT_COLLECTION,
    QDRANT_URL,
    SUMMARY_RELEVANCE_THRESHOLD,
)
from llm.embeddings import embed_text

logger = logging.getLogger("rag.retriever")

_client: Optional[AsyncQdrantClient] = None


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=QDRANT_URL)
    return _client


def _point_id(conv_id: str, user_idx: int) -> int:
    """稳定可重现的 uint63 point ID，避免 hash() 受 PYTHONHASHSEED 影响。"""
    raw = f"{conv_id}:{user_idx}".encode()
    digest = hashlib.md5(raw).digest()
    return int.from_bytes(digest[:8], "big") % (2**63)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


# ── 初始化 ────────────────────────────────────────────────────────────────────

async def init_collection() -> None:
    """启动时调用：若 Collection 不存在则创建。"""
    client = get_client()
    resp = await client.get_collections()
    existing = {c.name for c in resp.collections}
    if QDRANT_COLLECTION not in existing:
        await client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info("Qdrant: 已创建 Collection '%s'", QDRANT_COLLECTION)
    else:
        logger.info("Qdrant: Collection '%s' 就绪", QDRANT_COLLECTION)


# ── 写入 ──────────────────────────────────────────────────────────────────────

async def store_pair(
    conv_id: str,
    user_msg: str,
    assistant_msg: str,
    user_idx: int,
) -> None:
    """将一轮 Q&A 向量化后写入 Qdrant（向量来自 user_msg，便于相关性检索）。"""
    try:
        vector = await embed_text(user_msg)
        point_id = _point_id(conv_id, user_idx)
        await get_client().upsert(
            collection_name=QDRANT_COLLECTION,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "conv_id": conv_id,
                        "user": user_msg,
                        "assistant": assistant_msg,
                        "msg_idx": user_idx,
                    },
                )
            ],
        )
        logger.debug("Qdrant: 已存储 conv=%s idx=%d", conv_id, user_idx)
    except Exception as exc:
        logger.error("Qdrant store_pair 失败: %s", exc)


# ── 检索 ──────────────────────────────────────────────────────────────────────

async def search_memories(
    conv_id: str,
    query: str,
    top_k: int = LONGTERM_TOP_K,
) -> list[str]:
    """检索与 query 最相关的历史 Q&A 对，返回格式化字符串列表。"""
    try:
        vector = await embed_text(query)
        response = await get_client().query_points(
            collection_name=QDRANT_COLLECTION,
            query=vector,
            query_filter=Filter(
                must=[FieldCondition(key="conv_id", match=MatchValue(value=conv_id))]
            ),
            limit=top_k,
            score_threshold=LONGTERM_SCORE_THRESHOLD,
        )
        return [
            f"用户: {r.payload.get('user', '')}\n助手: {r.payload.get('assistant', '')}"
            for r in response.points
        ]
    except Exception as exc:
        logger.error("Qdrant search_memories 失败: %s", exc)
        return []


# ── 忘记模式判断 ──────────────────────────────────────────────────────────────

async def is_relevant_to_summary(query: str, summary: str) -> bool:
    """判断 query 是否与中期摘要在语义上相关（低于阈值则触发忘记模式）。"""
    try:
        vec_q, vec_s = await asyncio.gather(embed_text(query), embed_text(summary))
        sim = _cosine_similarity(vec_q, vec_s)
        logger.info("query与摘要相似度: %.4f (阈值: %.2f)", sim, SUMMARY_RELEVANCE_THRESHOLD)
        return sim >= SUMMARY_RELEVANCE_THRESHOLD
    except Exception as exc:
        logger.error("is_relevant_to_summary 失败: %s", exc)
        return True  # 出错保守处理，不触发忘记


async def is_relevant_to_recent(query: str, recent_msgs: list[str]) -> bool:
    """无摘要时的替代方案：与最近几条用户消息的平均余弦相似度判断话题连续性。"""
    try:
        vecs = await asyncio.gather(
            embed_text(query), *[embed_text(m) for m in recent_msgs]
        )
        sims = [_cosine_similarity(vecs[0], v) for v in vecs[1:]]
        avg_sim = sum(sims) / len(sims) if sims else 0.0
        logger.info("query与近期消息平均相似度: %.4f (阈值: %.2f)", avg_sim, SUMMARY_RELEVANCE_THRESHOLD)
        return avg_sim >= SUMMARY_RELEVANCE_THRESHOLD
    except Exception as exc:
        logger.error("is_relevant_to_recent 失败: %s", exc)
        return True


# ── 删除 / 统计 ───────────────────────────────────────────────────────────────

async def delete_by_conv(conv_id: str) -> None:
    """删除某会话的所有长期记忆。"""
    try:
        await get_client().delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="conv_id", match=MatchValue(value=conv_id))]
                )
            ),
        )
        logger.info("Qdrant: 已清除 conv=%s 的所有记忆", conv_id)
    except Exception as exc:
        logger.error("Qdrant delete_by_conv 失败: %s", exc)


async def count_by_conv(conv_id: str) -> int:
    """返回某会话在 Qdrant 中存储的记忆条数（供调试接口使用）。"""
    try:
        result = await get_client().count(
            collection_name=QDRANT_COLLECTION,
            count_filter=Filter(
                must=[FieldCondition(key="conv_id", match=MatchValue(value=conv_id))]
            ),
            exact=True,
        )
        return result.count
    except Exception as exc:
        logger.error("Qdrant count_by_conv 失败: %s", exc)
        return -1
