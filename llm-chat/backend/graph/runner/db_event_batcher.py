"""
DBEventBatcher — SSE 事件批量持久化器（OO 拆分自 StreamSession）

═══════════════════════════════════════════════════════════════════════════════
职责
═══════════════════════════════════════════════════════════════════════════════

把 SSE 事件流和消息流缓冲落库，供刷新恢复使用。具体管两类缓冲：

  1. **event_log 批次** — 每个 SSE 帧追加一条记录到 event_log 表。批量写入
     减少 INSERT 次数。
  2. **messages 流式字段缓冲** — thinking / stream_buffer 是 LLM 增量 token，
     每来一个 token 都 UPDATE messages 太贵，因此先在内存累积，定期 flush。

═══════════════════════════════════════════════════════════════════════════════
为什么独立成类（拆 StreamSession 上帝对象）
═══════════════════════════════════════════════════════════════════════════════

原 StreamSession 700+ 行，一个类管图执行、SSE 推送、DB 批量、心跳、工具追
踪、停止检查、客户端 feed 共 7 类职责，违反 SRP。把"DB 批量缓冲 + 定期 flush"
单独抽出后：
  - StreamSession 不再持有 _event_batch / _thinking_buf / _content_buf 三个
    裸字段，而是组合一个 DBEventBatcher 实例
  - 单元测试可以独立验证 batcher 行为（mock event_store + mock memory_store）
  - 将来想换成 Postgres COPY 或 LISTEN/NOTIFY 推送，只改这一个类

═══════════════════════════════════════════════════════════════════════════════
锁与终态化
═══════════════════════════════════════════════════════════════════════════════

`_finalize_lock` 由 StreamSession 持有并传入。原因：消息终态化逻辑跨多个组件
（_finalize_message 写最终内容、_periodic_flush 写流式增量、_save_partial 写
中断响应），它们都要求"终态化后不再覆盖 messages 行"，因此共享同一把锁更安全。
batcher 只在 flush_message_buffers 内拿锁。

event_log 的写入 **不受** 终态化限制 —— done / stopped / error 事件本身就
发生在终态化之后，必须能落库（否则刷新恢复时缺最后一条事件）。所以代码里
event_log flush 在锁外，message buffer flush 在锁内。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("graph.runner.db_event_batcher")


class DBEventBatcher:
    """SSE 事件 + messages 流式字段的批量持久化缓冲。"""

    def __init__(
        self,
        conv_id: str,
        message_id: str,
        finalize_lock: asyncio.Lock,
        finalized_flag: list[bool],
    ) -> None:
        """
        Args:
            conv_id: 对话 ID（写入 event_log.conv_id）
            message_id: 当前 assistant 消息的业务 ID（写入 event_log.message_id）
            finalize_lock: 与 StreamSession 共享的终态化锁
            finalized_flag: 单元素 list 包装的 bool，作为 mutable 引用让
                StreamSession 和 Batcher 共享同一个"终态化与否"标志。
                用 list 而非裸 bool 是因为 Python 没有引用类型的 bool。
        """
        self.conv_id = conv_id
        self.message_id = message_id
        self._finalize_lock = finalize_lock
        self._finalized_flag = finalized_flag

        # event_log 批次：每条 SSE 帧一个 dict
        self._event_batch: list[dict] = []
        # messages 表的流式增量缓冲（thinking 和 content 分别累积）
        self._thinking_buf: str = ""
        self._content_buf: str = ""

        # assistant 消息在 messages 表中的自增主键（StreamSession 创建消息后回填）
        # 0 表示尚未持久化，flush_message_buffers 会跳过 UPDATE
        self.assistant_db_id: int = 0

    # ── 入队（生产者侧） ─────────────────────────────────────────────────────

    def enqueue_event(
        self,
        sse_string: str,
        event_type: str,
    ) -> None:
        """把一条 SSE 帧加入待写入 event_log 的批次。"""
        self._event_batch.append({
            "conv_id": self.conv_id,
            "message_id": self.message_id,
            "event_type": event_type,
            "sse_string": sse_string,
        })

    def append_thinking(self, text: str) -> None:
        """累积 thinking 增量（终态化前会被 flush 到 messages.thinking）。"""
        if text:
            self._thinking_buf += text

    def append_content(self, text: str) -> None:
        """累积 content 增量（终态化前会被 flush 到 messages.stream_buffer）。"""
        if text:
            self._content_buf += text

    @property
    def thinking_buffer(self) -> str:
        """当前累积的 thinking 文本（供 _finalize_message 写入最终字段时取用）。"""
        return self._thinking_buf

    # ── flush（消费者侧） ────────────────────────────────────────────────────

    async def flush_event_log(self) -> None:
        """
        把 event_log 批次刷新到 DB。

        独立成方法是为了在终态化场景下能精确控制：done/stopped/error 事件需要
        在写消息表之后再 flush，确保事件顺序正确。
        """
        if not self._event_batch:
            return
        batch = self._event_batch[:]
        self._event_batch.clear()
        try:
            from db.event_store import append_events_batch
            await append_events_batch(batch)
        except Exception as exc:
            # spec 铁律 #9：批量写失败要落日志，否则前端刷新看到事件断层无线索
            logger.warning("event_log 批量写入失败 conv=%s 批大小=%d: %s",
                           self.conv_id, len(batch), exc)

    async def flush_message_buffers(self) -> None:
        """
        把累积的 thinking/content 缓冲刷新到 messages 表。

        在终态化锁内执行，避免与 _finalize_message / _save_partial 竞态：
        终态化后再 flush 流式增量会覆盖最终内容（messages.content 被中间态
        污染）。
        """
        if not self.assistant_db_id:
            return
        if not (self._thinking_buf or self._content_buf):
            return

        async with self._finalize_lock:
            # 终态化后跳过：保护 messages.content 不被流式中间态覆盖
            if self._finalized_flag[0]:
                return
            try:
                from memory import store as memory_store
                await memory_store.update_message_streaming(
                    self.assistant_db_id,
                    thinking=self._thinking_buf if self._thinking_buf else None,
                    stream_buffer=self._content_buf if self._content_buf else None,
                )
            except Exception as exc:
                logger.warning("消息流式更新失败 conv=%s db_id=%s: %s",
                               self.conv_id, self.assistant_db_id, exc)

    async def flush_all(self) -> None:
        """一次性刷新 event_log + messages buffer。periodic flush 循环默认调它。"""
        await self.flush_event_log()
        await self.flush_message_buffers()
