# 本地 LLM 对话服务

> **目标**：本地部署双模型架构（对话 + 摘要），Python 后端基于 9 层 Agent Harness 架构管理上下文与记忆，Vue 3 前端提供 ChatGPT 风格界面。预留 RAG 长期记忆 + Embedding 扩展位。

---

## 硬件概况

| 组件 | 规格 |
|------|------|
| CPU | AMD Ryzen 7 9800X3D 8核 4.70GHz |
| RAM | 64 GB DDR5 6000MT/s |
| GPU 显存 | 17 GB |
| 存储 | 932 GB |

---

## 模型规划

| 用途 | 模型 | 显存占用 | 说明 |
|------|------|----------|------|
| **对话主模型** | qwen2.5:14b | ~10-12 GB | 中文能力强，主力对话 |
| **摘要压缩模型** | qwen2.5:1.5b | ~1.5 GB | 轻量快速，专做记忆压缩 |
| **Embedding**（预留） | nomic-embed-text | ~0.5 GB | 后续 RAG 向量化用 |

> 三个模型同时加载约 12–15 GB，17 GB 显存够用。

---

## 9 层 Agent Harness 架构

基于对 6 篇权威博客和 3 个主流开源框架的分析，后端采用 9 层 Harness 模型：

```
Agent Harness/
├── 1. Prompt      ── system prompt · 摘要模板
├── 2. Capability  ── Ollama 模型列表 · Embedding
├── 3. Memory      ── 消息结构 · 会话数据结构 · RAG 预留
├── 4. Runtime     ── Agent Loop（流式 · 同步）
├── 5. State       ── StateManager（进程内工作记忆）
├── 6. Context     ── 消息组装 · 压缩触发 · 滑动窗口
├── 7. Persistence ── JSON Checkpoint（磁盘 · 跨进程恢复）
├── 8. Verification── 日志 · 可观测性
└── 9. Extension   ── CORS · 插件扩展点
```

### OS 类比（Phil Schmid）

| 操作系统概念 | 本项目对应 | 职责 |
|---|---|---|
| CPU | Model（qwen2.5:14b） | 原始推理能力 |
| RAM | Context Window | 有限的工作内存 |
| OS | Harness（harness.py） | 管理所有层的调度 |
| 系统调用 | Capability（Ollama API） | Agent 能做什么 |
| 进程调度 | Runtime（layers/runtime.py） | 执行 agent loop |
| Process State | State（layers/state.py） | 运行时内存状态 |
| Disk Storage | Persistence（layers/persistence.py） | 跨进程持久化 |
| App | FastAPI main.py | 用户定义的对话逻辑 |

### 关键概念区分：Memory vs State vs Persistence

| 概念 | 认知科学类比 | 实际含义 | 时态 | 本项目实现 |
|------|------------|----------|------|-----------|
| **Memory** | Episodic + Semantic | 记住什么（消息历史 + 摘要） | 会话/永久 | `layers/memory.py`：`Conversation.messages` + `mid_term_summary` |
| **State** | Working Memory | 正在做什么（进程内） | 运行时 | `layers/state.py`：`StateManager._store` |
| **Persistence** | — | 做到哪里（可恢复） | 跨进程 | `layers/persistence.py`：JSON Checkpoint |

```
Memory 层:      "记住什么"（知识 + 对话）
State 层:       "正在做什么"（内存中，进程重启即丢）
Persistence 层: "做到哪里"（磁盘，重启后恢复）
```

---

## 整体架构

```
┌─────────────────────────────────┐
│       浏览器（Vue 3 前端）        │
│       localhost:5173             │
└────────────┬────────────────────┘
             │ HTTP / SSE
             ▼
┌─────────────────────────────────────────────────────┐
│           Python 后端（FastAPI :8000）               │
│                                                     │
│  main.py                                            │
│    └── harness.py  ← 9 层统一门面                   │
│          ├── layers/prompt.py        Layer 1        │
│          ├── layers/capability.py    Layer 2        │
│          ├── layers/memory.py        Layer 3        │
│          ├── layers/runtime.py       Layer 4        │
│          ├── layers/state.py         Layer 5        │
│          ├── layers/context.py       Layer 6        │
│          ├── layers/persistence.py   Layer 7        │
│          ├── layers/verification.py  Layer 8        │
│          └── layers/extension.py     Layer 9        │
└────────┬──────────────┬───────────────┬────────────┘
         │              │               │
         ▼              ▼               ▼ (预留)
   qwen2.5:14b    qwen2.5:1.5b    nomic-embed-text
   对话主模型      摘要压缩模型      Embedding
         │              │               │
         └──────────────┴───────────────┘
                  Ollama :11434
                  (OpenAI 兼容 /v1)
```

