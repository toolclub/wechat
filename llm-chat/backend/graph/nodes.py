"""
LangGraph 图节点定义

节点列表：
  retrieve_context  ── 从 ConversationStore + Qdrant 检索上下文，构建消息列表
  call_model        ── 调用 LLM（绑定工具），生成回复或工具调用指令
  save_response     ── 将用户消息和 AI 回复持久化到 ConversationStore
  compress_memory   ── 按需触发对话压缩（生成摘要 + 写入 Qdrant）

工厂函数（make_*）用于将运行时依赖（LLM、工具列表）注入到节点闭包中，
避免全局变量，方便测试和热重载。
"""
import logging
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool

from config import LONGTERM_MEMORY_ENABLED
from graph.state import GraphState
from memory import store as memory_store
from memory.compressor import maybe_compress
from memory.context_builder import build_messages

logger = logging.getLogger("graph.nodes")


# ── 节点 1：检索上下文 ────────────────────────────────────────────────────────

def make_retrieve_context(tool_names: list[str]):
    """
    工厂函数：创建 retrieve_context 节点。

    职责：
      1. 从 Qdrant 检索长期记忆
      2. 用余弦相似度判断是否触发忘记模式
      3. 调用 context_builder 组装历史消息 + 系统提示
    """
    async def retrieve_context(state: GraphState) -> dict:
        conv_id = state["conv_id"]
        user_msg = state["user_message"]
        conv = memory_store.get(conv_id)

        long_term: list[str] = []
        forget_mode = False

        if LONGTERM_MEMORY_ENABLED and user_msg:
            from rag import retriever as rag_retriever
            long_term = await rag_retriever.search_memories(conv_id, user_msg)

            if not long_term and conv:
                if conv.mid_term_summary:
                    relevant = await rag_retriever.is_relevant_to_summary(
                        user_msg, conv.mid_term_summary
                    )
                else:
                    # 无摘要时，与最近几条用户消息比较
                    recent = [m.content for m in conv.messages if m.role == "user"][-2:]
                    if recent:
                        relevant = await rag_retriever.is_relevant_to_recent(user_msg, recent)
                    else:
                        relevant = True
                forget_mode = not relevant

        # 构建历史消息列表（含系统提示、摘要、长期记忆、滑动窗口）
        history_messages = build_messages(conv, long_term, forget_mode, tool_names)
        # 追加本轮用户消息
        history_messages.append(HumanMessage(content=user_msg))

        return {
            "messages": history_messages,
            "long_term_memories": long_term,
            "forget_mode": forget_mode,
        }

    return retrieve_context


# ── 节点 2：调用 LLM ──────────────────────────────────────────────────────────

def make_call_model(llm_with_tools: Any):
    """
    工厂函数：创建 call_model 节点。

    职责：
      - 将 state.messages 送入 LLM
      - 若 LLM 返回工具调用 → should_continue 路由到 tools 节点
      - 若 LLM 返回最终回复 → 更新 full_response
    """
    async def call_model(state: GraphState) -> dict:
        messages = list(state["messages"])
        response = await llm_with_tools.ainvoke(messages)

        # 提取文本内容（工具调用时 content 通常为空）
        content = response.content if isinstance(response.content, str) else ""

        return {
            "messages": [response],
            "full_response": content,  # 最后一次非工具调用时才有实际内容
        }

    return call_model


# ── 节点 3：保存回复 ──────────────────────────────────────────────────────────

async def save_response(state: GraphState) -> dict:
    """
    将本轮用户消息和 AI 最终回复追加到 ConversationStore 并持久化。
    工具调用中间过程不写入（保持 conv.messages 只含 user/assistant 对）。
    """
    conv_id = state["conv_id"]
    user_msg = state["user_message"]
    full_response = state.get("full_response", "")

    memory_store.add_message(conv_id, "user", user_msg)
    if full_response:
        memory_store.add_message(conv_id, "assistant", full_response)

    return {}


# ── 节点 4：压缩记忆 ──────────────────────────────────────────────────────────

async def compress_memory(state: GraphState) -> dict:
    """
    按需触发对话压缩：
      - 对超过阈值的旧消息生成摘要
      - 同时将这批消息写入 Qdrant 长期记忆
    不影响流式输出（在 save_response 之后运行）。
    """
    conv_id = state["conv_id"]
    try:
        compressed = await maybe_compress(conv_id)
    except Exception as exc:
        logger.error("压缩失败 conv=%s: %s", conv_id, exc)
        compressed = False
    return {"compressed": compressed}
