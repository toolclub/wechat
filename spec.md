# 本地大语言模型部署指南 v2

> **目标**：本地部署双模型架构（对话 + 摘要），Python 后端管理三层记忆，Vue 3 前端提供 ChatGPT 风格界面。预留 RAG 长期记忆 + Embedding 模型扩展位。

---

## 硬件概况

| 组件 | 规格 | 备注 |
|------|------|------|
| CPU | AMD Ryzen 7 9800X3D 8核 4.70GHz | 高性能 |
| RAM | 64 GB DDR5 6000MT/s | 充足 |
| GPU 显存 | 17 GB | 推测 RTX 4090D 或类似 |
| 存储 | 932 GB，已用 501 GB | 剩余约 430 GB |

---

## 模型规划

| 用途 | 模型 | 参数量 | 显存占用 | 说明 |
|------|------|--------|----------|------|
| **对话主模型** | qwen2.5:14b | 14B | ~10-12GB | 中文能力强，主力对话 |
| **摘要压缩模型** | qwen2.5:1.5b | 1.5B | ~1.5GB | 轻量快速，专做记忆压缩 |
| **Embedding 模型**（预留） | nomic-embed-text 或 bge-m3 | - | ~0.5-1GB | 后续 RAG 向量化用 |

> 三个模型同时加载约 12-15GB 显存，17GB 完全够用。

---

## 整体架构

```
┌───────────────────────────────────────────────────────────┐
│                  浏览器（Vue 3 前端）                       │
│                  localhost:5173                            │
│            ChatGPT 风格对话界面                             │
└───────────────┬───────────────────────────────────────────┘
                │ HTTP / SSE
                ▼
┌───────────────────────────────────────────────────────────┐
│               Python 后端（FastAPI）                       │
│               localhost:8000                               │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │ 短期记忆  │  │ 中期记忆  │  │ 长期记忆  │  │ 对话管理   │ │
│  │ 近N轮原文 │  │ 压缩摘要  │  │ (预留RAG) │  │ 会话CRUD  │ │
│  └──────────┘  └──────────┘  └──────────┘  └───────────┘ │
└──────┬────────────┬────────────────────┬─────────────────┘
       │            │                    │
       ▼            ▼                    ▼ (预留)
┌────────────┐ ┌──────────┐     ┌──────────────────┐
│  Ollama     │ │ Ollama    │     │  Ollama           │
│  qwen2.5   │ │ qwen2.5   │     │  nomic-embed-text │
│  :14b      │ │ :1.5b     │     │  (Embedding)      │
│  对话主模型 │ │ 摘要模型   │     │  (后续RAG用)      │
└────────────┘ └──────────┘     └──────────────────┘
                                        │ (预留)
                                        ▼
                                ┌──────────────────┐
                                │  ChromaDB / Milvus │
                                │  向量数据库(预留)   │
                                └──────────────────┘
```

---

## STEP 1：安装 Ollama

### 1.1 下载安装

访问 https://ollama.com/download ，下载 Windows 版本安装包，双击安装。

安装完成后打开 PowerShell 验证：

```bash
ollama --version
```

### 1.2 验证 GPU

```bash
ollama run qwen2.5:1.5b
```

随便问一句，如果响应很快说明 GPU 正常。输入 `/bye` 退出。

---

## STEP 2：下载模型

### 2.1 下载三个模型

```bash
# 对话主模型（14B，中文最佳）
ollama pull qwen2.5:14b

# 摘要压缩模型（1.5B，轻量快速）
ollama pull qwen2.5:1.5b

# Embedding 模型（预留，后续 RAG 用，现在先下好）
ollama pull nomic-embed-text
```

### 2.2 验证模型列表

```bash
ollama list
```

应看到三个模型都已下载。

### 2.3 快速测试对话模型

```bash
ollama run qwen2.5:14b
>>> 用中文介绍一下你自己
```

确认中文回复质量 OK，输入 `/bye` 退出。

### 2.4 如果想用 HuggingFace 上的特定 GGUF 模型

```bash
# 1. 安装 huggingface-cli
pip install huggingface-hub

# 2. 下载 GGUF 文件（以某个模型为例）
huggingface-cli download <作者>/<模型名> <文件名>.gguf --local-dir ./models

# 3. 创建 Modelfile
cat > Modelfile << 'EOF'
FROM ./models/<文件名>.gguf
PARAMETER temperature 0.7
PARAMETER num_ctx 4096
SYSTEM "你是一个有用的AI助手，请用中文回答问题。"
EOF

# 4. 导入 Ollama
ollama create my-custom-model -f Modelfile

# 5. 测试
ollama run my-custom-model
```

