"""
SandboxOutputHandler：沙箱实时输出事件处理器

监听 on_custom_event("sandbox_output") 事件，
将 stdout/stderr 实时推送给前端终端面板。
"""
from typing import AsyncGenerator

from graph.runner.context import StreamContext
from graph.runner.handlers.base import EventHandler
from graph.runner.utils import sse


class SandboxOutputHandler(EventHandler):
    """沙箱实时输出：逐块推送 stdout/stderr 给前端终端。"""

    def matches(self, event_type: str, node_name: str, event_name: str) -> bool:
        return event_type == "on_custom_event" and event_name == "sandbox_output"

    async def handle(self, event: dict, ctx: StreamContext) -> AsyncGenerator[str, None]:
        data = event.get("data", {})
        if not isinstance(data, dict):
            return
        yield sse({
            "sandbox_output": {
                "stream": data.get("stream", "stdout"),
                "text": data.get("text", ""),
                "tool_name": data.get("tool_name", ""),
            }
        })