---

## 项目结构

```
wehcat3/
├── README.md
├── start.bat / stop.bat          # 一键启动/停止脚本
├── cloudflared.exe               # Cloudflare Tunnel（公网穿透）
└── llm-chat/
    ├── backend/
    │   ├── harness.py            # 9 层统一门面（AgentHarness）
    │   ├── main.py               # FastAPI 入口
    │   ├── config.py             # 集中配置
    │   ├── ollama_client.py      # Ollama HTTP 客户端（流式 + 同步）
    │   ├── models.py             # Pydantic 请求/响应模型
    │   ├── layers/
    │   │   ├── prompt.py         # Layer 1：system prompt / 摘要模板
    │   │   ├── capability.py     # Layer 2：模型列表 / Embedding
    │   │   ├── memory.py         # Layer 3：Message · Conversation 数据结构
    │   │   ├── runtime.py        # Layer 4：Agent Loop（stream / sync）
    │   │   ├── state.py          # Layer 5：StateManager（进程内 dict）
    │   │   ├── context.py        # Layer 6：消息组装 · 压缩判断 · 滑动窗口
    │   │   ├── persistence.py    # Layer 7：JSON Checkpoint 读写
    │   │   ├── verification.py   # Layer 8：日志 / 可观测性
    │   │   └── extension.py      # Layer 9：CORS 等扩展点
    │   └── conversations/        # 对话 JSON 存储（不入库）
    └── frontend/                 # Vue 3 + Vite 前端
```

---

## 记忆系统工作流程

消息**永不删除**，压缩只推进 `mid_term_cursor`：

```
第 1–7 轮：
  messages: [u1, a1, u2, a2, ..., u7, a7]   cursor=0
  发给模型:  [system] + [最近 N 轮原文]

第 8 轮触发压缩（unsummarised >= COMPRESS_TRIGGER*2）：
  → messages[0:cursor_new] 发给 qwen2.5:1.5b 生成摘要
  → mid_term_summary 更新，cursor 前移
  messages: [u1..a8] 全部保留，cursor 前移
  发给模型:  [system] + [摘要] + [最近 N 轮滑动窗口]

后续滚动：
  摘要不断叠加旧内容，窗口始终保持最近 N 轮完整原文
```

**最终三层完整形态（RAG 接入后）：**

```
[1] system_prompt               ← Layer 1 Prompt
[2] 中期摘要（语义记忆）          ← Layer 3 Memory
[3] RAG 检索结果（预留）          ← Layer 3 Memory（long_term）
[4] 滑动窗口原文（情节记忆）       ← Layer 6 Context
```

---

## 快速启动

### 环境准备

```bash
# 1. 安装 Ollama（Windows）
# 访问 https://ollama.com/download 下载安装

# 2. 下载模型
ollama pull qwen2.5:14b
ollama pull qwen2.5:1.5b
ollama pull nomic-embed-text   # 预留，建议一并下载
```

### 启动后端

```bash
cd llm-chat/backend
python -m venv venv
venv\Scripts\activate
pip install fastapi uvicorn httpx pydantic openai

python main.py   # 监听 :8000
```

访问 http://localhost:8000/docs 查看 API 文档。

### 启动前端

```bash
cd llm-chat/frontend
npm install
npm run dev   # 监听 :5173
```

### 公网穿透（Cloudflare Tunnel）

```bash
# 前后端都启动后，一条命令穿透
cloudflared.exe tunnel --url http://localhost:5173
```

输出中会出现临时公网地址，发给任何人即可访问，无需公网 IP。

---

## API 速查

```bash
# 查看已下载模型
curl http://localhost:8000/api/models

# 创建对话
curl -X POST http://localhost:8000/api/conversations \
  -H "Content-Type: application/json" \
  -d "{\"title\": \"测试\"}"

# 发消息（SSE 流式）
curl -N http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"conversation_id\": \"xxxx\", \"message\": \"你好\"}"

# 查看记忆状态（调试）
curl http://localhost:8000/api/conversations/xxxx/memory
```

