"""
Layer 3b – Long-term Memory
Qdrant 向量存储：把每轮 Q&A 对嵌入后持久化，在下一次对话前检索最相关的历史记忆注入上下文。

存储单元：一对 (user_msg, assistant_msg) 作为一个 Point，向量取自 user_msg（用于相关性匹配）。
检索策略：用当前用户问题做 Embedding，按余弦相似度取 TOP-K，过滤同一会话。
author: leizihao
email: lzh19162600626@gmail.com
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
    EMBEDDING_MODEL,
    LONGTERM_SCORE_THRESHOLD,
    LONGTERM_TOP_K,
    QDRANT_COLLECTION,
    QDRANT_HOST,
    QDRANT_PORT,
    SUMMARY_RELEVANCE_THRESHOLD,
)
from ollama_client import get_embedding as _embed

logger = logging.getLogger("longterm")

_client: Optional[AsyncQdrantClient] = None


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _client


def _point_id(conv_id: str, user_idx: int) -> int:
    """稳定可重现的 uint63 point ID，避免 hash() 受 PYTHONHASHSEED 影响。"""
    raw = f"{conv_id}:{user_idx}".encode()
    digest = hashlib.md5(raw).digest()
    return int.from_bytes(digest[:8], "big") % (2 ** 63)


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


async def store_pair(
    conv_id: str,
    user_msg: str,
    assistant_msg: str,
    user_idx: int,
) -> None:
    """
    将一轮对话 (user_msg, assistant_msg) 向量化后存入 Qdrant。
    向量来自 user_msg，便于按"问题相关性"检索。
    """
    try:
        vector = await _embed(user_msg, EMBEDDING_MODEL)
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
        logger.info("Qdrant: 已存储 conv=%s idx=%d", conv_id, user_idx)
    except Exception as exc:
        logger.error("Qdrant store_pair 失败: %s", exc)


async def search_memories(
    conv_id: str,
    query: str,
    top_k: int = LONGTERM_TOP_K,
) -> list[str]:
    """
    检索与 query 最相关的历史 Q&A 对。
    返回格式：["用户: ...\n助手: ...", ...]
    """
    try:
        vector = await _embed(query, EMBEDDING_MODEL)
        results = await get_client().search(
            collection_name=QDRANT_COLLECTION,
            query_vector=vector,
            query_filter=Filter(
                must=[FieldCondition(key="conv_id", match=MatchValue(value=conv_id))]
            ),
            limit=top_k,
            score_threshold=LONGTERM_SCORE_THRESHOLD,
        )
        memories = []
        for r in results:
            user = r.payload.get("user", "")
            assistant = r.payload.get("assistant", "")
            memories.append(f"用户: {user}\n助手: {assistant}")

        return memories
    except Exception as exc:
        logger.error("Qdrant search_memories 失败: %s", exc)
        return []


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def is_relevant_to_recent(
    query: str,
    recent_msgs: list[str],
    threshold: float = SUMMARY_RELEVANCE_THRESHOLD,
) -> bool:
    """
    没有摘要时的替代方案：比较 query 与最近几条用户消息的平均余弦相似度。
    返回 True 表示话题连续，False 表示话题切换（可触发忘记）。
    """
    try:
        vecs = await asyncio.gather(
            _embed(query, EMBEDDING_MODEL),
            *[_embed(m, EMBEDDING_MODEL) for m in recent_msgs],
        )
        vec_q = vecs[0]
        sims = [_cosine_similarity(vec_q, v) for v in vecs[1:]]
        avg_sim = sum(sims) / len(sims)
        logger.info("query与近期消息平均相似度: %.4f (阈值: %.2f)", avg_sim, threshold)
        return avg_sim >= threshold
    except Exception as exc:
        logger.error("is_relevant_to_recent 失败: %s", exc)
        return True  # 出错保守处理，不触发忘记


async def is_relevant_to_summary(
    query: str,
    summary: str,
    threshold: float = SUMMARY_RELEVANCE_THRESHOLD,
) -> bool:
    """
    用 Embedding 余弦相似度判断 query 是否与摘要相关。
    返回 True 表示相关，False 表示不相关（可以触发忘记）。
    出错时保守返回 True，避免误触发忘记。
    """
    try:
        vec_q, vec_s = await asyncio.gather(
            _embed(query, EMBEDDING_MODEL),
            _embed(summary, EMBEDDING_MODEL),
        )
        sim = _cosine_similarity(vec_q, vec_s)
        logger.info("query与摘要相似度: %.4f (阈值: %.2f)", sim, threshold)
        return sim >= threshold
    except Exception as exc:
        logger.error("is_relevant_to_summary 失败: %s", exc)
        return True  # 出错保守处理，不触发忘记


async def delete_by_conv(conv_id: str) -> None:
    """删除某会话的所有长期记忆 Point。"""
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
    """返回某会话在 Qdrant 中存储的记忆条数（用于调试接口）。"""
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
