"""
图运行器：将 LangGraph astream_events 翻译为 FastAPI SSE 字符串流

SSE 事件格式（与原版完全兼容，前端无需修改）：
  data: {"content": "...token..."}\n\n       ← LLM 输出 token（增量）
  data: {"tool_call": {...}}\n\n             ← 工具调用开始（新增，前端可选消费）
  data: {"tool_result": {...}}\n\n           ← 工具调用结果（新增，前端可选消费）
  data: {"done": true, "compressed": bool}\n\n  ← 完成信号

关键过滤：只转发来自 "call_model" 节点的 LLM token，
忽略 compress_memory 节点内摘要模型产生的 token（避免泄露到前端）。
"""
import json
import logging
from typing import AsyncGenerator

from graph.agent import get_graph
from graph.state import GraphState

logger = logging.getLogger("graph.runner")


async def stream_response(
    conv_id: str,
    user_message: str,
    model: str,
    temperature: float = 0.7,
) -> AsyncGenerator[str, None]:
    """
    运行 Agent 图并以 SSE 字符串形式 yield 事件。

    Args:
        conv_id:      对话 ID
        user_message: 用户当前消息
        model:        LLM 模型名称
        temperature:  采样温度

    Yields:
        SSE 格式字符串（以 "data: " 开头，以 "\n\n" 结尾）
    """
    graph = get_graph()

    initial_state: GraphState = {
        "conv_id": conv_id,
        "user_message": user_message,
        "model": model,
        "temperature": temperature,
        "messages": [],
        "long_term_memories": [],
        "forget_mode": False,
        "full_response": "",
        "compressed": False,
    }

    compressed = False

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            event_type: str = event["event"]
            node_name: str = event.get("metadata", {}).get("langgraph_node", "")

            # ── LLM token 流（只转发 call_model 节点的输出，过滤摘要模型） ──
            if event_type == "on_chat_model_stream" and node_name == "call_model":
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    payload = json.dumps({"content": chunk.content}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"

            # ── 工具调用开始 ──────────────────────────────────────────────────
            elif event_type == "on_tool_start":
                tool_input = event["data"].get("input", {})
                payload = json.dumps(
                    {
                        "tool_call": {
                            "name": event.get("name", ""),
                            "input": tool_input,
                        }
                    },
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"

            # ── 工具调用结束 ──────────────────────────────────────────────────
            elif event_type == "on_tool_end":
                output = event["data"].get("output", "")
                # 截断超长输出避免 SSE 包过大
                output_str = str(output)[:1000]
                payload = json.dumps(
                    {
                        "tool_result": {
                            "name": event.get("name", ""),
                            "output": output_str,
                        }
                    },
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"

            # ── 压缩结果（从 compress_memory 节点的 chain_end 事件获取） ──────
            elif event_type == "on_chain_end" and event.get("name") == "compress_memory":
                output = event["data"].get("output", {})
                if isinstance(output, dict):
                    compressed = output.get("compressed", False)

    except Exception as exc:
        logger.error("图执行失败 conv=%s: %s", conv_id, exc, exc_info=True)
        error_payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
        yield f"data: {error_payload}\n\n"

    # ── 完成信号 ──────────────────────────────────────────────────────────────
    done_payload = json.dumps({"done": True, "compressed": compressed})
    yield f"data: {done_payload}\n\n"
