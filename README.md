# ChatFlow — 本地 AI 对话系统

> 基于 **LangChain + LangGraph** 的本地全栈 AI 对话系统。
> 支持工具调用（Skills）、MCP 服务器接入、三级记忆体系（短期 + 摘要 + 向量 RAG）。

---

## 硬件参考

| 组件 | 规格 |
|---|---|
| CPU | AMD Ryzen 7 9800X3D 8核 4.70GHz |
| RAM | 64 GB DDR5 6000MT/s |
| GPU 显存 | 17 GB |

---

## 技术栈

| 层次 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + Element Plus |
| 后端框架 | Python 3.11 · FastAPI · Uvicorn |
| AI 编排 | LangGraph 0.3 · LangChain 0.3 |
| 本地 LLM | Ollama（OpenAI 兼容接口） |
| 向量数据库 | Qdrant（长期记忆，可禁用） |
| MCP 工具 | langchain-mcp-adapters |

---

## 模型配置

| 用途 | 模型 | 显存 |
|---|---|---|
| 对话主模型 | qwen3-coder:30b | ~17 GB |
| 摘要压缩模型 | qwen2.5-coder:14b | ~10 GB |
| 向量嵌入 | bge-m3 | ~0.5 GB |

> 三个模型按需加载，Ollama 空闲后自动卸载，不会同时占满显存。

---

## 整体架构

```
┌─────────────────────────────────┐
│       浏览器（Vue 3 前端）        │
│          localhost:5173          │
└──────────────┬──────────────────┘
               │ HTTP / SSE
               ▼
┌──────────────────────────────────────────────────────────┐
│              Python 后端（FastAPI :8000）                  │
│                                                          │
│  main.py                                                 │
│    └── graph/runner.py  ←  LangGraph Agent 图            │
│          │                                               │
│          ├── graph/nodes.py                              │
│          │     ├── retrieve_context  ← memory/ + rag/    │
│          │     ├── call_model        ← llm/ + tools/     │
│          │     ├── save_response     ← memory/store      │
│          │     └── compress_memory  ← memory/compressor  │
│          │                                               │
│          ├── memory/   对话存储 · 上下文组装 · 压缩        │
│          ├── rag/      Qdrant 检索 · 向量写入             │
│          ├── llm/      ChatOllama · OllamaEmbeddings     │
│          └── tools/    内置工具 · MCP 工具注册中心         │
└────────────────────────────────────────────────────────--┘
               │                    │
               ▼                    ▼
         Ollama :11434         Qdrant :6333
    qwen3-coder:30b            长期记忆向量库
    qwen2.5-coder:14b          （可禁用）
    bge-m3
```

---

## 项目结构

```
wehcat3/
├── README.md                       # 本文件
├── start.bat / stop.bat            # 一键启动/停止脚本
├── cloudflared.exe                 # Cloudflare Tunnel（公网穿透）
└── llm-chat/
    ├── backend/
    │   ├── main.py                 # FastAPI 入口 + lifespan 启动序列
    │   ├── config.py               # 所有配置（模型名/记忆参数/MCP 服务器）
    │   ├── models.py               # Pydantic 请求/响应模型
    │   ├── graph/                  # LangGraph Agent 图
    │   │   ├── state.py            #   GraphState TypedDict
    │   │   ├── nodes.py            #   4 个图节点
    │   │   ├── edges.py            #   条件边（工具 or 保存）
    │   │   ├── agent.py            #   build_graph() + 全局单例
    │   │   └── runner.py           #   astream_events → SSE 翻译器
    │   ├── memory/                 # 记忆管理
    │   │   ├── schema.py           #   Message / Conversation 数据结构
    │   │   ├── store.py            #   对话 CRUD + JSON 持久化
    │   │   ├── context_builder.py  #   组装发给 LLM 的消息列表
    │   │   └── compressor.py       #   滚动摘要压缩器
    │   ├── rag/                    # 长期记忆（Qdrant）
    │   │   ├── retriever.py        #   向量检索 + 忘记模式判断
    │   │   └── ingestor.py         #   压缩时批量写入向量对
    │   ├── llm/                    # LLM 工厂
    │   │   ├── chat.py             #   ChatOllama 缓存实例
    │   │   └── embeddings.py       #   OllamaEmbeddings + embed_text()
    │   ├── tools/                  # 工具系统（Skills）
    │   │   ├── __init__.py         #   注册中心：get_all_tools() / register_tool()
    │   │   ├── builtin/            #   内置工具
    │   │   │   ├── calculator.py   #     数学计算（安全 AST）
    │   │   │   ├── datetime_tool.py#     时区时间查询
    │   │   │   └── web_search.py   #     DuckDuckGo 搜索
    │   │   └── mcp/
    │   │       └── loader.py       #   MCP 服务器连接 + 工具加载
    │   ├── layers/
    │   │   └── extension.py        # CORS 配置
    │   └── conversations/          # 对话 JSON 存储（每个对话一个文件）
    └── frontend/                   # Vue 3 + Element Plus 前端
```

---

## 快速启动

### 第一步：下载模型

```bash
ollama pull qwen3-coder:30b      # 对话主模型
ollama pull qwen2.5-coder:14b    # 摘要压缩模型
ollama pull bge-m3               # 向量嵌入模型
```

### 第二步：启动 Qdrant（可选，长期记忆需要）

```bash
docker run -p 6333:6333 qdrant/qdrant

# 不想用 Qdrant？在 config.py 改一行：
# LONGTERM_MEMORY_ENABLED = False
```

### 第三步：安装后端依赖

```bash
cd llm-chat/backend
python -m venv venv
venv\Scripts\activate
pip install -e .
```