---

## STEP 3：搭建 Python 后端（FastAPI）

### 3.1 创建项目结构

```bash
mkdir llm-chat && cd llm-chat
mkdir -p backend/conversations frontend
cd backend
```

最终结构：

```
llm-chat/
├── backend/
│   ├── main.py              # FastAPI 主入口
│   ├── config.py            # 集中配置（模型名、参数等）
│   ├── memory_manager.py    # 记忆管理系统
│   ├── ollama_client.py     # Ollama API 客户端
│   ├── models.py            # Pydantic 数据模型
│   ├── requirements.txt
│   └── conversations/       # 对话持久化存储
└── frontend/                # Vue 3 前端（STEP 5）
```

### 3.2 创建虚拟环境并安装依赖

```bash
cd backend
python -m venv venv

# Windows 激活
venv\Scripts\activate

# 安装依赖
pip install fastapi uvicorn httpx pydantic
```

`requirements.txt`：

```
fastapi==0.115.*
uvicorn==0.34.*
httpx==0.28.*
pydantic==2.*
```

### 3.3 集中配置 —— `config.py`

```python
"""
集中管理所有配置，方便后续调整。
"""

# ── Ollama 服务 ──
OLLAMA_BASE_URL = "http://localhost:11434"

# ── 模型配置 ──
CHAT_MODEL = "qwen2.5:14b"          # 对话主模型
SUMMARY_MODEL = "qwen2.5:1.5b"      # 摘要压缩模型
EMBEDDING_MODEL = "nomic-embed-text" # Embedding 模型（预留）

# ── 上下文窗口 ──
CHAT_NUM_CTX = 4096                  # 对话模型上下文大小
SUMMARY_NUM_CTX = 2048               # 摘要模型上下文大小

# ── 记忆参数 ──
SHORT_TERM_MAX_TURNS = 10            # 短期记忆保留的最大轮数
COMPRESS_TRIGGER = 8                 # 触发压缩的轮数阈值
MAX_SUMMARY_LENGTH = 500             # 摘要最大字数

# ── 服务端口 ──
BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000

# ── System Prompt ──
DEFAULT_SYSTEM_PROMPT = "你是一个有用的AI助手，请用中文回答用户的问题。回答要准确、清晰、有条理。"

SUMMARY_SYSTEM_PROMPT = (
    "你是一个专业的摘要助手。你的任务是把对话历史压缩成简洁的摘要。"
    "要求：保留关键信息、用户偏好、重要结论和待办事项。用中文输出。"
    "不要遗漏任何重要的事实或数字。"
)
```

### 3.4 Ollama 客户端 —— `ollama_client.py`

```python
import httpx
import json
from typing import AsyncGenerator
from config import OLLAMA_BASE_URL, CHAT_NUM_CTX, SUMMARY_NUM_CTX


async def chat_stream(
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    num_ctx: int = CHAT_NUM_CTX,
) -> AsyncGenerator[str, None]:
    """
    流式调用 Ollama /api/chat，用于对话主模型。
    逐 chunk 返回生成的文本。
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream(
            "POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload,
        ) as response:
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if "message" in data and "content" in data["message"]:
                    yield data["message"]["content"]
                if data.get("done", False):
                    break


async def chat_sync(
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    num_ctx: int = SUMMARY_NUM_CTX,
) -> str:
    """
    非流式调用，用于摘要压缩模型等内部任务。
    直接返回完整文本。
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat", json=payload,
        )
        data = resp.json()
        return data["message"]["content"]


async def get_embedding(text: str, model: str) -> list[float]:
    """
    获取文本的 Embedding 向量（预留，后续 RAG 用）。
    调用 Ollama /api/embeddings 接口。
    """
    payload = {
        "model": model,
        "prompt": text,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/embeddings", json=payload,
        )
        data = resp.json()
        return data.get("embedding", [])


async def list_models() -> list[str]:
    """获取 Ollama 中已下载的模型列表。"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
```

### 3.5 记忆管理 —— `memory_manager.py`

```python
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
```

### 3.6 数据模型 —— `models.py`

