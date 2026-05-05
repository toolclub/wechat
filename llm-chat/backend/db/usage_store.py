"""
UsageStore：Token 使用记录存储
"""
import time
import logging
from db.database import AsyncSessionLocal
from db.models import UserUsageLogModel

logger = logging.getLogger("db.usage_store")

async def record_usage(
    user_id: str,
    client_id: str,
    conv_id: str,
    node: str,
    model: str,
    usage: dict
) -> None:
    """持久化 Token 使用记录到 user_usage_logs 表"""
    if not usage:
        return

    try:
        async with AsyncSessionLocal() as db:
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            reasoning_tokens = usage.get("reasoning_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

            log = UserUsageLogModel(
                user_id=user_id or "",
                client_id=client_id or "",
                conv_id=conv_id or "",
                node=node or "",
                model=model or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reasoning_tokens=reasoning_tokens,
                total_tokens=total_tokens,
                created_at=time.time()
            )
            db.add(log)
            await db.commit()
            logger.debug(
                "Usage recorded | user=%s | client=%s | node=%s | total=%d",
                user_id or "GUEST", client_id, node, total_tokens
            )
    except Exception as e:
        logger.error("Failed to record usage: %s", e, exc_info=True)

async def get_aggregated_usage(user_id: str = None, days: int = 7):
    """
    获取汇总统计数据（用于 Admin Dashboard）。
    
    返回：
      - total_tokens
      - user_tokens (登录用户)
      - guest_tokens (游客)
    """
    from sqlalchemy import func
    import time

    start_time = time.time() - (days * 86400)
    
    try:
        async with AsyncSessionLocal() as db:
            # 基础查询
            from sqlalchemy import select
            
            stmt = select(
                func.sum(UserUsageLogModel.total_tokens).label("total"),
                func.sum(UserUsageLogModel.prompt_tokens).label("prompt"),
                func.sum(UserUsageLogModel.completion_tokens).label("completion"),
                func.sum(UserUsageLogModel.reasoning_tokens).label("reasoning")
            ).where(UserUsageLogModel.created_at >= start_time)

            overall_res = await db.execute(stmt)
            overall = overall_res.one_or_none()
            
            # 登录用户汇总
            user_res = await db.execute(stmt.where(UserUsageLogModel.user_id != ""))
            user_usage = user_res.one_or_none()
            
            # 游客汇总
            guest_res = await db.execute(stmt.where(UserUsageLogModel.user_id == ""))
            guest_usage = guest_res.one_or_none()
            
            return {
                "overall": {
                    "total": int(overall.total or 0) if overall else 0,
                    "prompt": int(overall.prompt or 0) if overall else 0,
                    "completion": int(overall.completion or 0) if overall else 0,
                    "reasoning": int(overall.reasoning or 0) if overall else 0
                },
                "users": {
                    "total": int(user_usage.total or 0) if user_usage else 0,
                    "prompt": int(user_usage.prompt or 0) if user_usage else 0,
                    "completion": int(user_usage.completion or 0) if user_usage else 0
                },
                "guests": {
                    "total": int(guest_usage.total or 0) if guest_usage else 0,
                    "prompt": int(guest_usage.prompt or 0) if guest_usage else 0,
                    "completion": int(guest_usage.completion or 0) if guest_usage else 0
                }
            }
    except Exception as e:
        logger.error("Failed to get aggregated usage: %s", e)
        return None
