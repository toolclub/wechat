"""
全局状态机定义 — 所有实体的状态枚举、合法转换、校验逻辑

设计原则：
  - 每个实体（对话/消息/工具执行）有且仅有一组状态枚举
  - 合法转换显式声明，非法转换抛异常
  - 所有状态写 DB 前必须经过校验
  - SSE 事件类型统一注册，不允许硬编码字符串

使用方式：
    from db.state_machine import ConversationStatus, transition_conversation
    transition_conversation(current="active", target=ConversationStatus.STREAMING)
"""
from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger("db.state_machine")


# ══════════════════════════════════════════════════════════════════════════════
# 对话状态机
# ══════════════════════════════════════════════════════════════════════════════

class ConversationStatus(str, Enum):
    """对话生命周期状态。继承 str 使 JSON 序列化和 DB 存储无需额外转换。"""
    ACTIVE = "active"           # 空闲，可接受新消息
    STREAMING = "streaming"     # 正在生成回复
    COMPLETED = "completed"     # 本轮生成完成
    ERROR = "error"             # 生成出错

    @classmethod
    def _missing_(cls, value: object) -> ConversationStatus | None:
        """兼容从 DB 读取的裸字符串。"""
        if isinstance(value, str):
            for member in cls:
                if member.value == value:
                    return member
        return None


# 合法转换表：key=当前状态，value=允许转到的状态集合
_CONV_TRANSITIONS: dict[ConversationStatus, set[ConversationStatus]] = {
    ConversationStatus.ACTIVE:    {ConversationStatus.STREAMING},
    ConversationStatus.STREAMING: {ConversationStatus.COMPLETED, ConversationStatus.ERROR, ConversationStatus.ACTIVE},
    ConversationStatus.COMPLETED: {ConversationStatus.ACTIVE, ConversationStatus.STREAMING},   # 新一轮对话
    ConversationStatus.ERROR:     {ConversationStatus.ACTIVE, ConversationStatus.STREAMING},   # 重试
}


def validate_conv_transition(current: str | ConversationStatus, target: ConversationStatus) -> bool:
    """
    校验对话状态转换是否合法。

    Args:
        current: 当前状态（字符串或枚举）
        target:  目标状态（枚举）

    Returns:
        True 表示合法。不合法时记录警告并返回 False（不抛异常，避免阻断主流程）。
    """
    cur = ConversationStatus(current) if isinstance(current, str) else current
    allowed = _CONV_TRANSITIONS.get(cur, set())
    if target not in allowed:
        logger.warning(
            "非法对话状态转换: %s → %s（允许: %s）",
            cur.value, target.value, {s.value for s in allowed},
        )
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# 消息状态机
# ══════════════════════════════════════════════════════════════════════════════

class MessageStatus(str, Enum):
    """消息生命周期状态。映射到 DB 的 stream_completed 字段。"""
    PRE_WRITE = "pre_write"     # 预写空行（stream_completed=False, content=""）
    STREAMING = "streaming"     # 流式生成中（stream_completed=False, stream_buffer 有内容）
    FINALIZED = "finalized"     # 生成完成（stream_completed=True, content 有最终内容）
    PARTIAL = "partial"         # 中断保存（stream_completed=True, content 为部分内容）

    @classmethod
    def from_db(cls, stream_completed: bool, content: str, stream_buffer: str) -> MessageStatus:
        """从 DB 字段反推当前状态。"""
        if stream_completed:
            return cls.FINALIZED
        if stream_buffer:
            return cls.STREAMING
        if not content:
            return cls.PRE_WRITE
        return cls.STREAMING


_MSG_TRANSITIONS: dict[MessageStatus, set[MessageStatus]] = {
    MessageStatus.PRE_WRITE: {MessageStatus.STREAMING, MessageStatus.FINALIZED, MessageStatus.PARTIAL},
    MessageStatus.STREAMING: {MessageStatus.FINALIZED, MessageStatus.PARTIAL},
    MessageStatus.FINALIZED: set(),   # 终态
    MessageStatus.PARTIAL:   {MessageStatus.FINALIZED},  # 续写后可完成
}


# ══════════════════════════════════════════════════════════════════════════════
# 工具执行状态机
# ══════════════════════════════════════════════════════════════════════════════