```python
from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    model: Optional[str] = None       # 不传则用默认对话模型
    temperature: float = 0.7


class CreateConversationRequest(BaseModel):
    title: Optional[str] = "新对话"
    system_prompt: Optional[str] = ""


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = None
    system_prompt: Optional[str] = None
```

### 3.7 主服务 —— `main.py`

```python
import uuid
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from models import ChatRequest, CreateConversationRequest, UpdateConversationRequest
from memory_manager import memory
from ollama_client import chat_stream, list_models
from config import CHAT_MODEL, BACKEND_HOST, BACKEND_PORT

app = FastAPI(title="本地LLM对话服务")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 模型 ──

@app.get("/api/models")
async def get_models():
    models = await list_models()
    return {"models": models}


# ── 对话管理 ──

@app.get("/api/conversations")
async def get_conversations():
    return {"conversations": memory.list_conversations()}


@app.post("/api/conversations")
async def create_conversation(req: CreateConversationRequest):
    conv_id = str(uuid.uuid4())[:8]
    conv = memory.create_conversation(
        conv_id=conv_id,
        title=req.title or "新对话",
        system_prompt=req.system_prompt or "",
    )
    return {"id": conv.id, "title": conv.title}


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = memory.get_conversation(conv_id)
    if not conv:
        return {"error": "对话不存在"}
    return {
        "id": conv.id,
        "title": conv.title,
        "system_prompt": conv.system_prompt,
        "messages": [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in conv.short_term
        ],
        "mid_term_summary": conv.mid_term_summary,
    }


@app.patch("/api/conversations/{conv_id}")
async def update_conversation(conv_id: str, req: UpdateConversationRequest):
    conv = memory.get_conversation(conv_id)
    if not conv:
        return {"error": "对话不存在"}
    if req.title is not None:
        conv.title = req.title
    if req.system_prompt is not None:
        conv.system_prompt = req.system_prompt
    memory._save(conv)
    return {"ok": True}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    memory.delete_conversation(conv_id)
    return {"ok": True}


# ── 聊天（流式 SSE） ──

@app.post("/api/chat")
async def chat(req: ChatRequest):
    conv = memory.get_conversation(req.conversation_id)
    if not conv:
        conv = memory.create_conversation(req.conversation_id)

    # 记录用户消息
    memory.add_message(req.conversation_id, "user", req.message)

    # 构建 messages
    messages = memory.build_messages(conv)

    # 用对话主模型流式生成
    model = req.model or CHAT_MODEL

    async def generate():
        full_response = ""
        async for chunk in chat_stream(
            model=model,
            messages=messages,
            temperature=req.temperature,
        ):
            full_response += chunk
            yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

        # 记录 AI 回复
        memory.add_message(req.conversation_id, "assistant", full_response)

        # 尝试压缩（使用摘要小模型，不影响对话模型）
        compressed = await memory.maybe_compress(req.conversation_id)

        yield f"data: {json.dumps({'done': True, 'compressed': compressed})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 记忆调试 ──

@app.get("/api/conversations/{conv_id}/memory")
async def get_memory_debug(conv_id: str):
    conv = memory.get_conversation(conv_id)
    if not conv:
        return {"error": "对话不存在"}
    return {
        "short_term_count": len(conv.short_term),
        "mid_term_summary": conv.mid_term_summary or "(空)",
        "build_messages_preview": [
            {"role": m["role"], "content": m["content"][:80] + "..." if len(m["content"]) > 80 else m["content"]}
            for m in memory.build_messages(conv)
        ],
    }


# ── 预留：Embedding 测试接口 ──

@app.post("/api/embedding")
async def test_embedding(text: str = "测试文本"):
    from ollama_client import get_embedding
    from config import EMBEDDING_MODEL
    vec = await get_embedding(text, EMBEDDING_MODEL)
    return {
        "model": EMBEDDING_MODEL,
        "text": text,
        "dimensions": len(vec),
        "vector_preview": vec[:5],  # 只返回前5维预览
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
```

### 3.8 启动后端

```bash
cd backend
python main.py
```

访问 http://localhost:8000/docs 查看 API 文档。

---

## STEP 4：测试后端 API

