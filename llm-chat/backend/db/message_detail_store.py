"""
消息详情存储层：保存和读取每条消息的完整结构化数据（thinking、工具调用、步骤等）。
供前端刷新后完整恢复 UI 状态。
"""
import logging
import time

from sqlalchemy import select, delete as sa_delete

from db.database import AsyncSessionLocal
from db.models import MessageDetailModel

logger = logging.getLogger("db.message_detail_store")


async def save_message_detail(
    conv_id: str,
    msg_index: int,
    role: str,
    content: str = "",
    thinking: str = "",
    tool_calls: list | None = None,
    steps: list | None = None,
    search_results: list | None = None,
    sandbox_output: str = "",
    stream_completed: bool = True,
    stream_buffer: str = "",
    images: list | None = None,
) -> int:
    """保存一条消息的详情，返回自增 ID。"""
    now = time.time()
    async with AsyncSessionLocal() as session:
        row = MessageDetailModel(
            conv_id=conv_id,
            msg_index=msg_index,
            role=role,
            content=content,
            thinking=thinking,
            tool_calls=tool_calls or [],
            steps=steps or [],
            search_results=search_results or [],
            sandbox_output=sandbox_output,
            stream_completed=stream_completed,
            stream_buffer=stream_buffer,
            images=images or [],
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        detail_id = row.id
        await session.commit()
    return detail_id


async def update_message_detail(
    detail_id: int,
    **kwargs,
) -> None:
    """更新消息详情的指定字段。"""
    from sqlalchemy import update as sa_update
    kwargs["updated_at"] = time.time()
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_update(MessageDetailModel)
            .where(MessageDetailModel.id == detail_id)
            .values(**kwargs)
        )
        await session.commit()


async def get_message_details_for_conv(conv_id: str) -> list[dict]:
    """获取对话的全部消息详情，按 msg_index 排序。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(MessageDetailModel)
            .where(MessageDetailModel.conv_id == conv_id)
            .order_by(MessageDetailModel.msg_index.asc(), MessageDetailModel.id.asc())
        )
        rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "conv_id": r.conv_id,
            "msg_index": r.msg_index,
            "role": r.role,
            "content": r.content,
            "thinking": r.thinking,
            "tool_calls": r.tool_calls or [],
            "steps": r.steps or [],
            "search_results": r.search_results or [],
            "sandbox_output": r.sandbox_output or "",
            "stream_completed": r.stream_completed,
            "stream_buffer": r.stream_buffer or "",
            "images": r.images or [],
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


async def delete_message_details_for_conv(conv_id: str) -> None:
    """删除对话的全部消息详情（对话删除时级联删除也可，这是显式版本）。"""
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_delete(MessageDetailModel)
            .where(MessageDetailModel.conv_id == conv_id)
        )
        await session.commit()
