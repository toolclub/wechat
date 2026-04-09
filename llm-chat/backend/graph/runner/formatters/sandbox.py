"""
SandboxFormatter：沙箱工具结果格式化器

将 ExecuteResult 的结构化终端数据（commands 数组）推送给前端，
前端逐条渲染为仿真 Linux 终端界面。
"""
import json
import re
from typing import AsyncGenerator

from graph.runner.formatters.base import ToolResultFormatter
from graph.runner.utils import sse


class SandboxFormatter(ToolResultFormatter):
    """
    沙箱工具结果格式化器。

    tool_result 事件中包含 terminal 字段（结构化终端数据），
    前端检测到 terminal 字段后渲染为终端 UI，而非普通文本。
    """

    @staticmethod
    def _extract_exit_code(raw: str) -> int:
        """从 ExecuteResult.to_display() 格式的输出中提取 exit code。"""
        # to_display() 输出格式：⏱ N.NNs | exit=N
        match = re.search(r'\|\s*exit=(-?\d+)', raw)
        return int(match.group(1)) if match else 0

    async def format(self, name: str, raw: str) -> AsyncGenerator[str, None]:
        """
        尝试从 raw 中解析终端上下文（to_display 格式），
        同时推送原始文本作为 output（模型/工具已经格式化好了）。
        status 字段根据 exit code 判断：0=done，非0=error。
        """
        exit_code = self._extract_exit_code(raw)
        yield sse({
            "tool_result": {
                "name": name,
                "output": raw[:5000],
                "is_sandbox": True,
                "status": "error" if exit_code != 0 else "done",
            }
        })
