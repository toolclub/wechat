"""
SaveResponseNode：保存响应节点

职责：
  - 将本轮用户消息和 AI 最终回复追加到 ConversationStore 并持久化
  - 含图片时生成描述占位符，避免将原始 base64 存入数据库
  - 保存工具调用事件到 tool_events 表（供前端历史查看）
  - 写回语义缓存（chat/code 永不过期；search/search_code 带 TTL）
  - 清理工具调用残留文本（MiniMax 等模型在流式模式下可能输出 function call 文本）
"""
import json
import logging
import re

from langchain_core.callbacks.manager import adispatch_custom_event

from config import (
    DEFAULT_SYSTEM_PROMPT,
    SEMANTIC_CACHE_NAMESPACE_MODE,
    SEMANTIC_CACHE_SEARCH_TTL_HOURS,
    VISION_API_KEY,
    VISION_BASE_URL,
    VISION_MODEL,
)
from graph.nodes.base import BaseNode
from graph.state import GraphState
from memory import store as memory_store

logger = logging.getLogger("graph.nodes.save_response")

# COMPAT: 工具调用残留文本标识符（MiniMax 等模型在流式模式下可能输出）。
# 流式层（llm_handlers.py）已在 token 级别拦截，此处作为存储前的最终兜底清理。
# 当 MiniMax 等模型修复此行为后可移除。
_TOOL_CALL_ARTIFACTS = ("[TOOL_CALL]", "minimax:tool_call", "<tool_call>", "[/TOOL_CALL]")


