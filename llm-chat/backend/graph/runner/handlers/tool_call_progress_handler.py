"""
ToolCallArgsHandler：工具调用参数流式事件

将 LLM 生成工具参数的每个 JSON 片段实时推送给前端，
让用户在终端中看到"正在写 HTML/代码"的过程，而不是 30 秒静默。

SSE 格式：
  data: {"tool_call_args": {"text": "<!DOCTYPE html>..."}}
"""
from typing import AsyncGenerator

from graph.runner.context import StreamContext
from graph.runner.handlers.base import EventHandler
from graph.runner.utils import sse


class ToolCallArgsHandler(EventHandler):
    """工具调用参数流式推送：前端在终端中展示代码生成过程。"""

    def matches(self, event_type: str, node_name: str, event_name: str) -> bool:
        return event_type == "on_custom_event" and event_name == "tool_call_args"

    async def handle(self, event: dict, ctx: StreamContext) -> AsyncGenerator[str, None]:
        data = event.get("data", {})
        if isinstance(data, dict) and data.get("text"):
            yield sse({"tool_call_args": {"text": data["text"]}})
