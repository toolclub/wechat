"""
LangGraph Agent 图构建与全局单例管理

图结构：
    START
      │
      ▼
    retrieve_context   ← 检索 RAG + 判断 forget_mode + 组装历史消息
      │
      ▼
    call_model         ← LLM 推理（已 bind_tools）
      │
    should_continue?
      ├── "tools"      ← ToolNode 并发执行工具 → 回到 call_model
      └── "save_response"
              │
              ▼
         compress_memory  ← 按需生成摘要 + 写入 Qdrant
              │
              ▼
             END

扩展指南：
  - 添加新节点：graph.add_node("my_node", my_node_fn)
  - 添加顺序边：graph.add_edge("existing_node", "my_node")
  - 添加条件边：graph.add_conditional_edges("my_node", my_condition_fn)
  - 在 call_model 前插入节点（如 web 检索前置）：
        graph.add_edge("retrieve_context", "my_preprocess")
        graph.add_edge("my_preprocess", "call_model")
        （移除原来 retrieve_context → call_model 边）
"""
import logging
from typing import Any

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from config import CHAT_MODEL, OLLAMA_BASE_URL
from graph.edges import should_continue
from graph.nodes import (
    compress_memory,
    make_call_model,
    make_retrieve_context,
    save_response,
)
from graph.state import GraphState
from llm.chat import get_chat_llm

logger = logging.getLogger("graph.agent")

# 模块级编译图单例（在应用启动时通过 init() 初始化）
_compiled_graph: Any = None


def build_graph(tools: list[BaseTool], model: str = CHAT_MODEL) -> Any:
    """
    根据工具列表和模型名称构建并编译 LangGraph 图。

    每次调用都会构建新图（通常只在启动时调用一次）。
    若需支持不同用户使用不同模型，可改为在请求时动态构建。
    """
    tool_names = [t.name for t in tools]

    # 绑定工具的 LLM
    llm = get_chat_llm(model=model)
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    # 节点实例
    retrieve_fn = make_retrieve_context(tool_names)
    call_model_fn = make_call_model(llm_with_tools)

    # 构建图
    graph = StateGraph(GraphState)
    graph.add_node("retrieve_context", retrieve_fn)
    graph.add_node("call_model", call_model_fn)
    graph.add_node("save_response", save_response)
    graph.add_node("compress_memory", compress_memory)

    if tools:
        tool_node = ToolNode(tools)
        graph.add_node("tools", tool_node)
        graph.add_conditional_edges(
            "call_model",
            should_continue,
            {"tools": "tools", "save_response": "save_response"},
        )
        graph.add_edge("tools", "call_model")
    else:
        graph.add_edge("call_model", "save_response")

    graph.add_edge(START, "retrieve_context")
    graph.add_edge("retrieve_context", "call_model")
    graph.add_edge("save_response", "compress_memory")
    graph.add_edge("compress_memory", END)

    compiled = graph.compile()
    logger.info(
        "Agent 图已编译：模型=%s，工具数=%d（%s）",
        model,
        len(tools),
        ", ".join(tool_names) if tool_names else "无",
    )
    return compiled


def init(tools: list[BaseTool], model: str = CHAT_MODEL) -> None:
    """应用启动时调用，构建并缓存编译后的图。"""
    global _compiled_graph
    _compiled_graph = build_graph(tools, model)


def get_graph() -> Any:
    """返回已编译的图，若未初始化则抛出异常。"""
    if _compiled_graph is None:
        raise RuntimeError("Agent 图未初始化，请先调用 graph.agent.init(tools)")
    return _compiled_graph
