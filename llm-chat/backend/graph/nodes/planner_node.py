"""
PlannerNode：任务规划节点

职责：
  - 分析用户请求，生成结构化执行计划（步骤列表）
  - 仅对 search / search_code 路由（或无路由模式）触发规划
  - 读取 state["vision_description"]（由 VisionNode 预生成）作为图片内容输入，
    避免重复调用视觉模型
  - 三层兜底：重试拿非空内容 → 解析 JSON → 单步兜底

硬性限制：计划最多 3 步，防止步骤过多触发 nginx 超时。
"""
import json
import logging
import re
import uuid
from datetime import date

from config import SEARCH_MODEL, VISION_MODEL
from graph.event_types import PlannerNodeOutput
from graph.nodes.base import BaseNode
from graph.state import GraphState, PlanStep
from llm.chat import get_chat_llm

logger = logging.getLogger("graph.nodes.planner")

def _fix_json_inner_quotes(text: str) -> str:
    """
    修复 JSON 字符串值内的裸 ASCII 双引号。

    模型有时在字段值中用双引号包裹词语（如 "百业"），
    导致 json.loads 报 'Expecting comma' 错误。

    策略：状态机逐字符扫描，进入字符串后若遇到双引号，
    检查其后紧跟的字符——若不是 JSON 结构字符（, } ] :），
    则认为是内部装饰引号，替换为单引号。
    """
    result: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        c = text[i]
        if c == '\\' and in_string:
            # 转义序列，原样保留
            result.append(c)
            i += 1
            if i < len(text):
                result.append(text[i])
            i += 1
            continue
        if c == '"':
            if not in_string:
                in_string = True
                result.append(c)
            else:
                # 判断是字符串结束引号，还是值内部的裸双引号
                # 字符串结束后，下一个非空字符必然是 , } ] :（JSON 结构符）
                j = i + 1
                while j < len(text) and text[j] in (' ', '\t', '\n', '\r'):
                    j += 1
                next_ch = text[j] if j < len(text) else ''
                if next_ch in (',', '}', ']', ':'):
                    # 合法的字符串结束引号
                    in_string = False
                    result.append(c)
                else:
                    # 内部裸引号，替换为单引号
                    result.append("'")
        else:
            result.append(c)
        i += 1
    return ''.join(result)


# ── 今日日期（构建时固定，进程生命周期内不变） ─────────────────────────────────
_TODAY = date.today().strftime("%Y年%m月%d日")

_PLANNER_SYSTEM = f"""你是一个任务规划专家。分析用户的请求，制定清晰的执行计划。
当前日期：{_TODAY}。搜索时直接用核心关键词，不要手动添加年份。
要求：
- 将任务分解为若干个具体可执行的步骤
- 每步有明确的操作（搜索信息、获取数据、计算、分析、撰写等）
- 步骤间有逻辑顺序，后一步依赖前一步的结果
- 如果任务很简单只需一步操作，就只列 1 个步骤
- 【最后一步原则】如果用户最终需要获得某个产品（网页、完整代码、分析报告等），
  最后一步必须是"直接输出该产品的完整内容（代码/HTML/文档）"；
  不能用"规划结构"、"设计架构"、"制定方案"等描述性步骤代替；
  前面的步骤专门负责收集或分析所需信息，最后步才是生成

输出格式（JSON）：
{{"steps": [{{"title": "简短标题（10字以内）", "description": "具体描述（说明要做什么、搜索什么）"}}]}}

只输出 JSON，不要任何解释。"""

# 每步最多计划步数（stream.py recursion_limit=120，每步约4节点，10步≈45节点，远低于上限）
_MAX_PLAN_STEPS = 10


