"""
conversations 路由：对话 CRUD + 完整状态 + 流式状态

═══════════════════════════════════════════════════════════════════════════════
路由一览
═══════════════════════════════════════════════════════════════════════════════

  GET    /api/conversations                           —— 列出当前客户端对话
  POST   /api/conversations                           —— 创建对话
  GET    /api/conversations/{conv_id}                 —— 获取对话详情
  PATCH  /api/conversations/{conv_id}                 —— 更新 title / system_prompt
  DELETE /api/conversations/{conv_id}                 —— 删除对话（含 RAG 清理）
  GET    /api/conversations/{conv_id}/full-state      —— 刷新后恢复 UI 的完整状态
  GET    /api/conversations/{conv_id}/streaming-status —— 僵尸判定安全的流式状态

═══════════════════════════════════════════════════════════════════════════════
DB-first 原则
═══════════════════════════════════════════════════════════════════════════════

所有读接口都直接走 memory_store.db_* 方法（绕过进程内缓存），这是为了多
worker 一致性：worker A 刚写入的数据必须能在 worker B 立即读到，进程缓存
只能在单 worker 内保持一致，靠读 DB 才能跨 worker。
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Request

from config import LONGTERM_MEMORY_ENABLED
from memory import store as memory_store
from models import CreateConversationRequest, UpdateConversationRequest
from rag import retriever as rag_retriever

logger = logging.getLogger("api.conversations")

router = APIRouter(tags=["conversations"])


# ── 列表 / 创建 ──────────────────────────────────────────────────────────────

@router.get("/api/conversations")
async def list_conversations(request: Request):
    client_id = request.headers.get("X-Client-ID", "")
    convs = await memory_store.db_list_conversations(client_id)
    return {"conversations": convs}


@router.post("/api/conversations")
async def create_conversation(req: CreateConversationRequest, request: Request):
    client_id = request.headers.get("X-Client-ID", "")
    conv_id = str(uuid.uuid4())[:8]
    conv = await memory_store.create(
        conv_id=conv_id,
        title=req.title or "新对话",
        system_prompt=req.system_prompt or "",
        client_id=client_id,
    )
    return {"id": conv.id, "title": conv.title}


# ── 详情 / 更新 / 删除 ────────────────────────────────────────────────────────

@router.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    data = await memory_store.db_get_conversation(conv_id)
    if not data:
        return {"error": "对话不存在"}
    return data


@router.patch("/api/conversations/{conv_id}")
async def update_conversation(conv_id: str, req: UpdateConversationRequest):
    # 只需要修改 meta（title / system_prompt），不加载 messages
    conv = await memory_store.get_meta(conv_id)
    if not conv:
        return {"error": "对话不存在"}
    if req.title is not None:
        conv.title = req.title
    if req.system_prompt is not None:
        conv.system_prompt = req.system_prompt
    await memory_store.save(conv)
    return {"ok": True}


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    await memory_store.delete(conv_id)
    if LONGTERM_MEMORY_ENABLED:
        await rag_retriever.delete_by_conv(conv_id)
    return {"ok": True}


# ── 完整状态（刷新恢复专用） ──────────────────────────────────────────────────

@router.get("/api/conversations/{conv_id}/full-state")
async def get_full_state(conv_id: str):
    """
    获取对话的完整状态，供前端刷新后恢复 UI。

    返回：消息列表（含 thinking、tool_calls、steps 等结构化数据）、
    执行计划、文件产物、工具历史、流式状态。

    性能：4 张关联表并行加载（asyncio.gather），artifact 只拉元数据不拉
    content，避免大文件阻塞首屏。
    """
    from db.artifact_store import get_artifact_meta_list
    from db.event_store import get_latest_event_id
    from db.plan_store import get_latest_plan_for_conv
    from db.tool_store import get_tool_executions_for_conv

    # 直接从 DB 读取（跨 worker 一致性）
    conv_data = await memory_store.db_get_conversation(conv_id)
    if not conv_data:
        return {"error": "对话不存在"}

    # 并行加载所有关联数据
    tool_execs, latest_plan, artifacts, last_event_id = await asyncio.gather(
        get_tool_executions_for_conv(conv_id),
        get_latest_plan_for_conv(conv_id),
        get_artifact_meta_list(conv_id),
        get_latest_event_id(conv_id),
    )

    # 流式活跃判定：未完成消息存在 + 心跳新鲜（worker 没崩）
    # 单看 stream_completed=False 不够——崩溃的 worker 会留下永远 false 的僵尸消息
    has_incomplete_msg = any(
        not m.get("stream_completed", True)
        for m in conv_data["messages"]
        if m.get("role") == "assistant"
    )
    has_streaming = has_incomplete_msg and await memory_store.is_streaming(conv_id)

    # 按 message 组织 tool_executions 和 artifacts
    tool_by_msg: dict[str, list] = {}
    for t in tool_execs:
        tool_by_msg.setdefault(t["message_id"], []).append(t)

    artifact_by_msg: dict[str, list] = {}
    for a in artifacts:
        if a.get("message_id"):
            artifact_by_msg.setdefault(a["message_id"], []).append(a)

    # 组装消息（含 thinking + tool_executions + artifacts 元数据 + stream 状态）
    enriched_messages = []
    for m in conv_data["messages"]:
        msg = {**m}
        msg_id = m.get("message_id", "")
        if msg_id and msg_id in tool_by_msg:
            msg["tool_executions"] = tool_by_msg[msg_id]
        if msg_id and msg_id in artifact_by_msg:
            msg["artifacts"] = artifact_by_msg[msg_id]
        enriched_messages.append(msg)

    # 未关联到 message 的旧 artifact（兼容迁移前数据），只返回元数据
    orphan_artifacts = [a for a in artifacts if not a.get("message_id")]

    return {
        "id": conv_data["id"],
        "title": conv_data["title"],
        "status": conv_data.get("status", "active"),
        "messages": enriched_messages,
        "plan": latest_plan,
        "artifacts": orphan_artifacts,
        "has_streaming": has_streaming,
        "last_event_id": last_event_id,
    }


# ── 流式状态查询 ─────────────────────────────────────────────────────────────

@router.get("/api/conversations/{conv_id}/streaming-status")
async def get_streaming_status(conv_id: str):
    """
    检查对话是否有活跃的流式输出（DB-first，跨 worker 安全）。

    用 conversations.last_heartbeat_at 判定僵尸 streaming：
      status='streaming' AND now-last_heartbeat_at < 30s 才算真活跃。
    worker 崩溃后心跳停止更新，前端不会一直看到"生成中"的卡死状态。
    """
    from db.event_store import get_latest_event_id

    streaming = await memory_store.is_streaming(conv_id)
    last_eid = await get_latest_event_id(conv_id) if streaming else 0
    return {"streaming": streaming, "last_event_id": last_eid}