```bash
# 查看模型
curl http://localhost:8000/api/models

# 创建对话
curl -X POST http://localhost:8000/api/conversations \
  -H "Content-Type: application/json" \
  -d "{\"title\": \"测试\"}"
# → 返回 {"id": "xxxx", "title": "测试"}

# 发消息（把 xxxx 替换为实际 id）
curl -N http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"conversation_id\": \"xxxx\", \"message\": \"你好\"}"

# 查看记忆状态
curl http://localhost:8000/api/conversations/xxxx/memory

# 测试 Embedding（预留）
curl -X POST "http://localhost:8000/api/embedding?text=你好世界"
```

---

## STEP 5：搭建前端（Vue 3 + Vite）

### 5.1 创建项目

```bash
cd llm-chat/frontend
npm create vite@latest . -- --template vue-ts
npm install
```

### 5.2 项目结构

```
frontend/src/
├── App.vue              # 根组件
├── main.ts              # 入口
├── style.css            # 全局样式
├── api/
│   └── index.ts         # API 请求封装
├── components/
│   ├── Sidebar.vue      # 侧边栏（对话列表 + 新建 + 模型选择）
│   ├── ChatView.vue     # 聊天主视图
│   ├── MessageItem.vue  # 单条消息组件
│   └── InputBox.vue     # 输入框组件
├── composables/
│   └── useChat.ts       # 核心聊天逻辑（组合式函数）
└── types/
    └── index.ts         # 类型定义
```

### 5.3 类型定义 —— `src/types/index.ts`

```typescript
export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp?: number
}

export interface ConversationInfo {
  id: string
  title: string
  updated_at: number
}

export interface ConversationDetail {
  id: string
  title: string
  system_prompt: string
  messages: Message[]
  mid_term_summary: string
}
```

### 5.4 API 封装 —— `src/api/index.ts`

```typescript
const API_BASE = 'http://localhost:8000'

export async function fetchModels(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/api/models`)
  const data = await res.json()
  return data.models || []
}

export async function fetchConversations() {
  const res = await fetch(`${API_BASE}/api/conversations`)
  const data = await res.json()
  return data.conversations || []
}

