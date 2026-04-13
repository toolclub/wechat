"""
SemanticCacheNode：语义缓存检查节点

职责：
  - 图的最前置节点，在任何 LLM 调用前检查语义缓存
  - 命中：写入 full_response + cache_hit=True，后续 cache_routing 跳到 save_response
  - 未命中：cache_hit=False，继续正常流程

缓存命名空间策略（由 SEMANTIC_CACHE_NAMESPACE_MODE 配置）：
  "user"   → 每个用户（client_id）独立
  "conv"   → 每个对话独立（最细粒度）
  "prompt" → 同 system prompt 跨用户共享
  "global" → 全局共享
"""
import hashlib
import logging

from config import (
    DEFAULT_SYSTEM_PROMPT,
    SEMANTIC_CACHE_NAMESPACE_MODE,
)
from graph.event_types import CacheHitNodeOutput
from graph.nodes.base import BaseNode
from graph.state import GraphState

logger = logging.getLogger("graph.nodes.cache")


class SemanticCacheNode(BaseNode):
    """语义缓存检查节点：图的第一个执行节点。"""

    @property
    def name(self) -> str:
        return "semantic_cache_check"

    async def execute(self, state: GraphState) -> CacheHitNodeOutput:
        """
        检查当前请求是否命中语义缓存。

        含图片的请求始终跳过缓存（图片内容不参与语义匹配）。
        """
        from cache.factory import get_cache
        from logging_config import get_conv_logger
        from memory import store as memory_store

        user_msg = state["user_message"]
        conv_id = state["conv_id"]
        client_id = state.get("client_id", "")
        clog = get_conv_logger(client_id, conv_id)

        # ── 一次性加载 conversations 行 ──────────────────────────────────────
        # 本节点永远是图的第一个节点（agent.py 里 START 直连到这里），所以
        # 把 system_prompt 的获取统一在这里做，写进 state 后供下游 call_model /
        # save_response 等节点共用，避免一轮对话里多次回查 conversations 表。
        # 只加载 meta（不含 messages），单表一次 SELECT，开销可忽略。
        conv = await memory_store.get_meta(conv_id)
        system_prompt = (conv.system_prompt if conv and conv.system_prompt else "") or ""

        # 强制计划时跳过缓存（用户编辑了执行计划，必须重新执行）
        if state.get("force_plan"):
            clog.info("Cache SKIP  | force_plan 模式，跳过语义缓存")
            return {
                "cache_hit": False,
                "full_response": "",
                "cache_similarity": 0.0,
                "system_prompt": system_prompt,
            }

        # 含图片时跳过缓存
        if state.get("images"):
            clog.info(
                "Cache SKIP  | 含图片请求，跳过语义缓存 | user_msg='%.60s'",
                user_msg,
            )
            return {
                "cache_hit": False,
                "full_response": "",
                "cache_similarity": 0.0,
                "system_prompt": system_prompt,
            }

        namespace = self._derive_cache_namespace(conv, SEMANTIC_CACHE_NAMESPACE_MODE, client_id)
        cache = get_cache()
        result = await cache.lookup(user_msg, namespace)

        if result is None:
            clog.info(
                "Cache MISS  | ns=%s | 未命中，继续正常流程 | user_msg='%.60s'",
                namespace, user_msg,
            )
            return {
                "cache_hit": False,
                "full_response": "",
                "cache_similarity": 0.0,
                "system_prompt": system_prompt,
            }

        clog.info(
            "Cache HIT   | similarity=%.4f | ns=%s | matched='%.60s' | user_msg='%.60s'",
            result.similarity, namespace, result.matched_question, user_msg,
        )
        return {
            "cache_hit": True,
            "full_response": result.answer,
            "cache_similarity": result.similarity,
            "system_prompt": system_prompt,
        }

    @staticmethod
    def _derive_cache_namespace(conv: object, mode: str, client_id: str = "") -> str:
        """
        根据命名空间模式派生缓存 namespace 字符串（旧接口，接收 conv 对象）。

        新代码优先调用模块级 `derive_cache_namespace(system_prompt, conv_id, ...)`，
        不再依赖持有一个完整的 conv ORM 对象。本方法作为适配层保留，内部委托给
        纯函数版本，便于在单元测试中独立使用。
        """
        system_prompt = getattr(conv, "system_prompt", "") if conv else ""
        conv_id       = getattr(conv, "id", "") if conv else ""
        return derive_cache_namespace(system_prompt or "", conv_id or "", mode, client_id)


# ══════════════════════════════════════════════════════════════════════════════
# 模块级纯函数：命名空间派生
# ══════════════════════════════════════════════════════════════════════════════
#
# 设计原因：
#   旧版 _derive_cache_namespace 是 SemanticCacheNode 的 staticmethod，但实现
#   本身不依赖任何节点状态。save_response_node 想复用它就必须 import 整个节点类，
#   而且要构造一个 conv 对象当参数。
#
#   抽出成纯函数后：
#     1. 只依赖标量字段（system_prompt / conv_id / mode / client_id）
#     2. 不需要 ORM 层，写测试方便
#     3. 调用方不再耦合到 SemanticCacheNode，消除模块间循环依赖的风险
#
# 幂等性保证：相同入参永远返回相同 namespace，用于 write-through 缓存的读写对齐。


def derive_cache_namespace(
    system_prompt: str,
    conv_id: str,
    mode: str,
    client_id: str = "",
) -> str:
    """
    根据配置模式把"对话身份 + 用户身份 + 提示词"折叠为一个缓存命名空间字符串。

    "user"   → client_id，每个用户（浏览器）独立，多人系统推荐
    "conv"   → conv_id，每个对话独立（最细粒度，无跨会话复用）
    "global" → "global"，所有用户完全共享
    "prompt" → md5(system_prompt)[:8]，同 prompt 跨用户共享（默认）
    """
    if mode == "user":
        return f"u:{client_id}" if client_id else "u:anon"
    if mode == "conv":
        return conv_id or "global"
    if mode == "global":
        return "global"
    # 默认 "prompt" 模式
    prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    return hashlib.md5(prompt.encode()).hexdigest()[:8]
