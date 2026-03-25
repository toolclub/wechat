"""
MCP 工具加载器
通过 langchain-mcp-adapters 连接 MCP 服务器，将 MCP 工具转换为 LangChain BaseTool。

支持的传输协议：
  - stdio：启动子进程（npm/npx/uvx 等）
  - SSE：连接远程 HTTP/SSE 端点

配置示例（config.py 中的 MCP_SERVERS）：
    MCP_SERVERS = {
        # stdio 传输
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
            "transport": "stdio",
        },
        # SSE 传输
        "my_server": {
            "url": "http://localhost:8080/sse",
            "transport": "sse",
        },
    }

扩展指南：
  - 添加新 MCP 服务器：只需在 config.py 的 MCP_SERVERS 中增加一项，无需改代码
  - 自定义工具过滤：在 load_mcp_tools() 中对 tools 列表做过滤即可
  - 工具权限控制：可在此处包装工具，增加鉴权或参数验证逻辑
"""
import logging
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger("tools.mcp")

_loaded_tools: list[BaseTool] = []
_mcp_client = None


async def load_mcp_tools(servers: dict[str, Any]) -> list[BaseTool]:
    """
    连接所有配置的 MCP 服务器并加载工具。

    Args:
        servers: MCP 服务器配置字典（来自 config.MCP_SERVERS）

    Returns:
        LangChain 兼容的工具列表
    """
    global _loaded_tools, _mcp_client

    if not servers:
        return []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        _mcp_client = MultiServerMCPClient(servers)
        tools = await _mcp_client.get_tools()
        _loaded_tools = tools

        logger.info(
            "MCP 工具加载完成：%d 个工具来自 %d 个服务器",
            len(tools),
            len(servers),
        )
        for t in tools:
            logger.info("  ├─ MCP 工具: %s — %s", t.name, (t.description or "")[:60])

        return tools

    except ImportError:
        logger.warning(
            "langchain-mcp-adapters 未安装，MCP 工具不可用。"
            "安装命令：pip install langchain-mcp-adapters"
        )
        return []
    except Exception as exc:
        logger.error("MCP 工具加载失败: %s", exc, exc_info=True)
        return []


def get_loaded_mcp_tools() -> list[BaseTool]:
    """返回已加载的 MCP 工具列表（只读）。"""
    return list(_loaded_tools)