export async function createConversation(title: string = '新对话') {
  const res = await fetch(`${API_BASE}/api/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  return res.json()
}

export async function fetchConversation(id: string) {
  const res = await fetch(`${API_BASE}/api/conversations/${id}`)
  return res.json()
}

export async function deleteConversation(id: string) {
  await fetch(`${API_BASE}/api/conversations/${id}`, { method: 'DELETE' })
}

export async function sendMessage(
  conversationId: string,
  message: string,
  model: string,
  onChunk: (text: string) => void,
  onDone: () => void,
) {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      model,
    }),
  })

  const reader = res.body?.getReader()
  const decoder = new TextDecoder()

  if (!reader) return

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const text = decoder.decode(value)
    for (const line of text.split('\n')) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6))
        if (data.content) onChunk(data.content)
        if (data.done) onDone()
      } catch {}
    }
  }
}
```

### 5.5 组合式函数 —— `src/composables/useChat.ts`

```typescript
import { ref } from 'vue'
import type { Message, ConversationInfo } from '../types'
import * as api from '../api'

export function useChat() {
  const conversations = ref<ConversationInfo[]>([])
  const currentConvId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const loading = ref(false)
  const models = ref<string[]>([])
  const selectedModel = ref('qwen2.5:14b')

  async function loadModels() {
    models.value = await api.fetchModels()
    if (models.value.length && !models.value.includes(selectedModel.value)) {
      selectedModel.value = models.value[0]
    }
  }

  async function loadConversations() {
    conversations.value = await api.fetchConversations()
  }

  async function selectConversation(id: string) {
    currentConvId.value = id
    const data = await api.fetchConversation(id)
    messages.value = (data.messages || []).map((m: any) => ({
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
    }))
  }

  async function newConversation() {
    const data = await api.createConversation()
    currentConvId.value = data.id
    messages.value = []
    await loadConversations()
  }

  async function removeConversation(id: string) {
    await api.deleteConversation(id)
    if (currentConvId.value === id) {
      currentConvId.value = null
      messages.value = []
    }
    await loadConversations()
  }

  async function send(text: string) {
    if (!text.trim() || loading.value) return

    // 如果没有当前对话，先创建
    if (!currentConvId.value) {
      const data = await api.createConversation(text.slice(0, 30))
      currentConvId.value = data.id
    }

    // 添加用户消息
    messages.value.push({ role: 'user', content: text })

    // 添加空的 assistant 消息（流式填充）
    messages.value.push({ role: 'assistant', content: '' })
    const assistantIdx = messages.value.length - 1

    loading.value = true

    try {
      await api.sendMessage(
        currentConvId.value!,
        text,
        selectedModel.value,
        (chunk) => {
          messages.value[assistantIdx].content += chunk
        },
        () => {
          loading.value = false
          loadConversations()
        },
      )
    } catch (err) {
      messages.value[assistantIdx].content = '⚠️ 请求失败，请检查后端和 Ollama 是否正常运行。'
      loading.value = false
    }
  }

  return {
    conversations, currentConvId, messages, loading,
    models, selectedModel,
    loadModels, loadConversations, selectConversation,
    newConversation, removeConversation, send,
  }
}
```

### 5.6 侧边栏 —— `src/components/Sidebar.vue`

```vue
<script setup lang="ts">
import type { ConversationInfo } from '../types'

defineProps<{
  conversations: ConversationInfo[]
  currentConvId: string | null
  models: string[]
  selectedModel: string
}>()

const emit = defineEmits<{
  newChat: []
  select: [id: string]
  delete: [id: string]
  'update:selectedModel': [model: string]
}>()
</script>

<template>
  <div class="sidebar">
    <button class="new-chat-btn" @click="emit('newChat')">
      + 新对话
    </button>

    <div class="conv-list">
      <div
        v-for="conv in conversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: conv.id === currentConvId }"
        @click="emit('select', conv.id)"
      >
        <span class="conv-title">{{ conv.title }}</span>
        <button
          class="delete-btn"
          @click.stop="emit('delete', conv.id)"
        >
          ×
        </button>
      </div>
    </div>

    <div class="model-select">
      <label>对话模型</label>
      <select
        :value="selectedModel"
        @change="emit('update:selectedModel', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 260px;
  background: #16213e;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #2a2a4a;
  flex-shrink: 0;
}

.new-chat-btn {
  margin: 12px;
  padding: 10px;
  background: #0f3460;
  color: #e0e0e0;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}
.new-chat-btn:hover { background: #1a4a8a; }

.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}
.conv-item:hover { background: #1a3a5c; }
.conv-item.active { background: #0f3460; }

.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: #ccc;
}

.delete-btn {
  background: none;
  border: none;
  color: #888;
  cursor: pointer;
  font-size: 18px;
  opacity: 0;
  transition: opacity 0.2s;
}
.conv-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover { color: #e74c3c; }

.model-select {
  padding: 12px;
  border-top: 1px solid #2a2a4a;
}
.model-select label {
  font-size: 12px;
  color: #666;
  display: block;
  margin-bottom: 4px;
}
.model-select select {
  width: 100%;
  padding: 6px 8px;
  background: #0f3460;
  color: #e0e0e0;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  font-size: 12px;
}
</style>
```

### 5.7 消息组件 —— `src/components/MessageItem.vue`

```vue
<script setup lang="ts">
import type { Message } from '../types'

defineProps<{ message: Message }>()
</script>

<template>
  <div class="message" :class="message.role">
    <div class="avatar">{{ message.role === 'user' ? '👤' : '🤖' }}</div>
    <div class="content">
      <pre>{{ message.content }}</pre>
    </div>
  </div>
</template>

<style scoped>
.message {
  display: flex;
  gap: 12px;
  padding: 16px 24px;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}
.message.assistant {
  background: rgba(15, 52, 96, 0.3);
}
.avatar {
  font-size: 20px;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.content {
  flex: 1;
  line-height: 1.7;
}
.content pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  font-family: inherit;
  font-size: 14px;
  color: #e0e0e0;
  margin: 0;
}
</style>
```

### 5.8 输入框 —— `src/components/InputBox.vue`

```vue
<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ loading: boolean }>()
const emit = defineEmits<{ send: [text: string] }>()

const input = ref('')

function handleSend() {
  if (!input.value.trim() || props.loading) return
  emit('send', input.value)
  input.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="input-area">
    <textarea
      v-model="input"
      @keydown="handleKeydown"
      placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
      :disabled="loading"
      rows="3"
    />
    <button @click="handleSend" :disabled="loading || !input.trim()">
      {{ loading ? '生成中...' : '发送' }}
    </button>
  </div>
</template>

<style scoped>
.input-area {
  display: flex;
  gap: 8px;
  padding: 16px 24px;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}
textarea {
  flex: 1;
  padding: 12px 16px;
  background: #16213e;
  color: #e0e0e0;
  border: 1px solid #2a2a4a;
  border-radius: 12px;
  resize: none;
  font-size: 14px;
  font-family: inherit;
  line-height: 1.5;
  outline: none;
}
textarea:focus { border-color: #0f3460; }
button {
  padding: 12px 24px;
  background: #0f3460;
  color: #e0e0e0;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-size: 14px;
  align-self: flex-end;
}
button:hover:not(:disabled) { background: #1a4a8a; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
```

### 5.9 聊天视图 —— `src/components/ChatView.vue`

```vue
<script setup lang="ts">
import { nextTick, watch, ref } from 'vue'
import type { Message } from '../types'
import MessageItem from './MessageItem.vue'
import InputBox from './InputBox.vue'

const props = defineProps<{
  messages: Message[]
  loading: boolean
}>()

const emit = defineEmits<{ send: [text: string] }>()

const messagesContainer = ref<HTMLDivElement>()

// 自动滚动到底部
watch(
  () => props.messages.length > 0 ? props.messages[props.messages.length - 1].content : '',
  async () => {
    await nextTick()
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  },
)
</script>

<template>
  <div class="chat-view">
    <div class="messages" ref="messagesContainer">
      <div v-if="messages.length === 0" class="empty-state">
        <h2>本地 LLM 对话</h2>
        <p>选择左侧对话或开始新对话</p>
      </div>
      <MessageItem
        v-for="(msg, i) in messages"
        :key="i"
        :message="msg"
      />
    </div>
    <InputBox :loading="loading" @send="emit('send', $event)" />
  </div>
</template>

<style scoped>
.chat-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px 0;
}
.empty-state {
  text-align: center;
  padding-top: 200px;
  color: #555;
}
.empty-state h2 {
  font-size: 24px;
  margin-bottom: 8px;
  color: #777;
}
.empty-state p { color: #555; }
</style>
```

### 5.10 根组件 —— `src/App.vue`

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useChat } from './composables/useChat'
import Sidebar from './components/Sidebar.vue'
import ChatView from './components/ChatView.vue'

const chat = useChat()

onMounted(() => {
  chat.loadModels()
  chat.loadConversations()
})
</script>

<template>
  <div class="app">
    <Sidebar
      :conversations="chat.conversations.value"
      :currentConvId="chat.currentConvId.value"
      :models="chat.models.value"
      :selectedModel="chat.selectedModel.value"
      @new-chat="chat.newConversation()"
      @select="chat.selectConversation($event)"
      @delete="chat.removeConversation($event)"
      @update:selectedModel="chat.selectedModel.value = $event"
    />
    <ChatView
      :messages="chat.messages.value"
      :loading="chat.loading.value"
      @send="chat.send($event)"
    />
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #1a1a2e;
  color: #e0e0e0;
}
.app {
  display: flex;
  height: 100vh;
}
</style>
```

### 5.11 启动前端

```bash
cd llm-chat/frontend
npm run dev
```

浏览器打开 http://localhost:5173 即可使用。

---

## STEP 6：启动顺序

每次使用时（需要三个独立终端窗口）：

```bash
# 终端 1 — 确认 Ollama 正常运行（Windows 安装后一般自动后台运行）
ollama list

