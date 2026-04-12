"""
向后兼容桥接 — 转发到 fsm/ 模块 + 枚举定义。

旧代码通过 `from db.state_machine import ...` 导入。
"""
from enum import Enum

from fsm.sse_events import SSEEventType, detect_sse_event_type
from fsm.conversation import ConversationSM
from fsm.tool_execution import ToolExecutionSM
from fsm.plan_step import PlanStepSM


def validate_conv_transition(current: str, target_status: str) -> bool:
    """校验对话状态转换是否合法（委托给 ConversationSM）。"""
    try:
        sm = ConversationSM.from_db_status(current)
        result = sm.send_event(target_status)
        return result == target_status
    except Exception:
        return False


def validate_tool_transition(current: str, target_status: str) -> bool:
    """校验工具执行状态转换是否合法（委托给 ToolExecutionSM）。"""
    if current != "running":
        return False
    try:
        sm = ToolExecutionSM()
        sm.send_event(target_status)
        return True
    except Exception:
        return False


# 向后兼容的枚举（直接用字符串常量，不再自定义 Enum）
class ConversationStatus(str, Enum):
    """对话状态枚举。继承 str 使 .value 返回字符串，== 比较与裸字符串兼容。"""
    ACTIVE = "active"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ERROR = "error"


class ToolExecutionStatus(str, Enum):
    """工具执行状态枚举。继承 str 使 .value 返回字符串，兼容 DB 存储和 JSON 序列化。"""
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    TIMEOUT = "timeout"


class PlanStepStatus(str, Enum):
    """计划步骤状态枚举。继承 str 使 .value 返回字符串，兼容 DB 存储和 JSON 序列化。"""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


__all__ = [
    "ConversationSM",
    "ToolExecutionSM",
    "PlanStepSM",
    "SSEEventType",
    "detect_sse_event_type",
    "validate_conv_transition",
    "validate_tool_transition",
    "ConversationStatus",
    "ToolExecutionStatus",
    "PlanStepStatus",
]
