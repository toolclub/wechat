"""
plan_store：执行计划的 DB 持久化层

职责：
  - create_plan:       planner_node 规划完成后写入 plan_steps 表
  - save_step_result:  reflector_node 步骤完成后保存结果并推进 current_step
  - get_plan:          供调试/未来恢复功能读取计划详情

设计原则：
  - 所有操作均 try/except，失败仅记录日志，不抛异常（不阻断主执行流程）
  - DB 是持久化副本，GraphState.plan 才是运行时权威数据
"""
import logging
import time

from sqlalchemy import select, update as sa_update

from db.database import AsyncSessionLocal
from db.models import PlanStepModel

logger = logging.getLogger("db.plan_store")


async def create_plan(
    plan_id: str,
    conv_id: str,
    goal: str,
    steps: list[dict],
) -> None:
    """
    将 planner 规划结果写入 plan_steps 表。
    全部字段来自 GraphState，不依赖 DB 读取。
    """
    now = time.time()
    try:
        async with AsyncSessionLocal() as session:
            session.add(PlanStepModel(
                id=plan_id,
                conv_id=conv_id,
                goal=goal,
                steps=steps,
                current_step=0,
                total_steps=len(steps),
                created_at=now,
                updated_at=now,
            ))
            await session.commit()
        logger.info(
            "计划已写入DB | plan_id=%s | conv=%s | steps=%d",
            plan_id, conv_id, len(steps),
        )
    except Exception as exc:
        logger.error(
            "写入计划到DB失败（不影响主流程）| plan_id=%s | error=%s",
            plan_id, exc,
        )


async def save_step_result(
    plan_id: str,
    step_index: int,
    result: str,
    new_current_step: int,
) -> None:
    """
    保存步骤执行结果，并将 current_step 推进到下一步索引。
    result 截断到 3000 字符，防止 JSONB 过大。
    """
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(PlanStepModel, plan_id)
            if not row:
                logger.warning("save_step_result: plan_id=%s 不存在", plan_id)
                return

            steps = list(row.steps or [])
            if 0 <= step_index < len(steps):
                steps[step_index] = {
                    **steps[step_index],
                    "status": "done",
                    "result": result[:3000],
                }

            await session.execute(
                sa_update(PlanStepModel)
                .where(PlanStepModel.id == plan_id)
                .values(
                    steps=steps,
                    current_step=new_current_step,
                    updated_at=time.time(),
                )
            )
            await session.commit()
        logger.info(
            "步骤结果已存DB | plan_id=%s | step=%d → next=%d | result_len=%d",
            plan_id, step_index, new_current_step, len(result),
        )
    except Exception as exc:
        logger.error(
            "保存步骤结果失败（不影响主流程）| plan_id=%s | step=%d | error=%s",
            plan_id, step_index, exc,
        )


async def get_plan(plan_id: str) -> dict | None:
    """
    读取计划详情（供调试接口或未来断点续跑功能使用）。
    返回 None 表示 plan_id 不存在或 DB 异常。
    """
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(PlanStepModel, plan_id)
            if not row:
                return None
            return {
                "id":           row.id,
                "conv_id":      row.conv_id,
                "goal":         row.goal,
                "steps":        list(row.steps or []),
                "current_step": row.current_step,
                "total_steps":  row.total_steps,
            }
    except Exception as exc:
        logger.error("读取计划失败 | plan_id=%s | error=%s", plan_id, exc)
        return None
