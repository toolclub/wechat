"""
tools 路由：工具清单 + 对话工具调用历史

═══════════════════════════════════════════════════════════════════════════════
路由一览
═══════════════════════════════════════════════════════════════════════════════

  GET /api/tools                           —— 列出当前所有可用工具
  GET /api/conversations/{conv_id}/tools   —— 对话的工具调用历史（刷新恢复）

═══════════════════════════════════════════════════════════════════════════════
为什么两个路由放一个模块
═══════════════════════════════════════════════════════════════════════════════

两条路由都围绕"工具"这个领域对象展开，但读的是不同数据源：
  /api/tools                → 本进程注册的 BaseTool 实例列表（内置 + MCP）
  /api/conversations/.../tools → tool_events 表里的历史调用记录

放在一起符合 DDD 中"聚合根的所有查询放同一个 repository"的思路，前端也
习惯在同一个 namespace 下找工具相关的数据。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from memory.tool_events import get_tool_events
from tools import get_tools_info

logger = logging.getLogger("api.tools")

router = APIRouter(tags=["tools"])


@router.get("/api/tools")
async def list_tools():
    """列出当前所有可用工具（内置 + MCP + 动态注册）。"""
    return {"tools": get_tools_info()}


@router.get("/api/conversations/{conv_id}/tools")
async def get_conversation_tools(conv_id: str):
    """获取对话的工具调用历史（供前端刷新后复现"此会话经历了什么"）。"""
    events = await get_tool_events(conv_id)
    return {"events": events}
