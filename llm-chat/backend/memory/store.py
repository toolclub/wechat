"""
对话存储层 — DB-first 面向对象设计

设计原则（与 spec.md 铁律对齐）：
  1. PostgreSQL 是唯一真相源 —— 不维护任何跨请求的内存缓存
  2. 所有方法都是 async —— 杜绝"在同步函数中 await"的反模式（铁律 #5）
  3. 单一职责 —— ConversationStore 封装所有对话/消息的持久化操作
  4. 依赖注入 —— session_factory 通过构造函数传入，便于测试与 mock
  5. 可扩展 —— 新增字段在 _row_to_conversation / _row_to_dict 集中映射；
              新增持久化操作在本类中加 async 方法，禁止散落在调用方
  6. 流式心跳 DB 化 —— heartbeat()/is_streaming() 用 conversations.last_heartbeat_at
     替代旧的 Redis chatflow:streaming:{conv_id} key，刷新与跨 worker 一致

向后兼容：
  模块底部仍暴露 `get` / `create` / `add_message` 等模块级 async 函数，
  供老代码 `from memory import store as memory_store; await memory_store.get(...)` 调用。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import select, update as sa_update, delete as sa_delete, or_

from db.database import AsyncSessionLocal
from db.models import ConversationModel, MessageModel
from memory.schema import Conversation, Message
from config import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger("memory.store")


# 流式心跳超时阈值：last_heartbeat_at 早于 (now - STREAM_STALE_AFTER) 即视为失活
STREAM_STALE_AFTER = 30.0


class ConversationStore:
    """
    对话与消息的持久化门面。

    所有读写操作都直接命中 PostgreSQL，没有跨请求的内存缓存：
      - 之前的 _store dict 被废除（曾经引发缓存中毒 / 跨 worker 不一致）
      - DB 是 source-of-truth，刷新页面或切换 worker 始终能看到最新数据

    扩展方式：
      - 新增 conversations 字段：
          1. db/models.py 加列
          2. db/migrate.py 加 ALTER
          3. 本类 _row_to_conversation / _row_to_dict 加映射
          4. 如果是写字段，加一个专门的 async 方法（例：update_status, heartbeat）
      - 新增持久化操作：直接在本类加方法，禁止在外面写散装 SQL
    """

    def __init__(self, session_factory=AsyncSessionLocal) -> None:
        self._session_factory = session_factory

    # ══════════════════════════════════════════════════════════════════════════
    # 行 → 业务对象映射（集中维护，新增字段只改这里）
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _row_to_message(row: MessageModel) -> Message:
        return Message(
            role=row.role,
            content=row.content,
            timestamp=row.created_at,
            id=row.id,
            tool_summary=getattr(row, "tool_summary", "") or "",
            step_summary=getattr(row, "step_summary", "") or "",
        )

    @staticmethod
    def _msg_row_to_dict(row: MessageModel) -> dict:
        return {
            "role": row.role,
            "content": row.content,
            "thinking": getattr(row, "thinking", "") or "",
            "message_id": getattr(row, "message_id", "") or "",
            "stream_completed": getattr(row, "stream_completed", True),
            "stream_buffer": getattr(row, "stream_buffer", "") or "",
            "images": getattr(row, "images", []) or [],
            "tool_summary": getattr(row, "tool_summary", "") or "",
            "step_summary": getattr(row, "step_summary", "") or "",
            "clarification_data": getattr(row, "clarification_data", {}) or {},
            "timestamp": row.created_at,
        }

    @classmethod
    def _row_to_conversation(
        cls, row: ConversationModel, msg_rows: list[MessageModel]
    ) -> Conversation:
        return Conversation(
            id=row.id,
            title=row.title,
            system_prompt=row.system_prompt,
            messages=[cls._row_to_message(m) for m in msg_rows],
            mid_term_summary=row.mid_term_summary,
            mid_term_cursor=row.mid_term_cursor,
            created_at=row.created_at,
            updated_at=row.updated_at,
            client_id=row.client_id,
            status=getattr(row, "status", "active") or "active",
        )

    @classmethod
    def _row_to_dict(
        cls, row: ConversationModel, msg_rows: list[MessageModel]
    ) -> dict:
        return {
            "id": row.id,
            "title": row.title,
            "system_prompt": row.system_prompt,
            "messages": [cls._msg_row_to_dict(m) for m in msg_rows],
            "mid_term_summary": row.mid_term_summary,
            "status": getattr(row, "status", "active") or "active",
            "last_heartbeat_at": getattr(row, "last_heartbeat_at", 0.0) or 0.0,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # 读 — 对话
    # ══════════════════════════════════════════════════════════════════════════

    async def get(self, conv_id: str) -> Optional[Conversation]:
        """加载对话与全部消息（图节点用，需要 messages 列表参与上下文构建）。"""
        async with self._session_factory() as session:
            row = await session.get(ConversationModel, conv_id)
            if not row:
                return None
            msg_rows = await self._fetch_messages(session, conv_id)
            return self._row_to_conversation(row, msg_rows)

    async def get_meta(self, conv_id: str) -> Optional[Conversation]:
        """
        只加载对话主表，不加载 messages（messages=[]）。

        用于只需要 system_prompt / client_id / status 等元数据的调用方
        （例：cache 命名空间派生、call_model 选 system prompt），
        避免每次都全量拉 messages。
        """
        async with self._session_factory() as session:
            row = await session.get(ConversationModel, conv_id)
            if not row:
                return None
            return self._row_to_conversation(row, [])

    async def get_dict(self, conv_id: str) -> Optional[dict]:
        """返回 dict 形态（API 端点直接序列化为 JSON 用）。"""
        async with self._session_factory() as session:
            row = await session.get(ConversationModel, conv_id)
            if not row:
                return None
            msg_rows = await self._fetch_messages(session, conv_id)
            return self._row_to_dict(row, msg_rows)

    async def list_for_client(self, client_id: str = "") -> list[dict]:
        """列出指定 client 的对话（仅元数据，不含 messages）。"""
        async with self._session_factory() as session:
            query = select(ConversationModel).order_by(
                ConversationModel.updated_at.desc()
            )
            if client_id:
                query = query.where(
                    or_(
                        ConversationModel.client_id == client_id,
                        ConversationModel.client_id == "",
                    )
                )
            result = await session.execute(query)
            rows = result.scalars().all()

        return [
            {"id": r.id, "title": r.title, "updated_at": r.updated_at}
            for r in rows
        ]

    @staticmethod
    async def _fetch_messages(session, conv_id: str) -> list[MessageModel]:
        result = await session.execute(
            select(MessageModel)
            .where(MessageModel.conv_id == conv_id)
            .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
        )
        return list(result.scalars().all())

    # ══════════════════════════════════════════════════════════════════════════
    # 写 — 对话
    # ══════════════════════════════════════════════════════════════════════════

    async def create(
        self,
        conv_id: str,
        title: str = "新对话",
        system_prompt: str = "",
        client_id: str = "",
    ) -> Conversation:
        """创建新对话。"""
        prompt = system_prompt.strip() or DEFAULT_SYSTEM_PROMPT
        now = time.time()
        async with self._session_factory() as session:
            session.add(
                ConversationModel(
                    id=conv_id,
                    title=title,
                    system_prompt=prompt,
                    mid_term_summary="",
                    mid_term_cursor=0,
                    client_id=client_id,
                    status="active",
                    last_heartbeat_at=0.0,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        return Conversation(
            id=conv_id,
            title=title,
            system_prompt=prompt,
            client_id=client_id,
            created_at=now,
            updated_at=now,
        )

    async def save(self, conv: Conversation) -> None:
        """
        更新对话元数据（title / system_prompt / mid_term_summary / mid_term_cursor）。

        注意：本方法不写 messages，messages 由 add_message / create_message_immediate
        / finalize_message 等专门方法负责。
        """
        conv.updated_at = time.time()
        async with self._session_factory() as session:
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

    async def delete(self, conv_id: str) -> None:
        """删除对话（messages / tool_executions / event_log 由 FK CASCADE 删除）。"""
        async with self._session_factory() as session:
            await session.execute(
                sa_delete(ConversationModel).where(ConversationModel.id == conv_id)
            )
            await session.commit()

    async def update_status(self, conv_id: str, status: str) -> None:
        """
        持久化对话状态。

        状态合法性由调用方的 ConversationSM 保证（铁律 #7：状态变更必须走状态机）。
        本函数只做持久化，不做校验。
        """
        async with self._session_factory() as session:
            await session.execute(
                sa_update(ConversationModel)
                .where(ConversationModel.id == conv_id)
                .values(status=status, updated_at=time.time())
            )
            await session.commit()

    # ══════════════════════════════════════════════════════════════════════════
    # 流式心跳 — DB 驱动的活跃检测
    # ══════════════════════════════════════════════════════════════════════════

    async def heartbeat(self, conv_id: str) -> None:
        """
        流式生成期间的心跳（每 3s 调一次）。

        写入 last_heartbeat_at = now()。配合 is_streaming() 判定 worker 崩溃后的
        僵尸 status='streaming'：超过 STREAM_STALE_AFTER 秒未心跳即视为失活。
        """
        async with self._session_factory() as session:
            await session.execute(
                sa_update(ConversationModel)
                .where(ConversationModel.id == conv_id)
                .values(last_heartbeat_at=time.time())
            )
            await session.commit()

    async def is_streaming(
        self, conv_id: str, stale_after: float = STREAM_STALE_AFTER
    ) -> bool:
        """
        判断对话是否正在流式生成（DB 驱动，跨 worker 一致）。

        判定条件：status='streaming' AND now - last_heartbeat_at < stale_after

        worker 崩溃后 last_heartbeat_at 不再更新，超过阈值后 is_streaming 自动
        返回 False，前端不会一直看到"生成中"的僵尸状态。
        """
        async with self._session_factory() as session:
            row = await session.get(ConversationModel, conv_id)
            if not row:
                return False
            if (getattr(row, "status", "") or "") != "streaming":
                return False
            last_hb = getattr(row, "last_heartbeat_at", 0.0) or 0.0
            return (time.time() - last_hb) < stale_after

    # ══════════════════════════════════════════════════════════════════════════
    # 写 — 消息
    # ══════════════════════════════════════════════════════════════════════════

    async def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        update_db_id: int = 0,
        tool_summary: str = "",
        step_summary: str = "",
    ) -> None:
        """
        追加或更新消息。

        update_db_id > 0：UPDATE 已有行（StreamSession 预写的消息）
        update_db_id = 0：INSERT 新行

        tool_summary / step_summary 写入独立字段，不混入 content（铁律 #2）。
        """
        now = time.time()
        new_title: str | None = None

        async with self._session_factory() as session:
            # 计算新标题（首条 user 消息触发更名）
            if role == "user":
                conv_row = await session.get(ConversationModel, conv_id)
                if conv_row is None:
                    logger.warning(
                        "add_message 跳过：对话 %s 不存在（可能已删除）", conv_id
                    )
                    return
                if conv_row.title == "新对话":
                    new_title = content[:30] + ("..." if len(content) > 30 else "")
            else:
                # 非 user 消息也要确认对话存在
                exists = await session.get(ConversationModel, conv_id)
                if exists is None:
                    logger.warning(
                        "add_message 跳过：对话 %s 不存在（可能已删除）", conv_id
                    )
                    return

            if update_db_id > 0:
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
                session.add(
                    MessageModel(
                        conv_id=conv_id,
                        role=role,
                        content=content,
                        tool_summary=tool_summary,
                        step_summary=step_summary,
                        created_at=now,
                    )
                )

            conv_update: dict = {"updated_at": now}
            if new_title:
                conv_update["title"] = new_title
            await session.execute(
                sa_update(ConversationModel)
                .where(ConversationModel.id == conv_id)
                .values(**conv_update)
            )
            await session.commit()

    async def create_message_immediate(
        self,
        conv_id: str,
        role: str,
        content: str,
        message_id: str = "",
        thinking: str = "",
        images: list | None = None,
        stream_completed: bool = True,
    ) -> int:
        """
        立即写入消息到 DB，返回自增 ID。

        StreamSession 在流开始时用此方法预写 user/assistant 行，
        后续通过 update_message_streaming / finalize_message 增量更新同一行。

        sequence_number 由 DB 现存消息数推算（不依赖任何内存缓存）。
        """
        now = time.time()
        new_title: str | None = None

        async with self._session_factory() as session:
            # 用 DB 现有消息数作为 sequence_number（之前依赖 _store 内存缓存，已废除）
            from sqlalchemy import func

            count_result = await session.execute(
                select(func.count(MessageModel.id)).where(
                    MessageModel.conv_id == conv_id
                )
            )
            seq = int(count_result.scalar() or 0)

            if role == "user":
                conv_row = await session.get(ConversationModel, conv_id)
                if conv_row and conv_row.title == "新对话":
                    new_title = content[:30] + ("..." if len(content) > 30 else "")

            msg_row = MessageModel(
                conv_id=conv_id,
                role=role,
                content=content,
                message_id=message_id,
                thinking=thinking,
                stream_completed=stream_completed,
                sequence_number=seq,
                images=images or [],
                created_at=now,
            )
            session.add(msg_row)
            await session.flush()
            db_id = msg_row.id

            update_vals: dict = {"updated_at": now}
            if new_title:
                update_vals["title"] = new_title
            await session.execute(
                sa_update(ConversationModel)
                .where(ConversationModel.id == conv_id)
                .values(**update_vals)
            )
            await session.commit()

        return db_id

    async def update_message_streaming(
        self,
        msg_db_id: int,
        thinking: str | None = None,
        stream_buffer: str | None = None,
        stream_completed: bool | None = None,
    ) -> None:
        """
        增量更新流式生成中的消息。

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

        async with self._session_factory() as session:
            await session.execute(
                sa_update(MessageModel)
                .where(MessageModel.id == msg_db_id)
                .values(**values)
            )
            await session.commit()

    async def finalize_message(
        self, msg_db_id: int, content: str, thinking: str = ""
    ) -> None:
        """消息最终化：写入完整 content，标记 stream_completed=True，清空 buffer。"""
        async with self._session_factory() as session:
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

    async def clear_message_summaries(self, msg_id: int) -> None:
        """压缩后清空 tool_summary / step_summary（减少后续上下文窗口噪音）。"""
        if msg_id <= 0:
            return
        async with self._session_factory() as session:
            await session.execute(
                sa_update(MessageModel)
                .where(MessageModel.id == msg_id)
                .values(tool_summary="", step_summary="")
            )
            await session.commit()

    async def update_message_content(self, msg_id: int, new_content: str) -> None:
        """更新指定消息内容（压缩时把工具调用记录替换为 [old tools call] 占位符）。"""
        if msg_id <= 0:
            return
        async with self._session_factory() as session:
            await session.execute(
                sa_update(MessageModel)
                .where(MessageModel.id == msg_id)
                .values(content=new_content)
            )
            await session.commit()