# 终端 2 — 启动后端
cd D:\代码\wechat\llm-chat\backend
venv\Scripts\activate
python main.py                 # 监听 :8000（仅本机，不对外暴露）

# 终端 3 — 启动前端（需管理员权限，因为占用 80 端口）
cd D:\代码\wechat\llm-chat\frontend
npm run dev                    # 监听 :80，对局域网所有人开放
```

前端访问地址：
- 本机：http://localhost
- 局域网：http://192.168.x.x（查询方式：`ipconfig` 找 IPv4 地址）

> 前端通过 Vite 代理将 `/api` 请求转发到本机 `:8000`，后端无需对外暴露。

---

## STEP 7：公网暴露（Cloudflare Tunnel）

不需要公网 IP，使用 Cloudflare Tunnel 一条命令穿透：

### 7.1 下载工具（已下载，位于项目根目录）

```
D:\代码\wechat\cloudflared.exe
```

### 7.2 启动隧道

确保前端（:80）和后端（:8000）都已运行，然后：

```bash
D:\代码\wechat\cloudflared.exe tunnel --url http://localhost:80
```

输出中会出现公网地址，例如：

```
https://fruits-typing-performs-developing.trycloudflare.com
```

将此链接发给任何人即可访问，无需在同一局域网。

### 7.3 注意事项

| 项目 | 说明 |
|------|------|
| 地址有效期 | 临时地址，每次重启 cloudflared 会变 |
| 无需账号 | 匿名隧道，开箱即用 |
| 端口 | 只穿透 :80，后端 :8000 不暴露到公网 |
| 流量路径 | 外部用户 → Cloudflare → :80 前端 → Vite代理 → :8000 后端 |

---

## 记忆系统工作流程

```
第 1-7 轮对话：
  短期记忆: [user1, ai1, user2, ai2, ..., user7, ai7]   ← 14条消息，全部原文
  中期摘要: (空)
  发送给 qwen2.5:14b: [system] + [14条原文]

