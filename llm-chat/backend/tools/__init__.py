"""
工具注册中心 —— 管理所有可用工具（内置 + MCP + 动态注册）

═══════════════════════════════════════════════════════════════
扩展指南
═══════════════════════════════════════════════════════════════

方式一：添加内置工具（推荐）
  1. 在 tools/builtin/ 目录下新建 my_tool.py：
         from langchain_core.tools import tool

         @tool
         def my_tool(param: str) -> str:
             \"\"\"工具描述\"\"\"
             return result

  2. 在 tools/builtin/__init__.py 的 BUILTIN_TOOLS 列表中追加 my_tool

方式二：添加 MCP 工具（零代码）
  在 config.py 的 MCP_SERVERS 字典中添加 MCP 服务器配置，
  启动时自动加载，无需修改任何 Python 文件。

方式三：动态注册（运行时扩展）
  调用 register_tool(my_tool_instance) 在应用运行时添加工具。
  通常用于插件系统或基于用户配置动态激活工具。

═══════════════════════════════════════════════════════════════
"""
import logging

from langchain_core.tools import BaseTool

from tools.builtin import BUILTIN_TOOLS
from tools.mcp.loader import get_loaded_mcp_tools

logger = logging.getLogger("tools")

_extra_tools: list[BaseTool] = []


def register_tool(tool: BaseTool) -> None:
    """
    动态注册额外工具。
    适用场景：运行时根据用户配置或插件系统动态激活工具。
    """
    _extra_tools.append(tool)
    logger.info("已动态注册工具: %s", tool.name)


def unregister_tool(tool_name: str) -> bool:
    """按名称移除已动态注册的工具，返回是否成功找到并移除。"""
    for i, t in enumerate(_extra_tools):
        if t.name == tool_name:
            _extra_tools.pop(i)
            logger.info("已移除工具: %s", tool_name)
            return True
    return False


def get_all_tools() -> list[BaseTool]:
    """返回所有可用工具：内置工具 + MCP 工具 + 动态注册工具。"""
    return BUILTIN_TOOLS + get_loaded_mcp_tools() + _extra_tools


def get_tool_names() -> list[str]:
    """返回所有可用工具的名称列表。"""
    return [t.name for t in get_all_tools()]


def get_tools_info() -> list[dict]:
    """返回所有工具的详情（供 API 接口使用）。"""
    result = []
    for t in BUILTIN_TOOLS:
        result.append({"name": t.name, "description": t.description or "", "source": "builtin"})
    for t in get_loaded_mcp_tools():
        result.append({"name": t.name, "description": t.description or "", "source": "mcp"})
    for t in _extra_tools:
        result.append({"name": t.name, "description": t.description or "", "source": "dynamic"})
    return result