# ══════════════════════════════════════════════════════════════════════════════
# 单例 + 模块级 async 包装（向后兼容 `from memory import store as memory_store`）
# ══════════════════════════════════════════════════════════════════════════════

_default_store: ConversationStore | None = None


def get_store() -> ConversationStore:
    """获取默认 ConversationStore 单例。"""
    global _default_store
    if _default_store is None:
        _default_store = ConversationStore()
    return _default_store


async def init() -> None:
    """
    应用启动钩子。

    DB-first 设计下不再做任何内存预加载（旧版本会一次性把所有 conversations
    灌入 _store dict，新建对话在跨 worker 时永远看不到 → 已废除）。
    保留此函数仅为兼容 main.py 的 lifespan 启动调用。
    """
    get_store()  # 触发单例创建
    logger.info("ConversationStore 初始化完成（DB-first，无内存缓存）")


# ── 读 ────────────────────────────────────────────────────────────────────────

async def get(conv_id: str) -> Optional[Conversation]:
    return await get_store().get(conv_id)


async def get_meta(conv_id: str) -> Optional[Conversation]:
    return await get_store().get_meta(conv_id)


async def db_get_conversation(conv_id: str) -> Optional[dict]:
    """供 API 端点序列化为 JSON 的 dict 形态读取。"""
    return await get_store().get_dict(conv_id)