class ToolExecutionStatus(str, Enum):
    """工具调用生命周期状态。"""
    RUNNING = "running"     # 工具正在执行
    DONE = "done"           # 执行成功
    ERROR = "error"         # 执行失败
    TIMEOUT = "timeout"     # 执行超时

    @classmethod
    def _missing_(cls, value: object) -> ToolExecutionStatus | None:
        if isinstance(value, str):
            for member in cls:
                if member.value == value:
                    return member
        return None


_TOOL_TRANSITIONS: dict[ToolExecutionStatus, set[ToolExecutionStatus]] = {
    ToolExecutionStatus.RUNNING: {ToolExecutionStatus.DONE, ToolExecutionStatus.ERROR, ToolExecutionStatus.TIMEOUT},
    ToolExecutionStatus.DONE:    set(),  # 终态
    ToolExecutionStatus.ERROR:   set(),  # 终态
    ToolExecutionStatus.TIMEOUT: set(),  # 终态
}


def validate_tool_transition(current: str | ToolExecutionStatus, target: ToolExecutionStatus) -> bool:
    """校验工具执行状态转换是否合法。"""
    cur = ToolExecutionStatus(current) if isinstance(current, str) else current
    allowed = _TOOL_TRANSITIONS.get(cur, set())
    if target not in allowed:
        logger.warning(
            "非法工具状态转换: %s → %s（允许: %s）",
            cur.value, target.value, {s.value for s in allowed},
        )
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# SSE 事件类型注册表
# ══════════════════════════════════════════════════════════════════════════════

class SSEEventType(str, Enum):
    """
    SSE 事件类型 — 单一注册表，替代 _detect_event_type() 中的硬编码字符串列表。

    每个值对应 SSE JSON payload 中的 key 名。
    检测优先级由 detect() 方法中的 _PRIORITY_ORDER 决定。
    """
    # ── 流式内容 ──
    CONTENT = "content"
    THINKING = "thinking"

    # ── 工具调用 ──
    TOOL_CALL = "tool_call"
    TOOL_CALL_START = "tool_call_start"
    TOOL_RESULT = "tool_result"
    SEARCH_ITEM = "search_item"
    SANDBOX_OUTPUT = "sandbox_output"

    # ── 文件产物 ──
    FILE_ARTIFACT = "file_artifact"

    # ── 认知/计划 ──
    PLAN_GENERATED = "plan_generated"
    REFLECTION = "reflection"
    CLARIFICATION = "clarification"

    # ── 状态/路由 ──
    STATUS = "status"
    ROUTE = "route"

    # ── 会话控制 ──
    DONE = "done"
    STOPPED = "stopped"
    ERROR = "error"
    PING = "ping"
    RESUME_CONTEXT = "resume_context"

    # ── 未知 ──
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> SSEEventType | None:
        if isinstance(value, str):
            for member in cls:
                if member.value == value:
                    return member
        return None


# 检测优先级：tool/control 事件优先于 content（避免多 key 时误判）
_SSE_PRIORITY_ORDER: list[SSEEventType] = [
    SSEEventType.DONE,
    SSEEventType.STOPPED,
    SSEEventType.ERROR,
    SSEEventType.CLARIFICATION,
    SSEEventType.TOOL_RESULT,
    SSEEventType.TOOL_CALL,
    SSEEventType.TOOL_CALL_START,
    SSEEventType.SEARCH_ITEM,
    SSEEventType.SANDBOX_OUTPUT,
    SSEEventType.FILE_ARTIFACT,
    SSEEventType.PLAN_GENERATED,
    SSEEventType.REFLECTION,
    SSEEventType.STATUS,
    SSEEventType.ROUTE,
    SSEEventType.RESUME_CONTEXT,
    SSEEventType.THINKING,
    SSEEventType.CONTENT,
    SSEEventType.PING,
]


def detect_sse_event_type(data: dict) -> SSEEventType:
    """
    从 SSE payload dict 中检测事件类型。

    按优先级顺序匹配，控制事件 > 工具事件 > 内容事件。
    避免多 key 共存时误判（如 tool_result 和 content 同时存在时优先识别为 tool_result）。
    """
    for etype in _SSE_PRIORITY_ORDER:
        if etype.value in data:
            return etype
    return SSEEventType.UNKNOWN
