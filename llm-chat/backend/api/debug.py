"""
debug 路由：辅助 / 调试 / 运行时状态查询

═══════════════════════════════════════════════════════════════════════════════
路由一览
═══════════════════════════════════════════════════════════════════════════════

  GET  /api/models                            —— Ollama 已下载模型列表
  POST /api/embedding                         —— 嵌入向量测试
  GET  /api/sandbox/status                    —— 沙箱集群健康状态
  GET  /api/conversations/{conv_id}/memory    —— 对话记忆调试（短/中/长期）
  GET  /api/conversations/{conv_id}/plan      —— 对话最新执行计划

═══════════════════════════════════════════════════════════════════════════════
为什么归在同一个 debug 模块
═══════════════════════════════════════════════════════════════════════════════

这 5 条路由都是"运维/开发"类，有两个共同点：
  1. 不属于用户主路径（chat / conversations / artifacts）
  2. 前端要么不用、要么只在设置面板 / 调试面板里用

放在同一个 router 下方便将来统一加一层 admin 认证（如果需要的话），
独立文件也避免污染主业务模块的 import 图。
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter

from config import (
    API_BASE_URL,
    CHAT_MODEL,
    EMBEDDING_MODEL,
    LONGTERM_MEMORY_ENABLED,
)
from memory import store as memory_store
from rag import retriever as rag_retriever
from tools import get_tool_names

logger = logging.getLogger("api.debug")

router = APIRouter(tags=["debug"])


# ── 模型列表 ─────────────────────────────────────────────────────────────────

@router.get("/api/models")
async def get_models():
    """列出 Ollama 中已下载的所有模型（过滤掉 embedding 模型）。"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{API_BASE_URL}/api/tags")
            data = resp.json()
            models = [
                m["name"] for m in data.get("models", [])
                if not m["name"].startswith(EMBEDDING_MODEL.split(":")[0])
            ]
    except Exception as exc:
        # spec 铁律 #9：失败不致命（Ollama 未启动时回退默认）但要落日志
        logger.warning("获取 Ollama 模型列表失败（已回退默认）: %s", exc)
        models = [CHAT_MODEL]
    return {"models": models}


# ── Embedding 测试 ───────────────────────────────────────────────────────────

@router.post("/api/embedding")
async def test_embedding(text: str = "测试文本"):
    """把一段文本送到 embedding 模型，返回维度和前 5 维预览（调试用）。"""
    from llm.embeddings import embed_text
    vec = await embed_text(text)
    return {
        "model": EMBEDDING_MODEL,
        "text": text,
        "dimensions": len(vec),
        "vector_preview": vec[:5],
    }


# ── 沙箱集群状态 ─────────────────────────────────────────────────────────────

@router.get("/api/sandbox/status")
async def sandbox_status():
    """查看沙箱 Worker 集群状态：健康数、session 分布、各节点状态。"""
    from config import SANDBOX_ENABLED
    if not SANDBOX_ENABLED:
        return {"enabled": False}
    from sandbox.manager import sandbox_manager
    return {"enabled": True, **sandbox_manager.status()}


# ── 对话记忆调试 ─────────────────────────────────────────────────────────────

@router.get("/api/conversations/{conv_id}/memory")
async def get_memory_debug(conv_id: str):
    """
    查看对话的三层记忆状态（短期窗口 / 中期摘要 / 长期 RAG），用于排查
    "AI 为什么记得/不记得某件事"。
    """
    conv = await memory_store.get(conv_id)
    if not conv:
        return {"error": "对话不存在"}

    lt_count = (
        await rag_retriever.count_by_conv(conv_id) if LONGTERM_MEMORY_ENABLED else -1
    )
    return {
        "total_messages": len(conv.messages),
        "summarised_count": conv.mid_term_cursor,
        "window_count": len(conv.messages) - conv.mid_term_cursor,
        "mid_term_summary": conv.mid_term_summary or "(空)",
        "long_term_stored_pairs": lt_count if LONGTERM_MEMORY_ENABLED else "(已禁用)",
        "active_tools": get_tool_names(),
    }


# ── 执行计划 ─────────────────────────────────────────────────────────────────

@router.get("/api/conversations/{conv_id}/plan")
async def get_conversation_plan(conv_id: str):
    """获取对话最新的执行计划（供前端刷新后恢复认知面板）。"""
    from db.plan_store import get_latest_plan_for_conv
    plan = await get_latest_plan_for_conv(conv_id)
    return {"plan": plan}
