"""
计划步骤状态机 — 管理单个执行步骤的生命周期

状态流转图：
    PENDING ──start──→ RUNNING ──finish──→ DONE
                                ──fail────→ FAILED

使用方式：
    sm = PlanStepSM()
    sm.start()              # pending → running
    sm.finish()             # running → done
    print(sm.current_value) # "done"

    sm = PlanStepSM.from_db_status("running")
    sm.fail()               # running → failed
"""
from __future__ import annotations

import logging
from statemachine import StateMachine, State

logger = logging.getLogger("statemachine.plan_step")


class PlanStepSM(StateMachine):
    """计划步骤生命周期状态机。"""

    # ── 状态定义 ──
    pending = State(initial=True)
    running = State()
    done = State(final=True)
    failed = State(final=True)

    # ── 转换定义 ──
    start = pending.to(running)
    finish = running.to(done)
    fail = running.to(failed)

    @property
    def current_value(self) -> str:
        """当前状态的字符串值（用于写 DB）。"""
        return self.current_state_value

    @classmethod
    def from_db_status(cls, status: str) -> PlanStepSM:
        """从 DB 中的 status 字符串恢复状态机实例。"""
        valid = {"pending", "running", "done", "failed"}
        start = status if status in valid else "pending"
        return cls(start_value=start)

    def send_event(self, target_status: str) -> str:
        """
        根据目标状态自动选择转换事件。

        返回转换后的状态字符串。非法转换抛 TransitionNotAllowed。
        """
        transition_map: dict[str, str] = {
            "running": "start",
            "done": "finish",
            "failed": "fail",
        }
        event_name = transition_map.get(target_status)
        if not event_name:
            logger.warning("步骤状态转换无效: %s → %s", self.current_value, target_status)
            return self.current_value

        getattr(self, event_name)()
        return self.current_value
