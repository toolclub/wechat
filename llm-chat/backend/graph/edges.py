"""
LangGraph 条件边：决定 call_model 之后的路由
"""
from graph.state import GraphState


def should_continue(state: GraphState) -> str:
    """
    检查最后一条 AI 消息是否包含工具调用。
      - 有工具调用 → 路由到 "tools" 节点执行
      - 无工具调用 → 路由到 "save_response" 节点保存结果
    """
    messages = state.get("messages", [])
    if not messages:
        return "save_response"

    last = messages[-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"

    return "save_response"
