"""
StreamSessionRegistry — 进程内活跃流式会话注册表（OO 封装）

═══════════════════════════════════════════════════════════════════════════════
为什么需要这个类
═══════════════════════════════════════════════════════════════════════════════

历史上 graph/runner/stream.py 暴露一个模块级 `_active_sessions: dict`，main.py
和 stream.py 内部都直接读写。后果：
  1. main.py 必须 `from graph.runner.stream import _active_sessions` 触碰下划
     线开头的"私有"成员，违反 OO 封装。
  2. main.py 还会进一步访问 `session._graph_task.cancel()`，把 StreamSession
     的内部 asyncio.Task 也变成跨模块的"事实公共 API"。
  3. 模块级可变 dict 难以 mock，单元测试要先猴补丁再恢复，容易出错。

本注册表把这些操作封装为有意义的方法（register/get/remove_if/cancel/
is_active），让调用方只关心"取消这个对话的流"而不是"找到 session 然后取消
它的 _graph_task"。同时通过单例 `get_session_registry()` 提供进程级唯一实例。

═══════════════════════════════════════════════════════════════════════════════
作用范围（重要）
═══════════════════════════════════════════════════════════════════════════════

注册表只追踪 **当前 worker 进程内** 的 StreamSession 实例。跨 worker 的
"是否还在生成"判定走 DB（conversations.last_heartbeat_at + status='streaming'，
见 memory.store.is_streaming），跨 worker 的停止信号走 Redis（见
db.redis_state.publish_stop / check_stop）。

也就是说：
  - 注册表 = 本 worker 的实时推送通道 + 取消句柄
  - DB     = 跨 worker 的活跃判定真相源
  - Redis  = 跨 worker 的停止事件广播

三者职责清晰分离，符合 spec.md "永远不信任进程内数据" 原则。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

# 仅类型检查用，运行时不导入，避免循环依赖（StreamSession 也会 import 本模块）
if TYPE_CHECKING:
    from graph.runner.stream import StreamSession

logger = logging.getLogger("graph.runner.session_registry")


class StreamSessionRegistry:
    """
    进程内活跃 StreamSession 注册表。

    线程模型：FastAPI/uvicorn 工作模式下所有协程跑在同一个事件循环里，
    dict 的读写不需要锁。如果将来切换到多线程模型再加 threading.Lock。
    """

    def __init__(self) -> None:
        # conv_id → StreamSession（仅本 worker 内）
        # 使用 dict 而非 OrderedDict：流式会话生命周期短（秒～分钟），
        # 不存在 LRU 淘汰需求，正常路径下 register/remove 配对清理。
        self._sessions: dict[str, "StreamSession"] = {}

    # ── 注册 / 注销 ────────────────────────────────────────────────────────────

    def register(self, conv_id: str, session: "StreamSession") -> None:
        """
        把会话挂到注册表上。stream() 在初始化完心跳后调用一次。

        若同一 conv_id 已有旧 session（极少见，理论上 main.py 在新建前会先
        cancel 旧的），直接覆盖并落 warning，便于排查重复入口。
        """
        if conv_id in self._sessions:
            logger.warning(
                "重复注册 conv=%s，旧 session 将被覆盖（可能存在并发请求未取消）",
                conv_id,
            )
        self._sessions[conv_id] = session

    def remove_if(self, conv_id: str, session: "StreamSession") -> None:
        """
        条件式注销：只在注册表里存的还是 `session` 本身时才移除。

        这是为了避免一个常见竞态：旧 session 的 finally 清理与新 session 的
        register 顺序错乱时，旧 session 可能误删新 session。调用方传入自己
        的引用做身份比对就能彻底防止。
        """
        if self._sessions.get(conv_id) is session:
            self._sessions.pop(conv_id, None)

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def get(self, conv_id: str) -> Optional["StreamSession"]:
        """获取本 worker 内该对话的活跃会话。返回 None 表示不在本 worker。"""
        return self._sessions.get(conv_id)

    def is_active(self, conv_id: str) -> bool:
        """本 worker 是否正在处理该对话（仅本进程视图，跨 worker 请用 DB 判定）。"""
        return conv_id in self._sessions

    # ── 取消 ──────────────────────────────────────────────────────────────────

    def cancel(self, conv_id: str) -> bool:
        """
        请求取消本 worker 内该对话的图执行任务。

        返回 True 表示找到并发起了 cancel；False 表示本 worker 没有该会话
        （此时调用方应该已经通过 Redis publish_stop 通知所有 worker）。

        注意：cancel 只是把信号送到 graph_task，真正的清理流程由 StreamSession
        自己在 _consume_events 的 finally 里完成。本方法不等待清理结束。
        """
        session = self._sessions.get(conv_id)
        if session is None:
            return False

        # 通过 stop_event 优雅停止（图执行循环每个 step 都检查这个事件）
        if session.stop_event is not None and not session.stop_event.is_set():
            session.stop_event.set()

        # 同时硬取消 graph_task，覆盖图正卡在 LLM 流式 IO 等不响应 stop_event 的情况
        task = session._graph_task  # 注册表是 stream.py 的"友元"，允许访问内部任务
        if task is not None and not task.done():
            task.cancel()

        logger.info("注册表已请求取消 conv=%s（本 worker）", conv_id)
        return True

    # ── 调试 ──────────────────────────────────────────────────────────────────

    def active_count(self) -> int:
        """当前 worker 内的活跃会话数量（用于监控/健康检查）。"""
        return len(self._sessions)


# ═══════════════════════════════════════════════════════════════════════════════
# 单例（Singleton 模式）
# ═══════════════════════════════════════════════════════════════════════════════
#
# 进程内只需要一个注册表。没有用 metaclass / __new__ 的"硬"单例，因为：
#   1. 显式工厂函数 get_session_registry() 比隐式更易测试
#   2. 单元测试可以通过 reset_session_registry() 拿到干净实例
#   3. 没有继承单例的需求

_registry: StreamSessionRegistry | None = None


def get_session_registry() -> StreamSessionRegistry:
    """返回进程内唯一的注册表实例（懒初始化）。"""
    global _registry
    if _registry is None:
        _registry = StreamSessionRegistry()
    return _registry


def reset_session_registry() -> None:
    """仅供测试使用：清空单例，让下次 get 拿到全新实例。"""
    global _registry
    _registry = None