class SaveResponseNode(BaseNode):
    """保存响应节点：将本轮对话持久化并更新语义缓存。"""

    @property
    def name(self) -> str:
        return "save_response"

    async def execute(self, state: GraphState) -> dict:
        """
        持久化流程：
          1. 提取工具调用事件列表
          2. 处理图片占位符（含图片时生成描述替代 base64）
          3. 写入用户消息到数据库
          4. 清理并写入 AI 回复到数据库（含工具调用摘要）
          5. 保存工具调用事件
          6. 写回语义缓存
        """
        from logging_config import get_conv_logger

        conv_id   = state["conv_id"]
        client_id = state.get("client_id", "")
        user_msg  = state["user_message"]
        images    = state.get("images", [])

        # 原始 full_response（含 think 块），用于澄清标记检测
        raw_response  = state.get("full_response", "")
        # 移除 think 块后的 full_response（用于保存和日志）
        full_response = self._strip_think_blocks(raw_response)

        # 对话链路日志
        clog = get_conv_logger(client_id, conv_id)
        route           = state.get("route", "chat")
        plan            = state.get("plan", [])
        tool_events_list = self._extract_tool_events(state)
        tool_names_list  = [ev["tool_name"] for ev in tool_events_list]
        clog.info(
            "对话完成 | route=%s | model=%s | plan_steps=%d | tools=%s | "
            "response_len=%d | images=%d | user_msg=%.60s",
            route,
            state.get("answer_model", state.get("model", "")),
            len(plan),
            tool_names_list,
            len(full_response),
            len(images),
            user_msg,
        )

        # ── 图片处理：生成存储用消息（优先用完整视觉描述，降级用短占位符） ────
        # 提前到澄清检测之前，确保澄清时也能保存图片上下文到历史
        user_msg_to_save = await self._build_user_msg_for_storage(state)

        # ── 澄清检测 ──────────────────────────────────────────────────────────
        # 优先：DB-first 路径 — call_model_node 预检直接设置 state 字段
        clar_data = state.get("clarification_data") or None
        # COMPAT: 模型通过 system prompt 主动输出 [NEED_CLARIFICATION] 标记时，
        # 需要从文本中解析。待 system prompt 改为工具调用方式后可移除。
        if not clar_data:
            for candidate in (full_response, raw_response):
                if candidate and self._is_clarification_response(candidate):
                    clar_data = self._extract_clarification_from_text(candidate)
                    if clar_data:
                        break

        # 获取 StreamSession 预写的 DB 行 ID
        pre_user_id = state.get("pre_user_db_id", 0)
        pre_asst_id = state.get("pre_assistant_db_id", 0)

        if clar_data:
            await adispatch_custom_event("clarification_needed", clar_data)
            logger.info(
                "澄清问询 | conv=%s | items=%d | question=%.80s",
                conv_id, len(clar_data.get("items", [])), clar_data.get("question", ""),
            )
            # UPDATE 预写的 user 行 + 追加到内存缓存
            await memory_store.add_message(
                conv_id, "user", self._sanitize_for_db(user_msg_to_save),
                update_db_id=pre_user_id,
            )
            return {"needs_clarification": True}

        # ── 写入用户消息（UPDATE 预写行，追加到内存缓存） ──
        await memory_store.add_message(
            conv_id, "user", self._sanitize_for_db(user_msg_to_save),
            update_db_id=pre_user_id,
        )

        # ── 写入 AI 回复（UPDATE 预写行，追加到内存缓存） ──
        # DB-first：tool_summary 和 step_summary 存入独立字段，不混入 content
        if full_response:
            tool_summary = self._build_tool_summary(state)
            step_summary = self._build_step_context(state)
            await memory_store.add_message(
                conv_id, "assistant", self._sanitize_for_db(full_response),
                update_db_id=pre_asst_id,
                tool_summary=self._sanitize_for_db(tool_summary),
                step_summary=self._sanitize_for_db(step_summary),
            )

        # ── 保存工具调用事件 ─────────────────────────────────────────────────
        if tool_events_list:
            from memory.tool_events import save_tool_event
            for ev in tool_events_list:
                await save_tool_event(conv_id, ev["tool_name"], ev["tool_input"])

        # ── 写回语义缓存 ─────────────────────────────────────────────────────
        await self._write_cache(state, user_msg, full_response, route, client_id, conv_id)

        # ── 确保 DB 中所有步骤都标记为 done（兜底） ────────────────────────────
        # reflector 每步完成时会写 DB，但最后一步可能因异常/时序未更新
        plan_id = state.get("plan_id", "")
        plan = state.get("plan", [])
        if plan_id and plan:
            try:
                from db.plan_store import finalize_all_steps
                await finalize_all_steps(plan_id, plan)
            except Exception as exc:
                logger.warning("finalize_all_steps 失败（步骤可能卡在 running）: %s", exc)

        return {}

    # ══════════════════════════════════════════════════════════════════════════
    # 私有工具方法
    # ══════════════════════════════════════════════════════════════════════════

    # ──────────────────────────────────────────────────────────────────────────
    # 语义缓存写入（4 个阶段 + 1 个调度器）
    # ──────────────────────────────────────────────────────────────────────────
    #
    # 原来 _write_cache 一个方法同时承担了 5 件事：跳过判定、脏数据清理、TTL
    # 计算、命名空间派生、实际 cache.store 调用。读写谁都看不清楚，改一处
    # 要翻 70 行。
    #
    # 拆成 4 个职责单一的纯函数 + 1 个调度器方法：
    #
    #     _should_cache    : 返回"要不要缓存"的布尔值（跳过判定 + None 值语义）
    #     _clean_response  : 清理工具调用残留文本，返回清洗后的字符串或 None
    #     _compute_ttl     : 根据 route 决定过期时间（秒）
    #     _write_cache     : 调度器，编排上面三步 + 实际调用 cache.store
    #
    # 收益：
    #   1. 每个小函数可以单独写单元测试（不用 mock 整个 cache backend）
    #   2. 将来要加新的"不缓存条件"或新路由 TTL 只改一个函数
    #   3. 阅读 _write_cache 时一眼看清整个流程

    def _should_cache(
        self,
        state: GraphState,
        full_response: str,
    ) -> bool:
        """
        判断本轮响应是否应该写入语义缓存。

        不缓存的情形（按检查顺序）：
          - 响应为空
          - 已命中缓存（避免覆盖自己读到的东西，无意义）
          - 含图片（语义随图片内容变化，缓存命中会跳过 VisionNode，结果错）
          - 含工具调用（缓存只存文本，命中后会跳过工具执行，丢失文件产物/沙箱
            状态等副作用，导致下一次命中看起来"做了事"但实际没做）
        """
        if not full_response:
            return False
        if state.get("cache_hit"):
            return False
        if state.get("images"):
            return False
        # 含工具调用的响应不缓存
        if self._extract_tool_events(state):
            return False
        return True

    def _clean_response(self, full_response: str) -> str | None:
        """
        检测并清理 MiniMax 等模型输出的工具调用残留文本。

        Returns:
            - 清理后的字符串（可写入缓存）
            - None 表示清理后为空，本轮不应写入缓存

        处理流程：
          1. 扫描是否存在 _TOOL_CALL_ARTIFACTS 里的任一 marker
          2. 若存在，正则剥掉三类残留（[TOOL_CALL]...[/TOOL_CALL] /
             minimax:tool_call... / <tool_call>...</tool_call>）
          3. 剥离后为空字符串返回 None（整条就是工具调用 noise，没有
             真正的文本内容可缓存）
        """
        has_artifact = any(a in full_response for a in _TOOL_CALL_ARTIFACTS)
        if not has_artifact:
            return full_response

        cleaned = re.sub(r"\[TOOL_CALL\].*?\[/TOOL_CALL\]", "", full_response, flags=re.DOTALL)
        cleaned = re.sub(r"minimax:tool_call.*", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL)
        cleaned = cleaned.strip()

        if not cleaned:
            logger.warning(
                "ARTIFACT SKIP | 响应清理后为空，跳过缓存 | response='%.100s'",
                full_response,
            )
            return None

        logger.warning(
            "ARTIFACT CLEAN | 工具调用残留文本已清理后写入缓存 | response='%.100s'",
            full_response,
        )
        return cleaned

    @staticmethod
    def _compute_ttl(route: str) -> int:
        """
        根据路由类型计算缓存 TTL（秒）。

        - search / search_code: 短 TTL（默认 2 小时），搜索结果时效性强，
          避免返回过期新闻/文档
        - 其他（chat / code）  : 24 小时兜底，防止缓存中毒永久有效

        所有路由都必须带 TTL，是因为早期版本出过一次事故：某轮响应错误地
        把工具调用残留文本写进了缓存（那次 _clean_response 逻辑还没加），
        没有 TTL 的话这条脏数据会永久命中所有相似请求。现在 TTL 是兜底的
        "即使清理逻辑失效也不会永久污染"保险。
        """
        if route in ("search", "search_code"):
            return SEMANTIC_CACHE_SEARCH_TTL_HOURS * 3600
        return 24 * 3600

    async def _write_cache(
        self,
        state: GraphState,
        user_msg: str,
        full_response: str,
        route: str,
        client_id: str,
        conv_id: str,
    ) -> None:
        """
        语义缓存写入的顶层调度器。

        按 `_should_cache → _clean_response → derive_cache_namespace →
        _compute_ttl → cache.store` 的顺序编排。任何一步判定不缓存就提前
        return，不再继续下游。

        所有 IO 异常都被捕获并落 warning（铁律 #9），不能让缓存写入失败
        影响主流程的 SSE 响应。
        """
        # 1) 是否应该缓存
        if not self._should_cache(state, full_response):
            return

        # 2) 清理残留文本（None 表示清洗后为空，不缓存）
        cleaned = self._clean_response(full_response)
        if cleaned is None:
            return

        # 3) 实际写入缓存（派生命名空间 + 计算 TTL + 调用 cache backend）
        try:
            from cache.factory import get_cache
            from graph.nodes.cache_node import derive_cache_namespace

            # system_prompt 由 SemanticCacheNode 在图入口统一注入 state，
            # 这里直接读取，避免重复查 conversations 表（Commit 7 的改动）。
            system_prompt = state.get("system_prompt", "")
            namespace = derive_cache_namespace(
                system_prompt, conv_id, SEMANTIC_CACHE_NAMESPACE_MODE, client_id
            )
            ttl = self._compute_ttl(route)

            cache = get_cache()
            await cache.store(user_msg, cleaned, namespace, ttl_seconds=ttl)
        except Exception as exc:
            logger.warning("写入语义缓存失败（不影响主流程）: %s", exc)

    async def _build_user_msg_for_storage(self, state: GraphState) -> str:
        """
        构建用于持久化到 DB 的用户消息。

        - 有图片且 VisionNode 已生成完整描述（vision_description）：
            将完整描述附加到用户消息，保证下一轮（如澄清后）能从历史中恢复图片上下文。
        - 有图片但 vision_description 为空（VisionNode 降级）：
            调用视觉模型生成简短占位描述后附加。
        - 无图片：直接返回用户消息原文。
        """
        user_msg = state["user_message"]
        images   = state.get("images", [])

        if not images:
            return user_msg

        vision_description = state.get("vision_description", "")
        if vision_description:
            # 有完整视觉分析时直接附加（足够详细，供下一轮上下文）
            combined = f"{user_msg}\n[图片内容分析]\n{vision_description}" if user_msg.strip() else vision_description
        else:
            # 降级：生成简短占位描述
            model_for_desc = state.get("answer_model") or state["model"]
            img_desc       = await self._describe_images_for_storage(images, model_for_desc)
            placeholder    = f"[用户上传了图片：图片内容大致为{img_desc}]"
            combined       = f"{user_msg}\n{placeholder}" if user_msg.strip() else placeholder

        return combined

    @staticmethod
    async def _describe_images_for_storage(images: list[str], model: str) -> str:
        """
        用视觉 LLM 生成图片内容的简短描述，替代存储/记忆中的原始 base64 数据。
        失败时静默降级，返回通用占位文本。
        """
        try:
            from openai import AsyncOpenAI

            vision_model = VISION_MODEL or model
            content: list = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": img if img.startswith("data:") else f"data:image/jpeg;base64,{img}"
                    },
                }
                for img in images
            ]
            content.append({
                "type": "text",
                "text": "请简短描述图片的主要内容，不超过50个字，直接描述，不要解释。",
            })

            client = AsyncOpenAI(base_url=VISION_BASE_URL, api_key=VISION_API_KEY)
            resp   = await client.chat.completions.create(
                model=vision_model,
                messages=[{"role": "user", "content": content}],
                temperature=0.1,
            )
            return (resp.choices[0].message.content or "").strip() or "图片内容"
        except Exception as exc:
            logger.warning("图片描述生成失败: %s", exc)
            return "图片内容"

    @staticmethod
    def _strip_think_blocks(text: str) -> str:
        # COMPAT: legacy think block parsing — 用正则移除 <think> 标签。
        # 待模型 API 支持 enable_thinking 后，改用结构化 reasoning_content 字段，
        # 届时可移除此方法。
        """移除 <think>...</think> 推理块（qwen3 等模型的思考内容不应存入上下文）。"""
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    @staticmethod
    def _sanitize_for_db(text: str) -> str:
        """移除 PostgreSQL UTF-8 不支持的字符（null 字节等），防止存库失败。"""
        return text.replace("\x00", "").replace("\u0000", "")

    @staticmethod
    def _extract_tool_events(state: GraphState) -> list[dict]:
        """从 messages 中提取工具调用事件列表（用于持久化到 tool_events 表）。"""
        messages = list(state.get("messages", []))
        events   = []
        for m in messages:
            if hasattr(m, "tool_calls") and m.tool_calls:
                for tc in m.tool_calls:
                    name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    if name:
                        events.append({"tool_name": name, "tool_input": args or {}})
        return events

    @staticmethod
    def _build_step_context(state: GraphState) -> str:
        """
        为多步计划构建执行过程摘要，保存到 DB 作为下次对话的上下文。

        只有在计划步骤数 > 1 且有中间步骤结果时才生成，避免单步任务冗余。
        """
        step_results = list(state.get("step_results") or [])
        plan         = state.get("plan", [])

        # 无多步结果或单步任务不生成摘要
        if len(step_results) <= 1 or len(plan) <= 1:
            return ""

        # 中间步骤摘要（不含最后一步，因为最后一步就是 full_response）
        lines: list[str] = []
        for i, result in enumerate(step_results[:-1]):
            title = plan[i]["title"] if i < len(plan) else f"步骤{i + 1}"
            short = result[:200] + ("..." if len(result) > 200 else "")
            lines.append(f"- 步骤{i + 1}（{title}）：{short}")

        if not lines:
            return ""

        return "【执行过程摘要】\n" + "\n".join(lines)

    @staticmethod
    def _build_tool_summary(state: GraphState) -> str:
        """从 messages 中提取工具调用摘要，追加到 AI 回复尾部用于上下文持久化。"""
        messages  = list(state.get("messages", []))
        summaries = []
        for m in messages:
            if hasattr(m, "tool_calls") and m.tool_calls:
                for tc in m.tool_calls:
                    name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    summaries.append(
                        f"- 调用工具: {name}({json.dumps(args, ensure_ascii=False)[:200]})"
                    )
            # ToolMessage：记录工具返回内容摘要
            if type(m).__name__ == "ToolMessage":
                content = str(m.content)[:300]
                summaries.append(f"  结果: {content}")

        if summaries:
            return "【工具调用记录】\n" + "\n".join(summaries[:20])  # 最多 20 条
        return ""

    # ── COMPAT: 模型输出的澄清标记解析（待 system prompt 改用工具调用后移除）────

    _CLAR_START = "[NEED_CLARIFICATION]"
    _CLAR_END   = "[/NEED_CLARIFICATION]"

    @classmethod
    def _is_clarification_response(cls, text: str) -> bool:
        # COMPAT: 检测模型输出中的澄清标记
        return cls._CLAR_START in text

    @classmethod
    def _extract_clarification_from_text(cls, text: str) -> dict | None:
        """
        COMPAT: 从模型输出的 [NEED_CLARIFICATION]...[/NEED_CLARIFICATION] 标记中提取 JSON。
        容错：支持无闭合标签、markdown 包裹、JSON 内嵌等情况。
        """
        start = text.find(cls._CLAR_START)
        if start == -1:
            return None

        after_start = text[start + len(cls._CLAR_START):]
        end_in_after = after_start.find(cls._CLAR_END)
        raw = after_start[:end_in_after].strip() if end_in_after != -1 else after_start.strip()

        # 尝试直接解析
        data = cls._try_parse_clar_json(raw)
        if data:
            return data

        # 容错：用正则提取完整 JSON 对象
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            data = cls._try_parse_clar_json(json_match.group())
            if data:
                return data

        logger.warning("COMPAT 澄清 JSON 解析失败 | raw=%.200s", raw)
        return None

    @staticmethod
    def _try_parse_clar_json(raw: str) -> dict | None:
        """尝试解析澄清 JSON，需含 question + items。"""
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "question" in data and isinstance(data.get("items"), list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        return None
