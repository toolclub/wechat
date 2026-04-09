"""
对话存储层：PostgreSQL 持久化 + 内存字典缓存

设计原则：
  - conv.messages 是唯一权威数据源，永不被删除
  - PostgreSQL 作为持久化后端，内存字典 _store 作为读缓存
  - 所有读操作（get / all_conversations）走缓存（保持向后兼容同步接口）
  - 所有写操作（create / save / add_message / delete）为 async，同时更新缓存和 DB
  - 启动时从 PostgreSQL 加载全部对话到内存缓存
"""
import logging
import time
from typing import Optional

from sqlalchemy import select, update as sa_update, delete as sa_delete

from db.database import AsyncSessionLocal
from db.models import ConversationModel, MessageModel
from memory.schema import Conversation, Message
from config import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger("memory.store")

_store: dict[str, Conversation] = {}


# ── 读缓存接口（同步，供图执行内部使用）────────────────────────────────────────

def get(conv_id: str) -> Optional[Conversation]:
    return _store.get(conv_id)


def all_conversations(client_id: str = "") -> list[Conversation]:
    """返回指定 client 的对话（内存缓存）。"""
    if not client_id:
        return list(_store.values())
    return [c for c in _store.values() if not c.client_id or c.client_id == client_id]


# ── DB 直查接口（多 worker 安全，供 API 端点使用）────────────────────────────────

async def db_get_conversation(conv_id: str) -> Optional[dict]:
    """从 DB 直接读取对话（跨 worker 一致性）。返回 dict 或 None。"""
    async with AsyncSessionLocal() as session:
        row = await session.get(ConversationModel, conv_id)
        if not row:
            return None

        msgs_result = await session.execute(
            select(MessageModel)
            .where(MessageModel.conv_id == conv_id)
            .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
        )
        msg_rows = msgs_result.scalars().all()

        # 同时刷新本 worker 的内存缓存
        messages = [
            Message(
                role=mr.role, content=mr.content, timestamp=mr.created_at, id=mr.id,
                tool_summary=getattr(mr, "tool_summary", "") or "",
                step_summary=getattr(mr, "step_summary", "") or "",
            )
            for mr in msg_rows
        ]
        conv = Conversation(
            id=row.id, title=row.title, system_prompt=row.system_prompt,
            messages=messages, mid_term_summary=row.mid_term_summary,
            mid_term_cursor=row.mid_term_cursor, created_at=row.created_at,
            updated_at=row.updated_at, client_id=row.client_id,
            status=getattr(row, "status", "active") or "active",
        )
        _store[conv_id] = conv  # 刷新缓存

        return {
            "id": row.id,
            "title": row.title,
            "system_prompt": row.system_prompt,
            "messages": [
                {
                    "role": mr.role,
                    "content": mr.content,
                    "thinking": getattr(mr, "thinking", "") or "",
                    "message_id": getattr(mr, "message_id", "") or "",
                    "stream_completed": getattr(mr, "stream_completed", True),
                    "stream_buffer": getattr(mr, "stream_buffer", "") or "",
                    "images": getattr(mr, "images", []) or [],
                    "tool_summary": getattr(mr, "tool_summary", "") or "",
                    "step_summary": getattr(mr, "step_summary", "") or "",
                    "clarification_data": getattr(mr, "clarification_data", {}) or {},
                    "timestamp": mr.created_at,
                }
                for mr in msg_rows
            ],
            "mid_term_summary": row.mid_term_summary,
            "status": getattr(row, "status", "active") or "active",
        }


async def db_list_conversations(client_id: str = "") -> list[dict]:
    """从 DB 直接读取对话列表（跨 worker 一致性）。"""
    async with AsyncSessionLocal() as session:
        query = select(ConversationModel).order_by(ConversationModel.updated_at.desc())
        if client_id:
            from sqlalchemy import or_
            query = query.where(
                or_(ConversationModel.client_id == client_id, ConversationModel.client_id == "")
            )
        result = await session.execute(query)
        rows = result.scalars().all()

    return [
        {"id": r.id, "title": r.title, "updated_at": r.updated_at}
        for r in rows
    ]


# ── 初始化 ────────────────────────────────────────────────────────────────────

