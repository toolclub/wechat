"""
FileArtifactHandler：文件产物事件处理器

监听 on_custom_event("file_artifact") 事件，
将 sandbox_write 创建的文件以 file_artifact SSE 事件推送给前端。
前端据此渲染文件卡片并支持预览/下载。
"""
from typing import AsyncGenerator

from graph.runner.context import StreamContext
from graph.runner.handlers.base import EventHandler
from graph.runner.utils import sse


class FileArtifactHandler(EventHandler):
    """文件产物：sandbox_write 成功后推送文件信息给前端。"""

    def matches(self, event_type: str, node_name: str, event_name: str) -> bool:
        return event_type == "on_custom_event" and event_name == "file_artifact"

    async def handle(self, event: dict, ctx: StreamContext) -> AsyncGenerator[str, None]:
        data = event.get("data", {})
        if not isinstance(data, dict):
            return
        # 透传所有字段（PPT 需要 slides_html/binary/size/slide_count 等）
        artifact: dict = {
            "name": data.get("name", ""),
            "path": data.get("path", ""),
            "content": data.get("content", ""),
            "language": data.get("language", "text"),
        }
        # 可选字段：有则透传
        for key in ("binary", "size", "slide_count", "theme", "slides_html", "message_id"):
            if key in data:
                artifact[key] = data[key]
        yield sse({"file_artifact": artifact})
