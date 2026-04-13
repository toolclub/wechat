"""
Redis 跨 worker 共享状态 — 仅保留 stop 信号

历史上还托管过 streaming 注册和 store 缓存失效，已迁移到 DB：
  - streaming 活跃判定 → conversations.last_heartbeat_at
    （memory.store.heartbeat / is_streaming）
  - store 缓存失效   → 已废除内存缓存，所有读直接命中 DB

stop 信号留在 Redis 是因为它本质是"广播给所有 worker 的瞬时事件"，
DB 不适合做 pub/sub。失败时退化为本 worker 内的 _stop_events dict。
"""
import logging
from typing import Optional

import redis.asyncio as aioredis

from config import REDIS_URL

logger = logging.getLogger("db.redis_state")

_redis: Optional[aioredis.Redis] = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        if not REDIS_URL:
            raise RuntimeError("REDIS_URL 未配置，Redis 共享状态不可用")
        _redis = aioredis.from_url(
            REDIS_URL, decode_responses=True,
            max_connections=20, socket_keepalive=True, socket_connect_timeout=5,
        )
    return _redis


# ══════════════════════════════════════════════════════════════════════════════
# 停止信号（跨 worker 通知正在跑的图执行立即退出）
# ══════════════════════════════════════════════════════════════════════════════

_STOP_KEY_PREFIX = "chatflow:stop:"
_STOP_TTL = 60  # 60 秒自动过期（防止残留）


async def publish_stop(conv_id: str) -> None:
    """发布停止信号（任意 worker 都能收到）。"""
    r = _get_redis()
    key = f"{_STOP_KEY_PREFIX}{conv_id}"
    await r.set(key, "1", ex=_STOP_TTL)
    logger.info("发布停止信号 | conv=%s", conv_id)


async def check_stop(conv_id: str) -> bool:
    """检查是否有停止信号。"""
    r = _get_redis()
    key = f"{_STOP_KEY_PREFIX}{conv_id}"
    val = await r.get(key)
    return val == "1"


async def clear_stop(conv_id: str) -> None:
    """清除停止信号。"""
    r = _get_redis()
    await r.delete(f"{_STOP_KEY_PREFIX}{conv_id}")