async def db_list_conversations(client_id: str = "") -> list[dict]:
    return await get_store().list_for_client(client_id)


# ── 写 — 对话 ─────────────────────────────────────────────────────────────────

async def create(
    conv_id: str,
    title: str = "新对话",
    system_prompt: str = "",
    client_id: str = "",
) -> Conversation:
    return await get_store().create(conv_id, title, system_prompt, client_id)


async def save(conv: Conversation) -> None:
    await get_store().save(conv)


async def delete(conv_id: str) -> None:
    await get_store().delete(conv_id)


async def update_status(conv_id: str, status: str) -> None:
    await get_store().update_status(conv_id, status)


# ── 流式心跳 ──────────────────────────────────────────────────────────────────

async def heartbeat(conv_id: str) -> None:
    await get_store().heartbeat(conv_id)


async def is_streaming(conv_id: str, stale_after: float = STREAM_STALE_AFTER) -> bool:
    return await get_store().is_streaming(conv_id, stale_after)


# ── 写 — 消息 ─────────────────────────────────────────────────────────────────

async def add_message(
    conv_id: str,
    role: str,
    content: str,
    update_db_id: int = 0,
    tool_summary: str = "",
    step_summary: str = "",
) -> None:
    await get_store().add_message(
        conv_id, role, content, update_db_id, tool_summary, step_summary
    )


async def create_message_immediate(
    conv_id: str,
    role: str,
    content: str,
    message_id: str = "",
    thinking: str = "",
    images: list | None = None,
    stream_completed: bool = True,
) -> int:
    return await get_store().create_message_immediate(
        conv_id, role, content, message_id, thinking, images, stream_completed
    )


async def update_message_streaming(
    msg_db_id: int,
    thinking: str | None = None,
    stream_buffer: str | None = None,
    stream_completed: bool | None = None,
) -> None:
    await get_store().update_message_streaming(
        msg_db_id, thinking, stream_buffer, stream_completed
    )


async def finalize_message(
    msg_db_id: int, content: str, thinking: str = ""
) -> None:
    await get_store().finalize_message(msg_db_id, content, thinking)


async def clear_message_summaries(msg_id: int) -> None:
    await get_store().clear_message_summaries(msg_id)


async def update_message_content(msg_id: int, new_content: str) -> None:
    await get_store().update_message_content(msg_id, new_content)
