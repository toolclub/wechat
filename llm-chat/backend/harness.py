"""
Agent Harness（代理总线）
将全部 9 层连接起来，向 main.py 暴露一个统一的外观接口。

层级映射（类比操作系统）：
  1. Prompt      → layers.prompt        （人格 / 提示模板）
  2. Capability  → layers.capability    （工具：模型列表、嵌入向量）
  3. Memory      → layers.memory        （数据结构：Message、Conversation）
  4. Runtime     → layers.runtime       （代理循环：流式 / 同步调用）
  5. State       → layers.state         （工作记忆：进程内存储）
  6. Context     → layers.context       （消息组装 + 压缩触发）
  7. Persistence → layers.persistence   （磁盘检查点：保存/加载/删除）
  8. Verification→ layers.verification  （日志 / 可观测性）
  9. Extension   → layers.extension     （在 main.py 中应用：CORS、插件）
"""
from typing import Optional, AsyncGenerator

from config import SUMMARY_MODEL, LONGTERM_MEMORY_ENABLED
from layers.memory import Conversation, Message
from layers.state import StateManager
from layers import context, persistence, prompt, verification
from layers.runtime import stream as _runtime_stream, call_sync
from layers import longterm


class AgentHarness:
    def __init__(self):
        # 第 5 层 – State：工作记忆
        self.state = StateManager()
        # 第 7 层 – Persistence：启动时从磁盘恢复检查点
        self.state.load_from(persistence.load_all())

    # ── 对话 CRUD ──────────────────────────────────────────────────────────

    def create_conversation(
        self,
        conv_id: str,
        title: str = "新对话",
        system_prompt: str = "",
    ) -> Conversation:
        conv = Conversation(
            id=conv_id,
            title=title,
            system_prompt=prompt.ensure_system_prompt(system_prompt),  # 第 1 层
        )
        self.state.set(conv)           # 第 5 层
        persistence.save(conv)         # 第 7 层
        return conv

    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        return self.state.get(conv_id)  # 第 5 层

    def list_conversations(self) -> list[dict]:
        return sorted(
            [
                {"id": c.id, "title": c.title, "updated_at": c.updated_at}
                for c in self.state.all()
            ],
            key=lambda x: x["updated_at"],
            reverse=True,
        )

    def delete_conversation(self, conv_id: str) -> None:
        self.state.remove(conv_id)      # 第 5 层
        persistence.delete(conv_id)     # 第 7 层

    def add_message(self, conv_id: str, role: str, content: str) -> None:
        conv = self.state.get(conv_id)
        if not conv:
            return
        conv.messages.append(Message(role=role, content=content))  # 第 3 层
        if conv.title == "新对话" and role == "user":
            conv.title = content[:30] + ("..." if len(content) > 30 else "")
        persistence.save(conv)          # 第 7 层

    @staticmethod
    def _save(conv: Conversation) -> None:
        """兼容性封装——直接调用持久化保存（供 PATCH 接口使用）。"""
        persistence.save(conv)          # 第 7 层

    # ── 上下文组装（第 6 层）──────────────────────────────────────────────

    @staticmethod
    def gen_chat_msg(
        conv: Conversation,
        long_term_memories: list[str] | None = None,
        forget_mode: bool = False,
    ) -> list[dict]:
        return context.build_messages(conv, long_term_memories, forget_mode)

    # ── 长期记忆（第 3b 层）──────────────────────────────────────────────

    async def search_long_term(self, conv_id: str, query: str) -> list[str]:
        """检索与 query 最相关的历史 Q&A 对。LONGTERM_MEMORY_ENABLED=False 时直接返回空。"""
        if not LONGTERM_MEMORY_ENABLED:
            return []
        return await longterm.search_memories(conv_id, query)

    async def should_forget(
        self, conv_id: str, query: str, long_term: list[str]
    ) -> bool:
        """
        判断是否触发忘记模式：RAG 未命中 且 话题与历史不相关。
        - 有摘要：比较 query 与摘要的余弦相似度
        - 无摘要：比较 query 与最近几轮用户消息的平均余弦相似度（压缩前的早期阶段）
        忘记时上下文只发最近 SHORT_TERM_FORGET_TURNS 轮，不注入摘要和长期记忆。
        LONGTERM_MEMORY_ENABLED=False 时仍可用摘要和近期消息做相似度判断。
        """
        if long_term:
            return False  # RAG 命中，话题相关，正常流程
        conv = self.state.get(conv_id)
        if not conv:
            return False
        if conv.mid_term_summary:
            # 有摘要：与摘要比较
            relevant = await longterm.is_relevant_to_summary(query, conv.mid_term_summary)
        else:
            # 无摘要（压缩前）：与最近 2 条用户消息比较
            # conv.messages[-1] 是本轮刚加入的 user，[:-1] 排除它，[-2:] 取前2条
            recent = [m.content for m in conv.messages if m.role == "user"][:-1][-2:]
            if not recent:
                return False  # 历史不足，无法判断，不忘记
            relevant = await longterm.is_relevant_to_recent(query, recent)
        return not relevant

    async def _batch_store_long_term(
        self, conv_id: str, messages: list[Message], base_idx: int
    ) -> None:
        """压缩时将待摘要的消息对批量写入 Qdrant。LONGTERM_MEMORY_ENABLED=False 时跳过。"""
        if not LONGTERM_MEMORY_ENABLED:
            return
        i = 0
        while i + 1 < len(messages):
            if messages[i].role == "user" and messages[i + 1].role == "assistant":
                await longterm.store_pair(
                    conv_id,
                    messages[i].content,
                    messages[i + 1].content,
                    base_idx + i,
                )
            i += 2

    # ── 运行时：流式对话（第 4 层）────────────────────────────────────────

    @staticmethod
    async def chat_stream(
            model: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        verification.log_chat("stream", model)  # 第 8 层
        async for chunk in _runtime_stream(model=model, messages=messages, temperature=temperature):
            yield chunk

    # ── 上下文压缩（第 6 + 4 + 3 + 1 层）─────────────────────────────────

    async def maybe_compress(self, conv_id: str) -> bool:
        conv = self.state.get(conv_id)
        if not conv or not context.should_compress(conv):   # 第 6 层
            return False

        # 第 6 层 – Context：确定需要摘要的新消息（游标 → 滑动窗口起点）
        to_summarise, new_cursor = context.slice_for_compression(conv)
        if not to_summarise:
            return False

        # 第 3b 层 – 压缩触发时批量写入长期记忆（替代每轮写入）
        await self._batch_store_long_term(conv_id, to_summarise, conv.mid_term_cursor)

        # 第 1 层 – Prompt：构建摘要提示模板
        history_text = "\n".join(
            f"{'用户' if m.role == 'user' else 'AI'}: {m.content}"
            for m in to_summarise
        )
        compress_messages = prompt.build_summary_messages(history_text, conv.mid_term_summary)
        print(compress_messages)
        # 第 4 层 – Runtime：同步调用摘要模型
        new_summary = await call_sync(
            model=SUMMARY_MODEL,
            messages=compress_messages,
            temperature=0.2,
        )

        # 第 3 层 – Memory：更新摘要并推进游标；消息列表保持不变
        conv.mid_term_summary = new_summary.strip()
        conv.mid_term_cursor = new_cursor

        # 第 7 层 – Persistence：写入检查点
        persistence.save(conv)

        # 第 8 层 – Verification：记录日志
        window_count = len(conv.messages) - new_cursor
        verification.log_compression(
            conv_id, len(to_summarise), window_count, len(conv.mid_term_summary)
        )
        return True


# 全局单例
harness = AgentHarness()
