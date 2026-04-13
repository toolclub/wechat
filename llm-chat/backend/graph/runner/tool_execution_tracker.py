"""
ToolExecutionTracker — 多工具并行执行的状态追踪器（OO 拆分自 StreamSession）

═══════════════════════════════════════════════════════════════════════════════
职责
═══════════════════════════════════════════════════════════════════════════════

模型可能在一次 step 内连续触发多个工具调用（典型如先 search 再 fetch_webpage），
甚至并行触发（LangGraph 的 ToolNode 支持）。每个工具有：
  - 一个 sequence_number（本会话内严格递增）
  - 一个 tool_executions 表里的 DB 行 id（INSERT 后回填）
  - 累积的 sandbox 终端输出
  - 累积的搜索结果列表

原 StreamSession 用 5 个裸字段管理这些状态：
    _tool_seq, _current_tool_seq,
    _tool_exec_map, _tool_output_map, _tool_search_map

跨 _track_sse_for_db 多个分支读写，状态机不清晰、加新字段易出错。本类把
"启动 → 累积 → 完成"流程封装成 5 个语义方法，调用方只需调方法名而不是
直接操作 dict。

═══════════════════════════════════════════════════════════════════════════════
sequence_number 的作用
═══════════════════════════════════════════════════════════════════════════════

工具的 sequence_number 不仅是 DB 主键去重用，还和 plan_step 关联：
tool_executions.step_index 记录工具属于哪个计划步骤，前端刷新时通过
(step_index, sequence_number) 精确分发工具到对应步骤的卡片下。

因此本类的 next_seq() 必须在 start_tool() 内原子完成：分配 seq → INSERT
→ 设为 current_seq。中间不能 await 其他逻辑。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("graph.runner.tool_execution_tracker")


class ToolExecutionTracker:
    """单个 StreamSession 内的并行工具状态追踪。"""

    def __init__(self, conv_id: str, message_id: str) -> None:
        """
        Args:
            conv_id: 对话 ID
            message_id: 当前 assistant 消息业务 ID（关联 tool_executions.message_id）
        """
        self.conv_id = conv_id
        self.message_id = message_id

        # 全会话内的 sequence_number 计数器（不复位，跨 step 持续递增）
        self._seq_counter: int = 0

        # 当前活跃工具的 seq —— 由最近一次 tool_call 设置，sandbox_output /
        # search_item 事件按这个 seq 累积到对应 buffer。
        # 设计简化：模型一般串行调用，并行 tool_call 时此值会切换到最新的，
        # 较早工具的 sandbox_output 会落到较新工具的 buffer 上。这是已知的
        # tradeoff —— 真正的并行多工具事件流分流需要事件本身带 seq tag，
        # 当前模型 API 还不普遍支持。
        self._current_seq: int = 0

        # seq → tool_executions 表的自增主键（INSERT 后回填）
        self._exec_id_map: dict[int, int] = {}
        # seq → 累积的 sandbox 终端输出（process stdout/stderr 拼接）
        self._output_map: dict[int, str] = {}
        # seq → 搜索结果列表（web_search / search_code 工具）
        self._search_map: dict[int, list[dict]] = {}

    # ── 状态查询 ─────────────────────────────────────────────────────────────

    @property
    def current_seq(self) -> int:
        """当前活跃工具的 sequence_number（0 表示尚无工具运行）。"""
        return self._current_seq

    # ── 启动一个工具 ─────────────────────────────────────────────────────────

    async def start_tool(
        self,
        tool_name: str,
        tool_input: dict,
        step_index: Optional[int] = None,
    ) -> int:
        """
        创建一条 tool_executions 记录（status=running），返回新分配的 seq。

        Args:
            tool_name: 工具名（如 "web_search"）
            tool_input: 工具入参（写入 tool_executions.tool_input JSONB）
            step_index: 所属计划步骤（0-based），无计划时传 None

        Returns:
            新分配的 sequence_number。即使 INSERT 失败也会返回一个 seq，
            只是 _exec_id_map 里没有对应 db_id（complete_tool 会跳过 UPDATE）。
        """
        self._seq_counter += 1
        seq = self._seq_counter
        self._current_seq = seq
        self._output_map[seq] = ""
        self._search_map[seq] = []

        try:
            from db.tool_store import create_tool_execution
            exec_id = await create_tool_execution(
                conv_id=self.conv_id,
                message_id=self.message_id,
                tool_name=tool_name,
                tool_input=tool_input,
                sequence_number=seq,
                step_index=step_index,
            )
            self._exec_id_map[seq] = exec_id
        except Exception as exc:
            # spec 铁律 #9：tool_executions INSERT 失败必须落日志。
            # 历史教训（spec.md 已知坑）：一次 ToolExecutionStatus 重构把异常
            # 静默吞了，导致整个会话的工具记录都没写 DB，刷新后终端全部消失。
            logger.warning("tool_execution 创建失败 conv=%s tool=%s seq=%d: %s",
                           self.conv_id, tool_name, seq, exc)

        return seq

    # ── 累积输出 / 搜索结果（按当前活跃 seq） ────────────────────────────────

    def append_output(self, text: str) -> None:
        """把一段 sandbox 终端输出累积到当前活跃工具的 buffer。"""
        if not text:
            return
        seq = self._current_seq
        if seq in self._output_map:
            self._output_map[seq] += text

    def append_search_item(self, item: dict) -> None:
        """把一条搜索结果累积到当前活跃工具的 buffer。"""
        seq = self._current_seq
        if seq in self._search_map:
            self._search_map[seq].append({
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "status": item.get("status", "done"),
            })

    # ── 完成工具（写最终状态） ───────────────────────────────────────────────

    async def finish_tool(
        self,
        raw_status: str,
        fallback_output: str = "",
    ) -> None:
        """
        把当前活跃工具标记完成，写入最终状态和累积输出。

        Args:
            raw_status: 工具上报的原始状态（"done"/"error"/"timeout" 等）。
                内部走 ToolExecutionSM 状态机校验后才落 DB（spec 铁律 #7）。
            fallback_output: 若没有累积到任何 sandbox 输出，用这个作为
                tool_output 字段（一般是工具直接 return 的字符串结果）。
        """
        seq = self._current_seq
        exec_id = self._exec_id_map.get(seq, 0)
        if not exec_id:
            # INSERT 当时就失败了，没有 DB 行可更新；清理本地 buffer 避免泄漏。
            self._cleanup_seq(seq)
            return

        output = self._output_map.get(seq, "") or fallback_output
        search_items = self._search_map.get(seq) or None

        # spec 铁律 #7：状态变更走状态机，不直接写裸字符串
        from fsm.tool_execution import ToolExecutionSM
        tool_sm = ToolExecutionSM()
        try:
            tool_sm.send_event(raw_status)
        except Exception as exc:
            logger.warning("ToolExecutionSM 状态转换失败 raw=%s: %s", raw_status, exc)
        status = tool_sm.current_value

        try:
            from db.tool_store import complete_tool_execution
            await complete_tool_execution(
                exec_id,
                output=output[:20000],  # 截断避免单条 tool_output 过大
                status=status,
                search_items=search_items,
            )
        except Exception as exc:
            logger.warning("tool_execution 完成失败 conv=%s exec_id=%s: %s",
                           self.conv_id, exec_id, exc)

        self._cleanup_seq(seq)

    # ── 内部清理 ─────────────────────────────────────────────────────────────

    def _cleanup_seq(self, seq: int) -> None:
        """工具完成后清理它在三个 map 中的条目，避免长会话内存增长。"""
        self._exec_id_map.pop(seq, None)
        self._output_map.pop(seq, None)
        self._search_map.pop(seq, None)