第 8 轮对话触发压缩：
  → 把前8条(user1~ai4) 发给 qwen2.5:1.5b 生成摘要
  短期记忆: [user5, ai5, ..., user8, ai8]               ← 只保留最近的
  中期摘要: "用户讨论了...偏好...结论是..."
  发送给 qwen2.5:14b: [system] + [摘要] + [最近8条原文]

后续继续积累，再次触发时：
  → qwen2.5:1.5b 把旧摘要+新溢出对话 合并成新摘要
  → 滚动窗口持续运行
```

---

## 可调参数速查

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `CHAT_MODEL` | config.py | qwen2.5:14b | 对话主模型 |
| `SUMMARY_MODEL` | config.py | qwen2.5:1.5b | 摘要压缩模型 |
| `EMBEDDING_MODEL` | config.py | nomic-embed-text | Embedding 模型（预留） |
| `CHAT_NUM_CTX` | config.py | 4096 | 对话模型上下文窗口 |
| `SHORT_TERM_MAX_TURNS` | config.py | 10 | 短期记忆最大轮数 |
| `COMPRESS_TRIGGER` | config.py | 8 | 触发压缩的轮数阈值 |
| `MAX_SUMMARY_LENGTH` | config.py | 500 | 摘要最大字数 |

---

## 后续扩展：RAG 长期记忆（预留说明）

当前已预留好接口，后续添加 RAG 时大致步骤：

1. **安装向量数据库**：推荐 ChromaDB（轻量本地） 或 Milvus
2. **每轮对话结束后**：用 `nomic-embed-text` 对用户消息/AI回复做 Embedding，存入向量库
3. **每次发消息前**：用当前用户输入做 Embedding → 从向量库检索相关历史片段
4. **注入到 messages 中**：在 `build_messages()` 的 RAG 预留位置，把检索结果作为 system 消息注入
5. **config.py 中已预留** `EMBEDDING_MODEL` 配置
6. **ollama_client.py 中已预留** `get_embedding()` 函数
7. **memory_manager.py 中已预留** RAG 相关注释代码块

最终三层记忆完整形态：

```
发送给模型的 messages:
  [1] system_prompt                          ← 人设
  [2] 中期摘要（qwen2.5:1.5b 生成）          ← 最近几十轮的压缩
  [3] RAG 检索结果（nomic-embed-text 检索）   ← 历史所有对话中的相关片段
  [4] 短期对话原文（最近 N 轮）               ← 完整上下文
```

---

## 常见问题

**Q: 两个模型会不会同时占显存导致 OOM？**
不会。Ollama 默认只在请求时加载模型到显存，空闲一段时间后自动卸载。摘要模型只在压缩时短暂运行。如果确实同时加载，14B(~12GB) + 1.5B(~1.5GB) ≈ 13.5GB，17GB 显存够用。

**Q: 摘要模型用 1.5B 会不会太小？**
对于摘要压缩任务足够了，因为输入是结构化的对话文本，不需要创造性。如果效果不满意，可以换成 `qwen2.5:7b`。

**Q: 为什么不直接用对话大模型做摘要？**
可以但没必要。用小模型做摘要速度更快、显存占用更小，大模型专注对话质量更高。

**Q: Embedding 模型现在需要下载吗？**
建议现在就 `ollama pull nomic-embed-text` 下好，不到 300MB，不占显存（只在调用时加载）。后续接 RAG 可以直接用。