async def init() -> None:
    """应用启动时调用：从 PostgreSQL 加载全部对话到内存缓存。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ConversationModel))
        conv_rows = result.scalars().all()

        for row in conv_rows:
            msgs_result = await session.execute(
                select(MessageModel)
                .where(MessageModel.conv_id == row.id)
                .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
            )
            msg_rows = msgs_result.scalars().all()
            messages = [
                Message(
                    role=mr.role,
                    content=mr.content,
                    timestamp=mr.created_at,
                    id=mr.id,
                    tool_summary=getattr(mr, "tool_summary", "") or "",
                    step_summary=getattr(mr, "step_summary", "") or "",
                )
                for mr in msg_rows
            ]
            conv = Conversation(
                id=row.id,
                title=row.title,
                system_prompt=row.system_prompt,
                messages=messages,
                mid_term_summary=row.mid_term_summary,
                mid_term_cursor=row.mid_term_cursor,
                created_at=row.created_at,
                updated_at=row.updated_at,
                client_id=row.client_id,
                status=getattr(row, "status", "active") or "active",
            )
            _store[row.id] = conv

    logger.info("对话存储初始化完成，共加载 %d 个对话", len(_store))


# ── CRUD（异步写操作）─────────────────────────────────────────────────────────

async def create(
    conv_id: str,
    title: str = "新对话",
    system_prompt: str = "",
    client_id: str = "",
) -> Conversation:
    """创建新对话：写入 DB + 更新缓存。"""
    prompt = system_prompt.strip() or DEFAULT_SYSTEM_PROMPT
    now = time.time()
    conv = Conversation(
        id=conv_id,
        title=title,
        system_prompt=prompt,
        client_id=client_id,
        created_at=now,
        updated_at=now,
    )
    _store[conv_id] = conv

    async with AsyncSessionLocal() as session:
        session.add(ConversationModel(
            id=conv.id,
            title=conv.title,
            system_prompt=conv.system_prompt,
            mid_term_summary="",
            mid_term_cursor=0,
            client_id=conv.client_id,
            status="active",
            created_at=now,
            updated_at=now,
        ))
        await session.commit()

    return conv


async def save(conv: Conversation) -> None:
    """更新对话元数据（title / system_prompt / mid_term_summary / mid_term_cursor）。
    注意：不负责 messages，messages 通过 add_message 单独写入。"""
    conv.updated_at = time.time()
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_update(ConversationModel)
            .where(ConversationModel.id == conv.id)
            .values(
                title=conv.title,
                system_prompt=conv.system_prompt,
                mid_term_summary=conv.mid_term_summary,
                mid_term_cursor=conv.mid_term_cursor,
                updated_at=conv.updated_at,
            )
        )
        await session.commit()


async def delete(conv_id: str) -> None:
    """删除对话：从缓存和 DB 中删除（messages / tool_events 级联删除）。"""
    _store.pop(conv_id, None)
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_delete(ConversationModel).where(ConversationModel.id == conv_id)
        )
        await session.commit()


async def add_message(
    conv_id: str, role: str, content: str, update_db_id: int = 0,
    tool_summary: str = "", step_summary: str = "",
) -> None:
    """
    追加一条消息：写入 DB + 更新缓存。

    update_db_id > 0 时：UPDATE 已有行（StreamSession 预写的消息），不 INSERT 新行。
    update_db_id = 0 时：INSERT 新行（传统行为）。

    tool_summary / step_summary：工具调用记录和多步执行摘要，
    存入独立 DB 字段，不混入 content。
    """
    conv = _store.get(conv_id)
    if not conv:
        return

    now = time.time()
    new_title = conv.title
    if conv.title == "新对话" and role == "user":
        new_title = content[:30] + ("..." if len(content) > 30 else "")

    msg_db_id = update_db_id

    async with AsyncSessionLocal() as session:
        if update_db_id > 0:
            # UPDATE 已有行（StreamSession 在流开始时预写了 DB 行）
            values: dict = {
                "content": content,
                "stream_completed": True,
                "stream_buffer": "",
            }
            if tool_summary:
                values["tool_summary"] = tool_summary
            if step_summary:
                values["step_summary"] = step_summary
            await session.execute(
                sa_update(MessageModel)
                .where(MessageModel.id == update_db_id)
                .values(**values)
            )
        else:
            # INSERT 新行
            msg_row = MessageModel(
                conv_id=conv_id, role=role, content=content,
                tool_summary=tool_summary, step_summary=step_summary,
                created_at=now,
            )
            session.add(msg_row)
            await session.flush()
            msg_db_id = msg_row.id

        await session.execute(
            sa_update(ConversationModel)
            .where(ConversationModel.id == conv_id)
            .values(updated_at=now, title=new_title)
        )
        await session.commit()

    # 追加到内存缓存
    msg = Message(
        role=role, content=content, timestamp=now, id=msg_db_id,
        tool_summary=tool_summary, step_summary=step_summary,
    )
    conv.messages.append(msg)
    conv.updated_at = now
    conv.title = new_title


async def update_status(conv_id: str, status: str) -> None:
    """
    更新对话状态，经过状态机校验。

    非法转换只记录警告，不阻断主流程（避免因状态不一致导致对话卡死）。
    """
    from db.state_machine import ConversationStatus, validate_conv_transition

    target = ConversationStatus(status)
    conv = _store.get(conv_id)
    if conv:
        validate_conv_transition(conv.status, target)
        conv.status = target.value
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_update(ConversationModel)
            .where(ConversationModel.id == conv_id)
            .values(status=target.value, updated_at=time.time())
        )
        await session.commit()


async def create_message_immediate(
    conv_id: str, role: str, content: str, message_id: str = "",
    thinking: str = "", images: list | None = None, stream_completed: bool = True,
) -> int:
    """
    立即写入消息到 DB（仅 DB，不写内存缓存）。返回 DB 自增 ID。

    重要：不更新 conv.messages 内存缓存！
    因为图执行期间会读取 conv.messages 构建 LLM 上下文，
    如果提前把当前轮的 user/assistant 加进去，会破坏
    tool_call → tool_result 的消息配对顺序，导致 MiniMax 等 API 报错。
    内存缓存由 save_response_node 在图执行完成后统一更新。
    """
    conv = _store.get(conv_id)
    now = time.time()
    seq = len(conv.messages) if conv else 0

    new_title = None
    if conv and conv.title == "新对话" and role == "user":
        new_title = content[:30] + ("..." if len(content) > 30 else "")

    async with AsyncSessionLocal() as session:
        msg_row = MessageModel(
            conv_id=conv_id, role=role, content=content,
            message_id=message_id, thinking=thinking,
            stream_completed=stream_completed,
            sequence_number=seq,
            images=images or [],
            created_at=now,
        )
        session.add(msg_row)
        await session.flush()
        db_id = msg_row.id

        update_vals = {"updated_at": now}
        if new_title:
            update_vals["title"] = new_title
        await session.execute(
            sa_update(ConversationModel)
            .where(ConversationModel.id == conv_id)
            .values(**update_vals)
        )
        await session.commit()

    # 只更新标题到缓存（不追加消息）
    if conv and new_title:
        conv.title = new_title

    return db_id


async def update_message_streaming(
    msg_db_id: int,
    thinking: str | None = None,
    stream_buffer: str | None = None,
    stream_completed: bool | None = None,
) -> None:
    """
    更新正在流式生成的消息（定期刷新 thinking/buffer）。

    参数语义：None = 不更新该字段；"" = 显式清空。
    """
    values: dict = {}
    if stream_completed is not None:
        values["stream_completed"] = stream_completed
    if thinking is not None:
        values["thinking"] = thinking
    if stream_buffer is not None:
        values["stream_buffer"] = stream_buffer
    if not values:
        return
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_update(MessageModel)
            .where(MessageModel.id == msg_db_id)
            .values(**values)
        )
        await session.commit()


async def finalize_message(
    msg_db_id: int, content: str, thinking: str = "",
) -> None:
    """消息生成完成：写入最终 content，标记 stream_completed=True，清空 buffer。"""
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_update(MessageModel)
            .where(MessageModel.id == msg_db_id)
            .values(
                content=content,
                thinking=thinking,
                stream_buffer="",
                stream_completed=True,
            )
        )
        await session.commit()

    # 更新内存缓存中的 content
    # (找到对应消息并更新，但不强依赖)
    for conv in _store.values():
        for msg in conv.messages:
            if msg.id == msg_db_id:
                msg.content = content
                return


async def clear_message_summaries(msg_id: int) -> None:
    """清空消息的 tool_summary 和 step_summary（压缩后不再需要）。"""
    if msg_id <= 0:
        return
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_update(MessageModel)
            .where(MessageModel.id == msg_id)
            .values(tool_summary="", step_summary="")
        )
        await session.commit()


async def update_message_content(msg_id: int, new_content: str) -> None:
    """更新指定消息内容（压缩时将工具调用记录替换为 [old tools call] 占位符）。"""
    if msg_id <= 0:
        return
    async with AsyncSessionLocal() as session:
        await session.execute(
            sa_update(MessageModel)
            .where(MessageModel.id == msg_id)
            .values(content=new_content)
        )
        await session.commit()
