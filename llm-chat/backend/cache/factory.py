"""
语义缓存工厂：管理全局单例，按配置选择后端实现。

扩展新后端：
  1. 在 cache/ 下新建后端模块（继承 SemanticCache）
  2. 在 init_cache() 中按 SEMANTIC_CACHE_BACKEND 值实例化
  3. 在 config.py 增加对应参数
"""
from __future__ import annotations

import logging
from typing import Optional

from cache.base import CacheLookupResult, SemanticCache

logger = logging.getLogger("cache.factory")

_instance: Optional[SemanticCache] = None


def get_cache() -> SemanticCache:
    """返回已初始化的缓存单例。调用前须先在 lifespan 中执行 init_cache()。"""
    if _instance is None:
        raise RuntimeError(
            "Semantic cache 未初始化，请先在 lifespan 中调用 cache.factory.init_cache()"
        )
    return _instance


async def init_cache() -> None:
    """
    应用启动时调用：按配置构建并初始化缓存后端单例。

    若初始化失败（Redis 不可达等），自动降级为 _NullCache，
    主流程不受影响。
    """
    global _instance
    from config import (
        SEMANTIC_CACHE_ENABLED,
        REDIS_URL,
        SEMANTIC_CACHE_INDEX,
        SEMANTIC_CACHE_THRESHOLD,
        EMBEDDING_DIM,
    )

    if not SEMANTIC_CACHE_ENABLED:
        logger.info("Semantic cache 已禁用（SEMANTIC_CACHE_ENABLED=false）")
        _instance = _NullCache()
        return

    from cache.redis_cache import RedisCacheBackend

    backend = RedisCacheBackend(
        redis_url=REDIS_URL,
        index_name=SEMANTIC_CACHE_INDEX,
        vector_dim=EMBEDDING_DIM,
        threshold=SEMANTIC_CACHE_THRESHOLD,
    )
    try:
        await backend.init()
        _instance = backend
        logger.info(
            "Semantic cache 就绪  backend=Redis  url=%s  index=%s  threshold=%.2f",
            REDIS_URL, SEMANTIC_CACHE_INDEX, SEMANTIC_CACHE_THRESHOLD,
        )
    except Exception as exc:
        logger.error("Semantic cache 初始化失败，降级为 NullCache: %s", exc)
        _instance = _NullCache()


class _NullCache(SemanticCache):
    """
    禁用态/降级态缓存：所有操作为空操作，不影响主流程。
    当 SEMANTIC_CACHE_ENABLED=false 或 Redis 不可达时自动启用。
    """

    async def init(self) -> None:
        pass

    async def lookup(
        self, question: str, namespace: str = "global"
    ) -> Optional[CacheLookupResult]:
        return None

    async def store(
        self, question: str, answer: str, namespace: str = "global",
        ttl_seconds: int | None = None,
    ) -> None:
        pass

    async def clear(self, namespace: Optional[str] = None) -> None:
        pass