class PlannerNode(BaseNode):
    """任务规划节点：将搜索类请求分解为步骤化执行计划。"""

    @property
    def name(self) -> str:
        return "planner"

    # ── 触发复杂代码规划的关键信号 ─────────────────────────────────────────────
    _COMPLEX_CODE_SIGNALS = frozenset([
        "然后", "接着", "之后", "最后", "第一步", "第二步", "首先",
        "分析", "比较", "调研", "研究", "写一篇", "写一份", "制定",
        "重构", "优化", "分多步", "分阶段", "步骤",
    ])
    # 超过此长度的 code 任务视为复杂，触发规划
    _COMPLEX_CODE_LENGTH = 150

    @classmethod
    def _needs_planning(cls, route: str, user_msg: str) -> bool:
        """
        判断当前请求是否需要规划。

        - search / search_code 路由：始终规划
        - code 路由：消息过长或含多步信号时规划（复杂编程任务）
        - chat 路由：不规划（直接对话响应更自然）
        - 未指定路由：规划（保守策略）
        """
        if not route or route in ("search", "search_code"):
            return True
        if route == "code":
            is_long      = len(user_msg.strip()) > cls._COMPLEX_CODE_LENGTH
            has_signals  = any(sig in user_msg for sig in cls._COMPLEX_CODE_SIGNALS)
            return is_long or has_signals
        # chat 路由不规划
        return False

    # ── 续写信号词（用户想继续被中断的任务）──────────────────────────────────────
    _CONTINUATION_WORDS = frozenset([
        "继续", "continue", "接着", "接着写", "接着做", "接上",
        "继续写", "继续做", "继续完成", "接着完成",
    ])

    @classmethod
    def _is_continuation(cls, user_msg: str) -> bool:
        """判断用户是否在要求续写上次被中断的任务。"""
        return user_msg.strip() in cls._CONTINUATION_WORDS

    async def _try_resume_from_db(self, state: GraphState) -> PlannerNodeOutput | None:
        """
        从 DB 加载上次计划，直接跳到第一个未完成步骤。

        返回值：
          - 成功恢复 → 返回 PlannerNodeOutput（plan / plan_goal / current_step_index / step_results）
          - 无可恢复计划 → 返回 None（调用方回退到正常规划流程）
        """
        conv_id = state.get("conv_id", "")
        try:
            from db.plan_store import get_latest_plan_for_conv
            db_plan = await get_latest_plan_for_conv(conv_id)
        except Exception as exc:
            logger.warning("续写：读取 DB 计划失败: %s", exc)
            return None

        if not db_plan:
            return None

        steps_raw = db_plan.get("steps", [])
        if not steps_raw:
            return None

        # 重建运行时 PlanStep 列表，done 的步骤带上 result
        plan: list[PlanStep] = []
        for s in steps_raw:
            plan.append(PlanStep(
                id=s.get("id", ""),
                title=s.get("title", ""),
                description=s.get("description", ""),
                status=s.get("status", "pending"),
                result=s.get("result", ""),
            ))

        # 找第一个未完成步骤
        resume_idx = None
        for i, step in enumerate(plan):
            if step["status"] != "done":
                resume_idx = i
                break

        if resume_idx is None:
            # 所有步骤已完成，无需续写
            logger.info("续写：计划所有步骤已完成 | conv=%s | plan_id=%s", conv_id, db_plan.get("id"))
            return None

        # 当前步骤可能有部分结果（崩溃时 _save_partial_plan_step 写入的）
        # 将其保留在 plan step 中，供 _build_focused_step_messages 构建续写上下文
        partial_result = plan[resume_idx].get("result", "")

        # 把续写点标为 running（保留 partial result）
        plan[resume_idx] = {**plan[resume_idx], "status": "running"}

        # step_results 从已完成步骤的 result 中重建
        step_results = [
            plan[i]["result"]
            for i in range(resume_idx)
            if plan[i].get("result")
        ]

        goal = db_plan.get("goal", state.get("user_message", ""))
        logger.info(
            "续写：从 DB 恢复计划 | conv=%s | plan_id=%s | resume_step=%d/%d | "
            "partial_result_len=%d | goal=%.60s",
            conv_id, db_plan.get("id"), resume_idx + 1, len(plan),
            len(partial_result), goal,
        )

        return {
            "plan":               plan,
            "plan_id":            db_plan.get("id", ""),
            "plan_goal":          goal,
            "current_step_index": resume_idx,
            "step_iterations":    0,
            "step_results":       step_results,
        }

    async def execute(self, state: GraphState) -> PlannerNodeOutput:
        """
        规划执行步骤。

        search / search_code 路由始终规划；
        code 路由在任务复杂时触发规划；
        chat 路由直接返回空计划（自然对话）。

        续写检测：用户发"继续"时，优先从 DB 恢复上次中断的计划，
        跳过已完成步骤，直接从断点处重新执行，无需重跑步骤 1、2。
        """
        route    = state.get("route", "")
        user_msg = state.get("user_message", "")

        # ── 续写检测：优先从 DB 恢复中断计划 ──────────────────────────────────
        # 用户说"继续"时，先尝试找上次未完成的计划，直接跳到断点步骤执行，
        # 避免重新规划和重复搜索，节省时间和 API 费用。
        if self._is_continuation(user_msg):
            resumed = await self._try_resume_from_db(state)
            if resumed:
                return resumed
            # 无可恢复计划 → 回退到普通流程（让模型自由续写）

        if not self._needs_planning(route, user_msg):
            return {
                "plan":               [],
                "plan_goal":          "",
                "current_step_index": 0,
                "step_iterations":    0,
                "step_results":       [],
            }

        images      = state.get("images", [])
        vision_desc = state.get("vision_description", "")

        # ── 规划模型选择 ────────────────────────────────────────────────────
        # 若路由分配的模型是视觉模型（仅在 VISION_BASE_URL 上存在），
        # 规划模型必须切换到主接口上的模型，否则无法访问。
        model = state.get("tool_model") or state["model"]
        if model == (VISION_MODEL or "") or not model:
            model = SEARCH_MODEL or state["model"]

        # ── 网页澄清预检（search_code 路由兼容方案） ────────────────────────
        # 问题背景：call_model_node 的澄清检查依赖 `not plan` 条件，
        # 而 search_code 路由会在 call_model 之前由本节点生成计划，
        # 导致 `not plan` 为 False，澄清被跳过。
        # 解决方案：在此处提前拦截，返回空计划，
        # call_model 看到 `not plan=True` 后会自然触发澄清卡片。
        #
        # 有图片时不拦截：图片本身就是用户提供的视觉风格参考，无需再追问。
        from graph.nodes.call_model_node import _needs_webpage_clarification
        if not images and _needs_webpage_clarification(user_msg):
            logger.info(
                "Planner 网页澄清预检命中，返回空计划以触发澄清 | model=%s | user_msg=%.60s",
                model, user_msg,
            )
            return {
                "plan":               [],
                "current_step_index": 0,
                "step_iterations":    0,
            }

        llm = get_chat_llm(model=model, temperature=0.1)

        # ── 构建规划输入 ────────────────────────────────────────────────────
        # 优先使用 vision_description（已由 VisionNode 生成），
        # 避免此处重复调用视觉模型（原 planner 内联的 Ollama 调用已移至 VisionNode）
        if images:
            if vision_desc:
                planning_msg = (
                    f"[图片内容分析]\n{vision_desc}\n\n"
                    f"[用户请求]\n{user_msg}"
                )
            else:
                planning_msg = (
                    f"[用户附带了 {len(images)} 张图片，内容无法解析]\n"
                    f"用户请求：{user_msg}"
                )
        else:
            planning_msg = user_msg

        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user",   "content": planning_msg},
        ]

        # ── 层 1：流式调用，逐 token 推送 thinking 事件给前端 ──────────────
        from langchain_core.callbacks.manager import adispatch_custom_event
        from logging_config import log_prompt
        log_prompt(state.get("conv_id", ""), "planner", model, messages)

        _THINK_PREFIX = "\x00THINK\x00"
        content = ""
        for attempt in range(3):
            content_parts: list[str] = []
            try:
                async for delta in llm.astream(messages, temperature=0.1):
                    if delta.startswith(_THINK_PREFIX):
                        thinking_text = delta[len(_THINK_PREFIX):]
                        await adispatch_custom_event(
                            "llm_thinking", {"content": thinking_text, "node": "planner"},
                        )
                    else:
                        content_parts.append(delta)
                        await adispatch_custom_event(
                            "llm_thinking", {"content": delta, "node": "planner"},
                        )
            except Exception as exc:
                logger.warning(
                    "Planner 流式调用异常 [第%d/3次] | error=%s", attempt + 1, exc,
                )
                continue
            raw = "".join(content_parts)
            content = raw.strip()
            logger.info(
                "Planner 原始响应 [第%d次] | model=%s | len=%d | raw='%.200s'",
                attempt + 1, model, len(raw), raw,
            )
            if content:
                break
            logger.warning(
                "Planner 返回空内容 [第%d/3次] | model=%s",
                attempt + 1, model,
            )

        # ── 层 2：从响应中提取并解析 JSON ───────────────────────────────────
        plan_steps: list[PlanStep] = []
        try:
            if not content:
                raise ValueError("三次重试后仍返回空内容")

            # 去除 markdown code block
            if "```" in content:
                for part in content.split("```"):
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    if part.startswith("{"):
                        content = part
                        break

            # 按 { } 定位 JSON 对象（兼容前后有说明文字）
            start = content.find("{")
            end   = content.rfind("}") + 1
            if start != -1 and end > start:
                content = content[start:end]

            # 容错：模型有时在字符串值内用 ASCII 双引号包裹词语（如 "百业"），
            # 这会导致 JSON 解析失败。将 JSON 字符串值内的裸双引号替换为单引号。
            content = _fix_json_inner_quotes(content)

            logger.info("Planner JSON 提取后 | extracted='%.300s'", content)
            data = json.loads(content)

            for i, s in enumerate(data.get("steps", [])):
                plan_steps.append(PlanStep(
                    id=str(i + 1),
                    title=s.get("title", f"步骤 {i + 1}"),
                    description=s.get("description", ""),
                    status="pending",
                    result="",
                ))

            # 限制最多 _MAX_PLAN_STEPS 步
            plan_steps = plan_steps[:_MAX_PLAN_STEPS]
            logger.info(
                "Planner 解析成功 | steps=%d | titles=%s",
                len(plan_steps),
                [s["title"] for s in plan_steps],
            )

        except Exception as e:
            # ── 层 3：兜底单步 ──────────────────────────────────────────────
            logger.warning(
                "Planner JSON 解析失败，使用单步兜底 | error=%s | model=%s | content='%.300s'",
                e, model, content,
            )
            plan_steps = [PlanStep(
                id="1",
                title="执行任务",
                description=user_msg,
                status="pending",
                result="",
            )]

        # 第一步标记为 running
        if plan_steps:
            plan_steps[0] = {**plan_steps[0], "status": "running"}

        # ── 持久化计划到 DB（非阻断，失败仅记录日志） ──────────────────────────
        plan_id = ""
        if plan_steps:
            # 始终持久化，单步计划也保存，供前端刷新后恢复认知面板
            plan_id = str(uuid.uuid4())
            vision_desc = state.get("vision_description", "")
            goal = (
                f"{user_msg}\n\n[图片内容]\n{vision_desc}"
                if vision_desc else user_msg
            )
            steps_for_db = [
                {
                    "id":          s["id"],
                    "title":       s["title"],
                    "description": s["description"],
                    "status":      "pending",
                    "result":      "",
                }
                for s in plan_steps
            ]
            try:
                from db.plan_store import create_plan
                await create_plan(
                    plan_id=plan_id,
                    conv_id=state.get("conv_id", ""),
                    goal=goal,
                    steps=steps_for_db,
                )
            except Exception as exc:
                logger.error("写入 plan_steps DB 失败: %s", exc)
                plan_id = ""  # 降级：后续节点用 GraphState 内存方案

        return {
            "plan":               plan_steps,
            "plan_id":            plan_id,
            "plan_goal":          user_msg,
            "current_step_index": 0,
            "step_iterations":    0,
            "step_results":       [],
        }
