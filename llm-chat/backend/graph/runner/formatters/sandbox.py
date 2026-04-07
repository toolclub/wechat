"""
SandboxFormatter：沙箱工具结果格式化器

将 ExecuteResult 的结构化终端数据（commands 数组）推送给前端，
前端逐条渲染为仿真 Linux 终端界面。
"""
import json
from typing import AsyncGenerator

from graph.runner.formatters.base import ToolResultFormatter
from graph.runner.utils import sse


class SandboxFormatter(ToolResultFormatter):
    """
    沙箱工具结果格式化器。

    tool_result 事件中包含 terminal 字段（结构化终端数据），
    前端检测到 terminal 字段后渲染为终端 UI，而非普通文本。
    """

    async def format(self, name: str, raw: str) -> AsyncGenerator[str, None]:
        """
        尝试从 raw 中解析终端上下文（to_display 格式），
        同时推送原始文本作为 output（模型/工具已经格式化好了）。
        """
        yield sse({
            "tool_result": {
                "name": name,
                "output": raw[:5000],
                "is_sandbox": True,
            }
        })