---

## 可调参数

| 参数 | 文件 | 默认值 | 说明 |
|------|------|--------|------|
| `CHAT_MODEL` | config.py | qwen2.5:14b | 对话主模型 |
| `SUMMARY_MODEL` | config.py | qwen2.5:1.5b | 摘要压缩模型 |
| `CHAT_NUM_CTX` | config.py | 4096 | 对话模型上下文窗口 |
| `SHORT_TERM_MAX_TURNS` | config.py | 10 | 滑动窗口保留轮数 |
| `COMPRESS_TRIGGER` | config.py | 8 | 触发压缩的未摘要轮数阈值 |
| `MAX_SUMMARY_LENGTH` | config.py | 500 | 摘要最大字数 |

---

## 后续扩展：RAG 长期记忆

预留位已就绪，接入步骤：

1. 安装向量数据库（推荐 ChromaDB 本地轻量）
2. 每轮对话后用 `nomic-embed-text` 对消息做 Embedding 并存入向量库
3. 每次发消息前检索相关历史片段
4. 在 `layers/context.py` 的 RAG 预留注释处注入检索结果
5. 取消 `layers/memory.py` 中 `long_term_collection` 字段的注释

---

## 常见问题

**Q: 两个模型同时占显存会 OOM 吗？**
不会。Ollama 在请求时加载、空闲后自动卸载。14B(~12GB) + 1.5B(~1.5GB) ≈ 13.5GB，17GB 够用。

**Q: 摘要模型 1.5B 会不会太弱？**
摘要任务是结构化压缩，不需要创造性，1.5B 完全胜任。效果不满意可换 `qwen2.5:7b`。

**Q: 消息历史会被删吗？**
不会。`conv.messages` 永不删除，压缩只推进 `mid_term_cursor`，全量历史始终保留在磁盘。

