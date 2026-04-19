"""
对话数据结构（与原 layers/memory.py 保持完全向后兼容）
"""
import time
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str           # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    id: int = 0         # DB 自增主键（0 表示尚未持久化）
    tool_summary: str = ""   # 工具调用记录摘要（独立字段，不混入 content）
    step_summary: str = ""   # 多步执行过程摘要（独立字段，不混入 content）
    thinking: str = ""       # 思考纯文本（向后兼容，= 所有 segments 拼接）
    thinking_segments: list = field(default_factory=list)
    # 结构化思考段：[{"node", "step_index", "phase", "content"}]


@dataclass
class Conversation:
    id: str
    title: str = "新对话"
    system_prompt: str = ""
    core_memory: dict = field(default_factory=dict)           # 用户偏好/项目规则/当前任务等常驻记忆
    messages: list[Message] = field(default_factory=list)  # 完整历史，永不删除
    mid_term_summary: str = ""                              # 语义记忆（中期摘要）
    mid_term_cursor: int = 0                                # messages[:cursor] 已完成摘要
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    client_id: str = ""                                     # 浏览器唯一标识（localStorage 生成）
    status: str = "active"                                  # active / streaming / completed / error