### 第四步：启动后端

```bash
python main.py   # 监听 :8000
```

### 第五步：启动前端

```bash
cd llm-chat/frontend
npm install
npm run dev   # 监听 :5173
```

**或者直接双击 `start.bat` 一键启动所有服务。**

---

## Agent 执行流程

```
用户发消息
    │
    ▼
① retrieve_context
    ├── 从 Qdrant 检索相关历史记忆（长期记忆）
    ├── 用余弦相似度判断话题是否切换（忘记模式）
    └── 组装消息列表：系统提示 + 摘要 + 长期记忆 + 近期对话
    │
    ▼
② call_model（ChatOllama + 工具绑定）
    ├── AI 决定：直接回复 → 跳到 ④
    └── AI 决定：调用工具 → 跳到 ③
    │
    ▼
③ tools（ToolNode 并发执行）
    ├── 执行工具（calculator / web_search / MCP 工具...）
    └── 把结果再喂给 AI → 回到 ②（可循环多次）
    │
    ▼
④ save_response
    └── 把 user + assistant 消息对写入 JSON 磁盘
    │
    ▼
⑤ compress_memory（异步，不影响流式输出）
    ├── 判断未摘要消息是否 ≥ 16 条
    ├── 是 → 批量写入 Qdrant + 调摘要模型生成滚动摘要
    └── 否 → 跳过
```

---

## 三级记忆系统

消息**永不删除**，压缩只推进游标：

```
第 1 级：短期记忆（滑动窗口）
  最近 10 轮对话原文，直接放入 LLM 上下文
                ↓（满 16 条未摘要消息时触发压缩）
第 2 级：中期记忆（滚动摘要）
  旧消息被摘要模型压缩成几百字，以 system 消息注入
                ↓（压缩时同步写入）
第 3 级：长期记忆（Qdrant 向量库）
  每对 Q&A 向量化存储，按语义相似度检索，跨会话有效
```

**发送给 LLM 的完整上下文结构：**

```
[1] system_prompt + 工具列表说明
[2] 中期摘要（有摘要时注入）
[3] 长期记忆（RAG 检索相关时注入）
[4] 最近 N 轮原文（滑动窗口）
[5] 本轮用户消息
```

**忘记模式（话题切换时自动瘦身）：**

```
RAG 命中？
  是 → 正常流程，注入全部记忆
  否 → 计算语义相似度
        相似 → 正常流程
        不相似 → 忘记模式：只发 [1] + 最近 2 轮，减少无关干扰
```

---

## 工具系统（Skills）

### 内置工具

| 工具 | 功能 |
|---|---|
| `calculator` | 数学计算，支持加减乘除、乘方、取模 |
| `get_current_datetime` | 查询任意时区的当前时间 |
| `web_search` | DuckDuckGo 搜索，无需 API Key |

### 添加新工具（2 步）

1. 新建 `tools/builtin/my_tool.py`，用 `@tool` 装饰器定义函数
2. 在 `tools/builtin/__init__.py` 的 `BUILTIN_TOOLS` 列表中追加

### 接入 MCP 服务器（零代码）

在 `config.py` 的 `MCP_SERVERS` 字典中添加服务器配置，重启即可：

```python
MCP_SERVERS = {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"],
        "transport": "stdio",
    },
}
```

---

## API 速查

```bash
# 查看可用模型
GET http://localhost:8000/api/models

# 查看可用工具
GET http://localhost:8000/api/tools

# 创建对话
POST http://localhost:8000/api/conversations
{"title": "测试", "system_prompt": ""}

# 流式聊天（SSE）
POST http://localhost:8000/api/chat
{"conversation_id": "xxxx", "message": "你好"}

# 查看记忆状态（调试）
GET http://localhost:8000/api/conversations/xxxx/memory

# 完整 API 文档
http://localhost:8000/docs
```

---

## 可调参数（config.py）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `CHAT_MODEL` | qwen3-coder:30b | 对话主模型 |
| `SUMMARY_MODEL` | qwen2.5-coder:14b | 摘要压缩模型 |
| `EMBEDDING_MODEL` | bge-m3 | 向量嵌入模型 |
| `SHORT_TERM_MAX_TURNS` | 10 | 滑动窗口保留轮数 |
| `COMPRESS_TRIGGER` | 8 | 触发压缩的轮数阈值（× 2 = 16 条消息） |
| `LONGTERM_MEMORY_ENABLED` | True | False = 禁用 Qdrant，不影响短期/中期记忆 |
| `LONGTERM_SCORE_THRESHOLD` | 0.5 | RAG 最低相似度阈值 |
| `LONGTERM_TOP_K` | 3 | RAG 每次注入的历史条数 |
| `SUMMARY_RELEVANCE_THRESHOLD` | 0.4 | 话题相关性阈值（低于则触发忘记模式） |
| `MCP_SERVERS` | {} | MCP 服务器配置字典 |

---

## 常见问题

**Q: 不想部署 Qdrant 可以用吗？**
可以。`config.py` 设置 `LONGTERM_MEMORY_ENABLED = False`，短期记忆和摘要压缩正常工作，只是没有第三级长期记忆。

**Q: 对话历史存在哪？**
`llm-chat/backend/conversations/` 目录，每个对话一个 JSON 文件，可直接查看和备份。

**Q: 消息会被删除吗？**
不会。`conv.messages` 永不删除，压缩只推进游标，全量历史始终保留在磁盘。

**Q: AI 调用工具前端有反应吗？**
有，SSE 流中会发送 `tool_call` 和 `tool_result` 事件，前端可选择性展示。