## 开发者说明
  ---
  整体调用链

  用户发消息 → main.py → harness.py（统一门面） → 各个 layers/ → ollama_client.py → Ollama

  ---
  ollama_client.py — 最底层，直接和 Ollama 说话

  这是唯一真正发 HTTP 请求的地方，其他所有层都不直接碰网络。

  有三个函数：
  - chat_stream() — 流式对话，用 SSE 一块一块返回文字（给用户看的那种打字效果）
  - chat_sync() — 同步调用，等模型跑完再返回完整结果（用于内部摘要任务）
  - get_embedding() — 获取向量（预留，RAG 用）

  值得注意：这里从旧版的 Ollama 私有 API (/api/chat) 改成了 OpenAI 兼容格式 (/v1/chat/completions)，所以理论上把 API_BASE_URL 换成任何 OpenAI 兼容服务（比如 vLLM、LM Studio、真正的 OpenAI）都能用。

  ---
  9 层详解

  Layer 1 — prompt.py：管"说什么"

  两个函数：

  ensure_system_prompt(raw)          # 用户没填 system prompt → 用默认的
  build_summary_messages(history, existing_summary)  # 拼摘要请求的消息列表

  所有 prompt 模板都集中在这里，改人设或摘要风格只改这一个文件。

  ---
  Layer 2 — capability.py：管"能做什么"

  目前只有两个能力：
  - list_models() — 问 Ollama 有哪些模型
  - get_embedding() — 获取向量

  这层是对 ollama_client 的薄包装，目的是语义隔离——"工具"和"底层 HTTP 客户端"是两回事。以后接 MCP、外部 API 也加在这里。

  ---
  Layer 3 — memory.py：数据结构定义

  两个 dataclass：

  Message:
      role: str        # "user" | "assistant" | "system"
      content: str
      timestamp: float

  Conversation:
      id, title, system_prompt
      messages: list[Message]    # 全量历史，永不删除
      mid_term_summary: str      # 语义记忆（摘要）
      mid_term_cursor: int       # 已摘要到哪条消息（索引）
      # long_term_collection     # 预留：RAG 集合名

  关键设计：messages 是追加写的，永远不删。mid_term_cursor 像一个指针，记录"哪些消息已经被压缩进摘要了"，但原消息还在。

  ---
  Layer 4 — runtime.py：执行引擎

  目前只有两个函数，非常薄：

  stream(model, messages, temperature)    # 流式 → yield 文字块
  call_sync(model, messages, temperature) # 同步 → 返回完整字符串

  这是 agent loop 的执行层。现在是单轮对话，以后如果要做多步 agent（工具调用循环、子代理）就在这里扩展。

  ---
  Layer 5 — state.py：进程内工作记忆

  StateManager 就是一个字典 { conv_id: Conversation }，装在内存里。

  state.get(conv_id)   # 取一个对话
  state.set(conv)      # 存一个对话
  state.remove(id)     # 删除
  state.all()          # 列出所有
  state.load_from(dict) # 启动时从磁盘批量恢复

  类比 OS 的 RAM——进程跑着就在，进程重启就没了。所以必须配合 Layer 7 Persistence 才能跨进程恢复。

  ---
  Layer 6 — context.py：决定"发什么给模型"

  这是整个记忆系统最核心的逻辑，三个函数：

  build_messages(conv) — 组装发给模型的消息列表，固定顺序：
  [system prompt]
  [中期摘要]         ← 如果有
  [RAG 检索结果]     ← 预留注释
  [最近 N 轮原文]    ← 滑动窗口 SHORT_TERM_MAX_TURNS*2 条消息

  should_compress(conv) — 判断是否要压缩：
  未摘要消息数 = len(messages) - mid_term_cursor
  return 未摘要消息数 >= COMPRESS_TRIGGER * 2   # 默认 8*2=16 条

  slice_for_compression(conv) — 决定压缩哪些：
  keep_count = (SHORT_TERM_MAX_TURNS // 2) * 2  # 保留最近一半
  new_cursor = len(messages) - keep_count        # cursor 前进到这里
  to_summarise = messages[old_cursor:new_cursor] # 这段发给摘要模型
  压缩后消息列表不变，只有 cursor 往前推。

  ---
  Layer 7 — persistence.py：磁盘 Checkpoint

  三个函数，负责把 Conversation 对象序列化成 JSON 存到 conversations/ 目录：

  save(conv)       # 写 JSON 文件（conversations/{id}.json）
  load_all()       # 启动时读所有 JSON，返回 dict
  delete(conv_id)  # 删文件

  有一个向后兼容处理：旧版本用的是 short_term 字段，新版本改成了 messages，load 时两个都能认。

  ---
  Layer 8 — verification.py：日志

  log_chat(conv_id, model)                           # 每次聊天记一条
  log_compression(conv_id, compressed, kept, len)   # 压缩时记一条
  log_error(msg, exc)                               # 报错时记

  用标准 logging 输出到控制台，格式是 时间 [级别] harness: 消息。

  ---
  Layer 9 — extension.py：CORS

  目前就一个函数：

  apply_cors(app, origins=["*"])

  在 main.py 最早被调用，让前端跨域请求不被浏览器拦截。这层的扩展位是以后加插件系统、多渠道接入（微信、Telegram）、API Gateway 之类的东西。

  ---
  harness.py — 把 9 层串起来的门面

  AgentHarness 是唯一被 main.py 用到的类，它自己不做任何计算，就负责把调用路由到正确的层：

  create_conversation()  → Layer 1（ensure prompt）+ Layer 5（set）+ Layer 7（save）
  add_message()          → Layer 3（append）+ Layer 7（save）
  build_messages()       → Layer 6（context assembly）
  chat_stream()          → Layer 8（log）+ Layer 4（runtime stream）
  maybe_compress()       → Layer 6（should? slice?）+ Layer 1（build prompt）
                          + Layer 4（call sync）+ Layer 3（update cursor）
                          + Layer 7（save）+ Layer 8（log）

  maybe_compress 是最复杂的一个方法，跨了 6 层，但每一步做什么都很清晰。

  ---
  main.py — 最外层，HTTP 接口

  就是 FastAPI 路由，非常薄。收到请求 → 调 harness → 返回结果。

  唯一有业务逻辑的是 /api/chat 的 generate() 生成器：
  1. 流式 yield 文字块给前端
  2. 全部生成完后记录 assistant 消息
  3. 异步触发一次 maybe_compress
  4. 发 {done: true} 结束流
