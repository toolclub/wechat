"""
视觉节点事件处理器

VisionStartHandler:  VisionNode 开始处理图片时派发 vision_analyze 事件，
                     转换为前端状态通知：{"status": "vision_analyze"}。

视觉的流式 token 已迁移到统一 emit_thinking 协议（node=vision, phase=content），
由 LLMStreamHandler 统一转发，此文件不再维护 VisionStreamHandler。
"""
from typing import AsyncGenerator

from graph.runner.context import StreamContext
from graph.runner.handlers.base import EventHandler
from graph.runner.utils import sse


class VisionStartHandler(EventHandler):
    """视觉分析开始：通知前端进入"图像解析中"状态。"""

    def matches(self, event_type: str, node_name: str, event_name: str) -> bool:
        return event_type == "on_custom_event" and event_name == "vision_analyze"

    async def handle(self, event: dict, ctx: StreamContext) -> AsyncGenerator[str, None]:
        yield sse({"status": "vision_analyze"})
