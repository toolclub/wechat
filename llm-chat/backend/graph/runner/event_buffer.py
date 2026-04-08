"""
SSE 事件缓冲区：支持流式断点续传

设计：
  - 每个活跃的流式对话在内存中维护一个 EventBuffer
  - 所有 SSE 事件同时写入缓冲区和客户端连接
  - 客户端断开后，图执行继续，事件持续写入缓冲区
  - 客户端重连时，从缓冲区重放遗漏的事件
  - 图执行完成后，保存最终状态到 DB，清理过期缓冲区
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("graph.runner.event_buffer")

_BUFFER_RETENTION_SECS = 300


@dataclass
class EventBuffer:
    """单个会话的 SSE 事件缓冲区。"""
    conv_id: str
    events: list[str] = field(default_factory=list)
    done: bool = False
    error: bool = False
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    # 累积的结构化数据（用于保存 message_details）
    accumulated_content: str = ""
    accumulated_thinking: str = ""
    accumulated_tool_calls: list = field(default_factory=list)
    accumulated_steps: list = field(default_factory=list)
    accumulated_search_results: list = field(default_factory=list)
    # 当前活跃步骤索引（-1 表示无步骤模式，数据直接写入顶层）
    active_step_index: int = -1
    # 停止信号
    stop_event: Optional[asyncio.Event] = field(default=None, repr=False)
    # graph task 引用（用于取消）
    graph_task: Optional[asyncio.Task] = field(default=None, repr=False)
    # 通知等待恢复的客户端
    _waiters: list[asyncio.Event] = field(default_factory=list)

    def append(self, sse_str: str) -> None:
        self.events.append(sse_str)
        for w in self._waiters:
            w.set()

    def get_events_since(self, index: int) -> list[str]:
        if index < 0:
            index = 0
        return self.events[index:]

    def create_waiter(self) -> asyncio.Event:
        ev = asyncio.Event()
        self._waiters.append(ev)
        return ev

    def remove_waiter(self, ev: asyncio.Event) -> None:
        try:
            self._waiters.remove(ev)
        except ValueError:
            pass

    # ── 步骤感知的数据累积 ───────────────────────────────────────────────

    def _current_step(self) -> dict | None:
        """返回当前活跃步骤的数据字典，如果有的话。"""
        if self.active_step_index >= 0 and self.active_step_index < len(self.accumulated_steps):
            return self.accumulated_steps[self.active_step_index]
        return None

    def add_content(self, text: str) -> None:
        step = self._current_step()
        if step is not None:
            step["content"] = step.get("content", "") + text
        else:
            self.accumulated_content += text

    def add_thinking(self, text: str) -> None:
        step = self._current_step()
        if step is not None:
            step["thinking"] = step.get("thinking", "") + text
        else:
            self.accumulated_thinking += text

    def add_tool_call(self, tc: dict) -> None:
        step = self._current_step()
        if step is not None:
            step.setdefault("toolCalls", []).append(tc)
        else:
            self.accumulated_tool_calls.append(tc)

    def find_last_tool(self, name: str, done: bool = False) -> dict | None:
        """查找最后一个指定名称的 tool call（在当前步骤或顶层）。"""
        step = self._current_step()
        tools = step.get("toolCalls", []) if step else self.accumulated_tool_calls
        for tc in reversed(tools):
            if tc["name"] == name and tc.get("done", False) == done:
                return tc
        return None

    def find_last_undone_tool(self, *names: str) -> dict | None:
        """查找最后一个未完成的指定名称工具。"""
        step = self._current_step()
        tools = step.get("toolCalls", []) if step else self.accumulated_tool_calls
        for tc in reversed(tools):
            if tc["name"] in names and not tc.get("done", False):
                return tc
        return None

    def update_steps(self, steps_data: list[dict]) -> None:
        """更新步骤列表，保留已累积的子数据。"""
        for i, s in enumerate(steps_data):
            if i < len(self.accumulated_steps):
                # 更新状态和标题，保留已累积的 toolCalls/thinking/content
                self.accumulated_steps[i]["status"] = s.get("status", "pending")
                self.accumulated_steps[i]["title"] = s.get("title", "")
                if s.get("result") and s.get("status") == "done":
                    self.accumulated_steps[i]["content"] = s["result"]
            else:
                self.accumulated_steps.append({
                    "index": i,
                    "title": s.get("title", ""),
                    "status": s.get("status", "pending"),
                    "toolCalls": [],
                    "thinking": "",
                    "content": s.get("result", ""),
                })
        # 更新活跃步骤索引
        running = next((i for i, s in enumerate(steps_data) if s.get("status") == "running"), -1)
        if running >= 0:
            self.active_step_index = running

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def is_expired(self) -> bool:
        if not self.done:
            return False
        return time.time() - self.completed_at > _BUFFER_RETENTION_SECS


# ── 全局缓冲区注册表 ──────────────────────────────────────────────────────────

_buffers: dict[str, EventBuffer] = {}
_cleanup_task: Optional[asyncio.Task] = None


def get_buffer(conv_id: str) -> Optional[EventBuffer]:
    return _buffers.get(conv_id)


def create_buffer(conv_id: str) -> EventBuffer:
    buf = EventBuffer(conv_id=conv_id)
    _buffers[conv_id] = buf
    _ensure_cleanup_running()
    logger.info("事件缓冲区已创建 | conv=%s", conv_id)
    return buf


def mark_done(conv_id: str, error: bool = False) -> None:
    buf = _buffers.get(conv_id)
    if buf:
        buf.done = True
        buf.error = error
        buf.completed_at = time.time()
        for w in buf._waiters:
            w.set()
        logger.info(
            "事件缓冲区已标记完成 | conv=%s | events=%d | error=%s",
            conv_id, buf.event_count, error,
        )


def remove_buffer(conv_id: str) -> Optional[EventBuffer]:
    return _buffers.pop(conv_id, None)


def is_streaming(conv_id: str) -> bool:
    buf = _buffers.get(conv_id)
    return buf is not None and not buf.done


def get_all_active() -> list[str]:
    return [cid for cid, buf in _buffers.items() if not buf.done]


def stop_stream(conv_id: str) -> None:
    """停止指定会话的流式输出：取消图执行并标记缓冲区完成。"""
    buf = _buffers.get(conv_id)
    if buf:
        if buf.graph_task and not buf.graph_task.done():
            buf.graph_task.cancel()
            logger.info("已取消图执行 | conv=%s", conv_id)
        if buf.stop_event:
            buf.stop_event.set()


def _ensure_cleanup_running() -> None:
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cleanup_loop())


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60)
        expired = [cid for cid, buf in _buffers.items() if buf.is_expired]
        for cid in expired:
            _buffers.pop(cid, None)
            logger.info("已清理过期事件缓冲区 | conv=%s", cid)
        if not _buffers:
            break
