"""
chat 路由：流式对话 / 停止 / 恢复

═══════════════════════════════════════════════════════════════════════════════
路由一览
═══════════════════════════════════════════════════════════════════════════════

  POST /api/chat                           —— 发起流式对话（SSE）
  POST /api/chat/{conv_id}/stop            —— 停止某对话的流式输出
  GET  /api/conversations/{conv_id}/resume —— 刷新后从 event_log 恢复流

═══════════════════════════════════════════════════════════════════════════════
StopEventRegistry —— 本 worker 内 stop_event 的 OO 封装
═══════════════════════════════════════════════════════════════════════════════

原 main.py 用模块级 `_stop_events: dict[str, asyncio.Event]` 裸字典管理每条
对话的 stop 信号，存在两个问题：

  1. 对象封装性差：register / set / remove 三个动作散落在路由函数里，语义
     不集中。拆路由后想复用这套逻辑就要再次 `from api.chat import _stop_events`
     触碰下划线私有名。
  2. 清理竞态：finally 里 `_stop_events.pop(conv_id)` 可能把同 conv_id 下
     已经换上去的新 stop_event 误删掉。需要身份比对（identity check）才能
     避免，但裸 dict 没有强制约束。

本类借鉴 StreamSessionRegistry 的 `remove_if` 身份比对模式，把生命周期管理
统一成 "acquire → set → release(identity)" 三个语义方法。

与 StreamSessionRegistry 的分工：

  - StreamSessionRegistry : 管 StreamSession 对象本身（能 cancel 图任务）
  - StopEventRegistry     : 管 asyncio.Event 停止信号（被图循环检查）

两者在停止链路上协同：前者硬取消已阻塞的协程，后者让每个 step 自愿退出。
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from config import CHAT_MODEL
from graph import runner as graph_runner
from graph.runner.session_registry import get_session_registry
from memory import store as memory_store
from models import ChatRequest

logger = logging.getLogger("api.chat")

router = APIRouter(tags=["chat"])


# ═══════════════════════════════════════════════════════════════════════════════
# StopEventRegistry
# ═══════════════════════════════════════════════════════════════════════════════


class StopEventRegistry:
    """
    本 worker 内 conv_id → asyncio.Event 的注册表。

    每个正在流式输出的对话关联一个 stop_event。模型推理循环、心跳任务等都
    会 await 这个事件的 is_set()，被主动停止时能立刻退出。

    注意跨 worker 停止走 Redis（db.redis_state.publish_stop），本类只管当前
    worker 的本地事件对象。三位一体的停止机制见 session_registry.py 的模块
    docstring。
    """

    def __init__(self) -> None:
        # conv_id → 当前活跃的 stop_event
        # 同一 conv_id 在短时间内可能被不同轮次覆盖（前端连续发两次请求），
        # 需要 release() 做身份比对来防止误删。
        self._events: dict[str, asyncio.Event] = {}

    def acquire(self, conv_id: str) -> asyncio.Event:
        """
        为 conv_id 注册一个全新的 stop_event 并返回。

        若已有旧 event 会先把它置位（通知旧轮退出），再挂上新的 event。
        返回值必须由调用方在 finally 里通过 `release(conv_id, event)` 清理。
        """
        old = self._events.get(conv_id)
        if old is not None:
            # 让旧轮能从 wait() 中醒来并退出
            old.set()

        event = asyncio.Event()
        self._events[conv_id] = event
        return event

    def signal_stop(self, conv_id: str) -> bool:
        """
        触发 conv_id 的 stop_event（不删除映射，由 chat() 的 finally 清理）。

        返回 True 表示本 worker 内找到并置位了事件；False 表示会话不在本
        worker（此时调用方一般还要通过 Redis 广播给其他 worker）。
        """
        event = self._events.get(conv_id)
        if event is None:
            return False
        if not event.is_set():
            event.set()
        return True

    def release(self, conv_id: str, event: asyncio.Event) -> None:
        """
        条件式注销：只在注册表里存的还是传入的 event 实例时才删除。

        身份比对是为了防止下列竞态：
            t0  chat()#A 注册 event_A
            t1  chat()#B 覆盖注册 event_B（A 的流被停止）
            t2  chat()#A 的 finally 跑 release → 不能把 event_B 误删
        """
        if self._events.get(conv_id) is event:
            self._events.pop(conv_id, None)


# 模块级单例（懒初始化）—— 所有路由共享同一个注册表
_stop_registry: StopEventRegistry | None = None


def get_stop_registry() -> StopEventRegistry:
    """返回 StopEventRegistry 的进程内唯一实例。"""
    global _stop_registry
    if _stop_registry is None:
        _stop_registry = StopEventRegistry()
    return _stop_registry


def reset_stop_registry() -> None:
    """仅供测试：重置单例。"""
    global _stop_registry
    _stop_registry = None


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助：跨 worker 停止广播
# ═══════════════════════════════════════════════════════════════════════════════


async def _publish_stop_safely(conv_id: str) -> None:
    """
    通过 Redis 广播停止信号给所有 worker。失败不致命，但要落日志（铁律 #9）。
    """
    try:
        from db.redis_state import publish_stop
        await publish_stop(conv_id)
    except Exception as exc:
        logger.warning("Redis publish_stop 失败 conv=%s: %s", conv_id, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    """
    流式对话接口（SSE）。

    SSE 事件格式：
      data: {"content": "..."}                 ← 增量 token
      data: {"tool_call": {...}}                ← 工具调用
      data: {"search_item": {...}}              ← 单条搜索结果（实时追加）
      data: {"tool_result": {...}}              ← 工具完成信号
      data: {"done": true, "compressed": bool}  ← 完成信号
      data: {"stopped": true}                   ← 用户主动停止
    """
    client_id = request.headers.get("X-Client-ID", "")

    # ── 入口日志（确认请求已到达 Python 层，可排查 nginx/网络层丢包） ─────────
    img_bytes = sum(len(img) for img in req.images)
    logger.info(
        "POST /api/chat | conv=%s | client=%s | model=%s | msg_len=%d"
        " | images=%d | img_total_kb=%.1f",
        req.conversation_id,
        client_id[:8] if client_id else "-",
        req.model or CHAT_MODEL,
        len(req.message),
        len(req.images),
        img_bytes / 1024,
    )

    # 确认对话存在；不存在则创建。DB-first，无需预热缓存。
    conv = await memory_store.get_meta(req.conversation_id)
    if not conv:
        await memory_store.create(req.conversation_id, client_id=client_id)

    # ── 停止旧轮（跨 worker + 本 worker） ────────────────────────────────────
    # 1) 跨 worker：发布 Redis stop 信号，所有 worker 的心跳循环都能探测
    await _publish_stop_safely(req.conversation_id)
    # 2) 本 worker：通过注册表 cancel（内部同时 set stop_event + cancel task）
    get_session_registry().cancel(req.conversation_id)

    # ── 为本轮注册新的 stop_event（acquire 内部会把旧 event 先 set） ───────
    stop_registry = get_stop_registry()
    stop_event = stop_registry.acquire(req.conversation_id)

    async def safe_stream():
        try:
            async for chunk in graph_runner.stream_response(
                conv_id=req.conversation_id,
                user_message=req.message,
                model=req.model or CHAT_MODEL,
                temperature=req.temperature,
                client_id=client_id,
                images=req.images,
                agent_mode=req.agent_mode,
                force_plan=req.force_plan,
                stop_event=stop_event,
            ):
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            # 身份比对式 release，避免误删下一轮的 stop_event
            stop_registry.release(req.conversation_id, stop_event)

    return StreamingResponse(
        safe_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/chat/{conv_id}/stop")
async def stop_chat(conv_id: str):
    """主动停止某个会话的流式输出（本 worker + 跨 worker Redis）。"""
    # 1. 本 worker 停止：stop_event + 注册表 cancel（两条腿保险）
    get_stop_registry().signal_stop(conv_id)
    get_session_registry().cancel(conv_id)
    # 2. 跨 worker 停止（通过 Redis 通知其他 worker）
    await _publish_stop_safely(conv_id)
    return {"ok": True}


@router.get("/api/conversations/{conv_id}/resume")
async def resume_chat(
    conv_id: str,
    request: Request,
    after_event_id: int = 0,
    message_id: str = "",
):
    """
    恢复流式输出（SSE）— DB-first 版。

    从 event_log 表读取 after_event_id 之后的事件，然后切换到实时推送。
    跨 worker 安全。

    Args:
        after_event_id: 客户端已经消费过的最后一个 event_id，从该点后回放
        message_id: 可选，限定只回放指定 assistant message 的事件
            （多轮对话时避免混入旧轮）
    """
    from graph.runner.stream import resume_stream

    async def safe_resume():
        try:
            async for chunk in resume_stream(conv_id, after_event_id, message_id):
                if await request.is_disconnected():
                    break
                yield chunk
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        safe_resume(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
