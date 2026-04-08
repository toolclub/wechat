"""
沙箱执行上下文：通过 contextvars 在图执行期间传递 conv_id 给沙箱工具。

设计原因：
  LangGraph ToolNode 执行工具时，@tool 函数的 config 参数注入不稳定。
  使用 contextvars 在图执行入口设置 conv_id，工具函数内直接读取。
  这是 Python 标准的异步上下文传递方式，线程/协程安全。
"""
from contextvars import ContextVar

# 当前执行的对话 ID（在 stream.py 的 _run_graph 入口设置）
current_conv_id: ContextVar[str] = ContextVar("sandbox_conv_id", default="")
# 当前 assistant 消息 ID（用于 artifact 关联）
current_message_id: ContextVar[str] = ContextVar("sandbox_message_id", default="")
