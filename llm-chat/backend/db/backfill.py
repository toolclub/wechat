"""
Token 数据回填工具：将 messages 表中的历史 Token 记录迁移到 user_usage_logs 审计表。
"""
import logging
import time
from sqlalchemy import select, func, text
from db.database import AsyncSessionLocal
from db.models import MessageModel, ConversationModel, UserUsageLogModel

logger = logging.getLogger("db.backfill")

async def backfill_usage_logs():
    """
    数据回填逻辑：
    1. 检查 user_usage_logs 是否为空。
    2. 如果为空且 messages 有数据，则进行迁移。
    """
    async with AsyncSessionLocal() as session:
        # 1. 检查审计表是否有数据
        count_stmt = select(func.count(UserUsageLogModel.id))
        count_res = await session.execute(count_stmt)
        count = count_res.scalar() or 0
        
        if count > 0:
            # logger.info("审计表已有数据，跳过自动回填")
            return

        # 2. 检查是否有历史消息需要迁移
        # 联表查询以获取 user_id 和 client_id
        stmt = (
            select(
                MessageModel.conv_id,
                MessageModel.prompt_tokens,
                MessageModel.completion_tokens,
                MessageModel.reasoning_tokens,
                MessageModel.created_at,
                ConversationModel.user_id,
                ConversationModel.client_id,
                ConversationModel.model_name
            )
            .join(ConversationModel, MessageModel.conv_id == ConversationModel.id)
            .where(MessageModel.role == "assistant")
            .where((MessageModel.prompt_tokens > 0) | (MessageModel.completion_tokens > 0))
        )
        
        result = await session.execute(stmt)
        rows = result.all()
        
        if not rows:
            logger.info("未发现需要回填的历史 Token 数据")
            return

        logger.info("开始回填历史 Token 数据 | 条数: %d", len(rows))
        
        new_logs = []
        for r in rows:
            new_logs.append(UserUsageLogModel(
                user_id=r.user_id or "",
                client_id=r.client_id or "",
                conv_id=r.conv_id,
                node="call_model", # 历史数据统一记为 call_model
                model=r.model_name or "unknown",
                prompt_tokens=r.prompt_tokens,
                completion_tokens=r.completion_tokens,
                reasoning_tokens=r.reasoning_tokens,
                total_tokens=r.prompt_tokens + r.completion_tokens,
                created_at=r.created_at
            ))
        
        # 批量插入
        session.add_all(new_logs)
        await session.commit()
        logger.info("历史 Token 数据回填完成")
