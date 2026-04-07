"""
BaseNode：所有图节点的抽象基类

职责：
  - 定义统一的节点接口（name / execute）
  - 提供所有节点共享的工具方法（消息转换、工具 schema 转换、计划步骤操作）

设计要点：
  - 节点注册到 LangGraph 时使用 node.execute 方法：
        graph.add_node("xxx", some_node.execute)
  - execute 返回 dict，由 LangGraph 合并回 GraphState
  - 共享工具方法定义为 staticmethod，无需实例化即可在子类中调用
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from graph.state import GraphState, PlanStep

logger = logging.getLogger("graph.nodes.base")


class BaseNode(ABC):
    """
    所有图节点的抽象基类。

    子类需实现：
        name    → 节点名称字符串（对应 graph.add_node 第一参数）
        execute → 节点主逻辑，接收 GraphState，返回 dict 更新
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """节点名称，对应 graph.add_node(name, fn) 的 name 参数。"""
        ...

    @abstractmethod
    async def execute(self, state: GraphState) -> dict:
        """
        节点主逻辑。

        参数：
            state: 当前 GraphState
        返回：
            dict：要更新回 GraphState 的字段，由 LangGraph add_messages reducer 合并
        """
        ...

    # ══════════════════════════════════════════════════════════════════════════
    # 消息格式转换工具（供 call_model 系节点使用）
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _to_openai_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """
        将 LangChain BaseMessage 列表转为 OpenAI SDK 原生 dict 格式。

        HumanMessage.content 若已是 list（多模态），直接透传。
        AIMessage 中的 tool_calls 同步转换为 OpenAI function calling 格式，
        确保 call_model_after_tool 在含图片场景下能正确重放工具调用历史。
        """
        role_map = {
            "SystemMessage":   "system",
            "HumanMessage":    "user",
            "AIMessage":       "assistant",
            "ToolMessage":     "tool",
            "FunctionMessage": "function",
        }
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = role_map.get(type(msg).__name__, "user")
            entry: dict[str, Any] = {"role": role, "content": msg.content}

            # ToolMessage 需要带上 tool_call_id
            if role == "tool":
                entry["tool_call_id"] = getattr(msg, "tool_call_id", "")

            # AIMessage 中的 tool_calls 转 OpenAI function calling 格式
            if role == "assistant":
                lc_tool_calls = getattr(msg, "tool_calls", None) or []
                if lc_tool_calls:
                    oai_tool_calls = []
                    for tc in lc_tool_calls:
                        if isinstance(tc, dict):
                            tc_id   = tc.get("id", "")
                            tc_name = tc.get("name", "")
                            tc_args = tc.get("args", {})
                        else:
                            tc_id   = getattr(tc, "id", "")
                            tc_name = getattr(tc, "name", "")
                            tc_args = getattr(tc, "args", {})
                        oai_tool_calls.append({
                            "id": tc_id,
                            "type": "function",
                            "function": {
                                "name": tc_name,
                                "arguments": json.dumps(tc_args, ensure_ascii=False),
                            },
                        })
                    entry["tool_calls"] = oai_tool_calls
                    # OpenAI 规范：有 tool_calls 时 content 须为 None
                    if not entry["content"]:
                        entry["content"] = None

            result.append(entry)
        return result

    @staticmethod
    def _tools_to_openai_schema(tools: list) -> list[dict[str, Any]]:
        """
        将 LangChain BaseTool 列表转为 OpenAI tools 参数格式。
        用于向 OpenAI SDK 传递工具定义（function calling）。
        """
        result = []
        for tool in tools:
            schema = getattr(tool, "args_schema", None)
            if schema is not None:
                parameters = (
                    schema.model_json_schema()
                    if hasattr(schema, "model_json_schema")
                    else schema.schema()
                )
                # 移除 pydantic 自动生成的 title，保持简洁
                parameters.pop("title", None)
            else:
                parameters = {"type": "object", "properties": {}}
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": getattr(tool, "description", ""),
                    "parameters": parameters,
                },
            })
        return result

    @staticmethod
    def _convert_oai_tool_calls(oai_tool_calls: list) -> list[dict[str, Any]]:
        """
        将 OpenAI ChatCompletionMessage.tool_calls 转为 LangChain AIMessage.tool_calls 格式。

        这样返回的 AIMessage 能被 LangGraph ToolNode 正确识别和执行。
        格式：[{"id": ..., "name": ..., "args": {...}, "type": "tool_call"}]
        """
        lc_tool_calls = []
        for tc in oai_tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {"_raw": tc.function.arguments}
            lc_tool_calls.append({
                "id":   tc.id,
                "name": tc.function.name,
                "args": args,
                "type": "tool_call",
            })
        return lc_tool_calls

    # ══════════════════════════════════════════════════════════════════════════
    # 计划步骤工具
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _mark_step(plan: list[PlanStep], idx: int, status: str) -> list[PlanStep]:
        """返回将指定步骤状态设为 status 的新计划列表（不修改原列表）。"""
        updated = list(plan)
        if 0 <= idx < len(updated):
            updated[idx] = {**updated[idx], "status": status}
        return updated

    # ══════════════════════════════════════════════════════════════════════════
    # 流式 LLM 调用工具（供 CallModel 系节点共享）
    # ══════════════════════════════════════════════════════════════════════════

    # 推理模型（GLM/DeepSeek-R1）thinking token 前缀标识
    _THINK_PREFIX = "\x00THINK\x00"

    # 内容审核错误标识（MiniMax 等厂商特定错误码）
    _AUDIT_MARKERS = ("1027", "sensitive")

    @staticmethod
    async def _stream_tokens(
        llm,
        oai_messages: list,
        temperature: float,
        conv_id: str,
        node: str,
        timeout: float = 180.0,
    ) -> dict:
        """
        流式 LLM 调用：逐 token yield，通过 adispatch_custom_event 发出事件。

        LLMStreamHandler 在 astream_events 中监听这些事件，实时推送给前端。
        节点返回时 full_response 包含完整内容，CallModelEndHandler 因
        ctx.*_streamed=True 而跳过重复发送。

        支持推理模型（GLM/DeepSeek-R1 等）的 thinking token：
          - "\\x00THINK\\x00" 前缀的 delta 作为 thinking 事件分发
          - 普通 delta 作为 llm_token 事件分发
        """
        from langchain_core.callbacks.manager import adispatch_custom_event

        _THINK_PREFIX = BaseNode._THINK_PREFIX
        content_parts:  list[str] = []
        thinking_parts: list[str] = []
        token_count = 0

        async for delta in llm.astream(oai_messages, temperature=temperature, timeout=timeout):
            token_count += 1
            if delta.startswith(_THINK_PREFIX):
                thinking_text = delta[len(_THINK_PREFIX):]
                thinking_parts.append(thinking_text)
                await adispatch_custom_event("llm_thinking", {"content": thinking_text, "node": node})
            else:
                content_parts.append(delta)
                await adispatch_custom_event("llm_token", {"content": delta, "node": node})

        full_content  = "".join(content_parts)
        full_thinking = "".join(thinking_parts)
        logger.info(
            "_stream_tokens 完成 | conv=%s | node=%s | tokens=%d | content_len=%d | thinking_len=%d",
            conv_id, node, token_count, len(full_content), len(full_thinking),
        )
        result: dict = {
            "messages":      [AIMessage(content=full_content)],
            "full_response": full_content,
            "_was_streamed": True,
        }
        if full_thinking:
            result["full_thinking"] = full_thinking
        return result

    @classmethod
    def _is_audit_error(cls, exc: Exception) -> bool:
        """判断是否为内容审核错误（MiniMax 1027 等）。"""
        err_str = str(exc)
        return any(marker in err_str for marker in cls._AUDIT_MARKERS)

    @staticmethod
    def _audit_fallback() -> dict:
        """内容审核错误时的优雅降级响应。"""
        msg = "抱歉，该内容触发了模型安全审核，无法生成回复。请换个方式描述问题。"
        return {"messages": [], "full_response": msg}
