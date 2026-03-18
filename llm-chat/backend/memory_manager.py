import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from ollama_client import chat_sync
from config import (
    SHORT_TERM_MAX_TURNS, COMPRESS_TRIGGER, SUMMARY_MODEL,
    MAX_SUMMARY_LENGTH, SUMMARY_SYSTEM_PROMPT, SUMMARY_NUM_CTX,
)

CONVERSATIONS_DIR = "./conversations"
os.makedirs(CONVERSATIONS_DIR, exist_ok=True)


@dataclass
class Message:
    role: str           # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Conversation:
    id: str
    title: str = "新对话"
    system_prompt: str = ""
    short_term: list[Message] = field(default_factory=list)
    mid_term_summary: str = ""
    # ── 预留：长期记忆 RAG 相关字段 ──
    # long_term_collection: str = ""   # 向量数据库 collection 名
    # rag_enabled: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class MemoryManager:
    """
    三层记忆管理器（当前实现短期+中期，长期预留）

    短期记忆：最近 N 轮完整对话原文
    中期记忆：较早对话的压缩摘要（由摘要小模型生成）
    长期记忆：（预留）RAG 向量检索

    发给对话模型的 messages 结构：
      [system_prompt]
      [中期摘要 - 如有]
      [RAG 检索结果 - 预留]
      [短期对话原文]
    """

    def __init__(self):
        self.conversations: dict[str, Conversation] = {}
        self._load_all()

    # ── 持久化 ──

    def _conv_path(self, conv_id: str) -> str:
        return os.path.join(CONVERSATIONS_DIR, f"{conv_id}.json")

    def _save(self, conv: Conversation):
        conv.updated_at = time.time()
        data = {
            "id": conv.id,
            "title": conv.title,
            "system_prompt": conv.system_prompt,
            "short_term": [asdict(m) for m in conv.short_term],
            "mid_term_summary": conv.mid_term_summary,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
        }
        with open(self._conv_path(conv.id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_all(self):
        for fname in os.listdir(CONVERSATIONS_DIR):
            if not fname.endswith(".json"):
                continue
            filepath = os.path.join(CONVERSATIONS_DIR, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            conv = Conversation(
                id=data["id"],
                title=data.get("title", "新对话"),
                system_prompt=data.get("system_prompt", ""),
                short_term=[Message(**m) for m in data.get("short_term", [])],
                mid_term_summary=data.get("mid_term_summary", ""),
                created_at=data.get("created_at", 0),
                updated_at=data.get("updated_at", 0),
            )
            self.conversations[conv.id] = conv

    # ── 对话 CRUD ──

    def create_conversation(
        self, conv_id: str, title: str = "新对话", system_prompt: str = ""
    ) -> Conversation:
        from config import DEFAULT_SYSTEM_PROMPT
        conv = Conversation(
            id=conv_id,
            title=title,
            system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        )
        self.conversations[conv_id] = conv
        self._save(conv)
        return conv

    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        return self.conversations.get(conv_id)

    def list_conversations(self) -> list[dict]:
        return sorted(
            [
                {"id": c.id, "title": c.title, "updated_at": c.updated_at}
                for c in self.conversations.values()
            ],
            key=lambda x: x["updated_at"],
            reverse=True,
        )

    def delete_conversation(self, conv_id: str):
        if conv_id in self.conversations:
            del self.conversations[conv_id]
            path = self._conv_path(conv_id)
            if os.path.exists(path):
                os.remove(path)

    # ── 构建发给模型的 messages ──

    def build_messages(self, conv: Conversation) -> list[dict]:
        messages = []

        # 1. System prompt
        messages.append({"role": "system", "content": conv.system_prompt})

        # 2. 中期摘要
        if conv.mid_term_summary:
            messages.append({
                "role": "system",
                "content": (
                    "【对话背景摘要】以下是之前对话的压缩摘要，请结合这些背景来回答：\n"
                    f"{conv.mid_term_summary}"
                ),
            })

        # 3. 预留：RAG 检索结果注入位置
        # if conv.rag_enabled:
        #     relevant_docs = await rag_search(user_query, conv.long_term_collection)
        #     messages.append({
        #         "role": "system",
        #         "content": f"【相关知识】\n{relevant_docs}"
        #     })

        # 4. 短期记忆
        recent = conv.short_term[-(SHORT_TERM_MAX_TURNS * 2):]
        for msg in recent:
            messages.append({"role": msg.role, "content": msg.content})

        return messages

    # ── 添加消息 ──

    def add_message(self, conv_id: str, role: str, content: str):
        conv = self.conversations.get(conv_id)
        if not conv:
            return
        conv.short_term.append(Message(role=role, content=content))

        # 第一条用户消息自动生成标题
        if conv.title == "新对话" and role == "user":
            conv.title = content[:30] + ("..." if len(content) > 30 else "")

        self._save(conv)

    # ── 中期记忆压缩 ──

    async def maybe_compress(self, conv_id: str) -> bool:
        """
        检查并执行记忆压缩。
        返回是否执行了压缩。

        使用摘要小模型（qwen2.5:1.5b）而不是对话大模型，
        节省显存且速度更快。
        """
        conv = self.conversations.get(conv_id)
        if not conv:
            return False

        total_messages = len(conv.short_term)
        if total_messages < COMPRESS_TRIGGER * 2:
            return False

        # 分割：保留最近一半，压缩前面的
        keep_count = (SHORT_TERM_MAX_TURNS // 2) * 2
        to_compress = conv.short_term[:-keep_count]
        to_keep = conv.short_term[-keep_count:]

        # 构建待压缩文本
        history_text = "\n".join(
            f"{'用户' if m.role == 'user' else 'AI'}: {m.content}"
            for m in to_compress
        )

        compress_prompt = [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"请将以下对话历史压缩成摘要。\n\n"
                    f"已有的历史摘要：\n{conv.mid_term_summary or '（无）'}\n\n"
                    f"新增对话：\n{history_text}\n\n"
                    f"请输出更新后的综合摘要（不超过{MAX_SUMMARY_LENGTH}字）："
                ),
            },
        ]

        # 用摘要小模型生成
        new_summary = await chat_sync(
            model=SUMMARY_MODEL,
            messages=compress_prompt,
            temperature=0.2,
            num_ctx=SUMMARY_NUM_CTX,
        )

        conv.mid_term_summary = new_summary.strip()
        conv.short_term = to_keep
        self._save(conv)

        print(f"[记忆压缩] 对话 {conv_id}")
        print(f"  压缩了 {len(to_compress)} 条消息")
        print(f"  保留了 {len(to_keep)} 条消息")
        print(f"  摘要长度: {len(conv.mid_term_summary)} 字")
        return True


# 全局单例
memory = MemoryManager()
