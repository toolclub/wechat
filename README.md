# ChatFlow — AI 智能对话平台

> 基于 LangChain + LangGraph 构建的新一代 AI 对话系统，支持多意图路由、自动任务规划、工具调用、多模态理解、三级记忆与语义缓存。

---

<!-- 演示视频 -->
<!-- 上传视频后取消下方注释，替换链接即可 -->
<!--
[![ChatFlow 演示](视频封面图URL)](视频链接URL)
-->

---

## 核心特性

### 智能路由与规划
- **四层意图路由**：自动识别 `chat` / `code` / `search` / `search_code`，为每类任务分配最优模型
- **自动任务拆解**：复杂请求自动生成 1-10 步执行计划，可视化展示实时进度
- **可编辑工作流**：前端直接插入、删除、修改执行步骤后重新运行
- **步骤反思机制**：每步完成后评估结果，决定 continue / done / retry

### 工具调用
- **内置工具**：Web 搜索（DuckDuckGo）、网页抓取、计算器、时间查询
- **MCP 协议扩展**：通过 `.env` 零代码接入任意 MCP 服务器（filesystem、github、fetch 等）
- **并发执行**：多工具调用并发处理，结果实时流式推送前端

### 多模态理解
- **图片输入**：支持粘贴 / 拖拽 / 上传，客户端自动压缩（1280px / 82% 质量）
- **视觉流式分析**：视觉模型逐 token 推送分析过程，显示在思考折叠块中
- **解耦设计**："分析归分析，推理归推理"——视觉模型只做描述，主模型负责推理

### 三级记忆体系
| 层级 | 机制 | 存储 |
|------|------|------|
| **短期** | 滑动窗口（最近 N 轮） | PostgreSQL |
| **中期** | 达到阈值自动语义压缩 | PostgreSQL |
| **长期** | 压缩时写入 Qdrant，每轮检索 Top-K | Qdrant 向量库 |

**选择性遗忘**：话题切换时自动检测相似度，无关历史不送入上下文，保持回答质量

### 语义缓存
- **秒级响应**：相似问题命中 Redis KNN 缓存，跳过全部 LLM 推理链路
- **四种隔离模式**：`user` / `prompt` / `global` / `conv`
- **TTL 策略**：`chat/code` 路由永不过期，`search` 类可配置过期时间

### 流式输出与实时反馈
- **Token 级别推流**：SSE 逐 token 渲染，thinking 推理块实时展示
- **事件分级**：内容 token、工具调用进度、搜索结果、计划状态、反思结论分别推送
- **心跳保活**：定时发送 ping，防止 nginx / 代理超时断流

### 澄清协议
- **自动触发**：意图多义、设计风格缺失（网页/UI 生成）、关键参数不明时弹出交互卡片
- **提前拦截**：规划节点前置检查，避免模型在信息不足时盲目执行
- **三种交互形式**：单选 / 多选 / 文本输入，答案自动拼回原始意图重新发起

---

## 技术栈

| 层次 | 技术 |
|------|------|
| **后端框架** | Python 3.11 · FastAPI · asyncio |
| **AI 编排** | LangChain · LangGraph（有向无环图） |
| **前端框架** | Vue 3 · TypeScript · Vite |
| **关系数据库** | PostgreSQL 16 |
| **向量数据库** | Qdrant |
| **缓存** | Redis Stack（RediSearch KNN） |
| **部署** | Docker Compose · Nginx |

---

## 支持的模型与接口

兼容任何 OpenAI 格式接口，可混合搭配：

| 提供商 | 典型模型 | 用途 |
|--------|---------|------|
| **Ollama（本地）** | qwen3、qwen2.5vl、bge-m3 | 全功能本地运行 |
| **OpenAI** | gpt-4o、text-embedding-3 | 高精度云端 |
| **智谱 GLM** | GLM-4、GLM-4.6V | 中文优化 + 视觉 |
| **MiniMax** | MiniMax-M2.7 | 长上下文 + 多模态 |
| **其他** | 任意 OpenAI 兼容接口 | 自由配置 |

---

## 快速开始

### Docker Compose 部署（推荐）

```bash
git clone https://github.com/your-org/ChatFlow.git
cd ChatFlow/llm-chat

# 复制配置并填写 API Key 和模型名称
cp .env.example .env

# 一键启动（backend · frontend · postgres · qdrant · redis）
docker compose up -d

# 查看日志
docker compose logs -f backend
```

浏览器访问 **http://localhost**

```bash
# 停止
docker compose down

# 代码更新后重新构建
docker compose up -d --build
```

### 本地开发启动

```bash
# 后端
cd llm-chat/backend
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .
python main.py

# 前端（新终端）
cd llm-chat/frontend
npm install && npm run dev
```

访问 **http://localhost:5173**，后端 API 文档：**http://localhost:8000/docs**

---

## 配置说明

```bash
cp .env.example .env
```

### LLM 接口

```env
LLM_BASE_URL=https://api.openai.com/v1   # LLM 服务地址（任意 OpenAI 兼容接口）
API_KEY=sk-...                            # API Key
CHAT_MODEL=gpt-4o                         # 对话模型
SUMMARY_MODEL=gpt-4o-mini                 # 摘要模型（速度优先）
EMBEDDING_MODEL=text-embedding-3-large    # Embedding 模型
EMBEDDING_BASE_URL=                       # Embedding 独立接口（留空复用 LLM_BASE_URL）

# 视觉模型（可选，留空则跳过图片分析）
VISION_MODEL=gpt-4o
VISION_BASE_URL=                          # 留空复用 LLM_BASE_URL
VISION_API_KEY=                           # 留空复用 API_KEY
```

### 路由与模型映射

```env
ROUTER_ENABLED=true
ROUTER_MODEL=gpt-4o-mini
SEARCH_MODEL=gpt-4o                       # 工具调用模型
ROUTE_MODEL_MAP={"chat":"gpt-4o","code":"gpt-4o","search":"gpt-4o","search_code":"gpt-4o"}
```

### 记忆参数

```env
SHORT_TERM_MAX_TURNS=10                   # 短期记忆窗口
COMPRESS_TRIGGER=8                        # 触发压缩的消息数
MAX_SUMMARY_LENGTH=500                    # 摘要最大长度
LONGTERM_MEMORY_ENABLED=true
QDRANT_URL=http://qdrant:6333
EMBEDDING_DIM=3072                        # 需与 Embedding 模型维度一致
LONGTERM_TOP_K=3
LONGTERM_SCORE_THRESHOLD=0.5
```

### 语义缓存

```env
SEMANTIC_CACHE_ENABLED=true
REDIS_URL=redis://redis:6379
SEMANTIC_CACHE_THRESHOLD=0.88             # 命中阈值（推荐 0.85~0.92）
SEMANTIC_CACHE_NAMESPACE_MODE=user        # user / prompt / global / conv
SEMANTIC_CACHE_SEARCH_TTL_HOURS=12        # search 类缓存过期时间
```

### 数据库

```env
DATABASE_URL=postgresql://user:pass@postgres:5432/chatflow
```

### MCP 工具扩展

```env
MCP_SERVERS={"filesystem":{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","./data"],"transport":"stdio"}}
```

完整配置见 [`.env.example`](llm-chat/.env.example)

---

## 项目结构

```
llm-chat/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 统一配置（pydantic-settings）
│   ├── graph/
│   │   ├── agent.py               # LangGraph 图构建与编译
│   │   ├── state.py               # GraphState 类型定义
│   │   ├── edges.py               # 条件路由逻辑
│   │   ├── nodes/                 # 执行节点
│   │   │   ├── vision_node.py     # 多模态图片理解
│   │   │   ├── route_node.py      # 意图路由决策
│   │   │   ├── planner_node.py    # 任务自动规划
│   │   │   ├── call_model_node.py # 主推理节点
│   │   │   ├── call_model_after_tool_node.py
│   │   │   ├── reflector_node.py  # 步骤评估反思
│   │   │   ├── save_response_node.py
│   │   │   └── ...
│   │   └── runner/                # SSE 流式执行引擎
│   │       ├── stream.py          # 主驱动（队列 + 心跳）
│   │       ├── dispatcher.py      # 事件分发（职责链）
│   │       └── handlers/          # 各类事件处理器
│   ├── llm/                       # LLM / Embedding 工厂
│   ├── memory/                    # 短期 + 中期记忆
│   ├── rag/                       # 长期记忆（Qdrant）
│   ├── cache/                     # 语义缓存（Redis）
│   ├── tools/                     # 内置工具 + MCP 加载器
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatView.vue       # 主对话界面
│   │   │   ├── MessageItem.vue    # 消息渲染（Markdown + 代码高亮 + 沙盒预览）
│   │   │   ├── InputBox.vue       # 输入框 + 图片管理
│   │   │   ├── CognitivePanel.vue # 右侧认知面板
│   │   │   ├── PlanFlowCanvas.vue # 任务流程图（@antv/x6）
│   │   │   ├── ClarificationCard.vue
│   │   │   └── AgentStatusBubble.vue
│   │   ├── composables/useChat.ts # 核心状态管理
│   │   └── types/                 # TypeScript 类型
│   ├── nginx.conf
│   └── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## LangGraph 执行流程

```
用户消息
    │
    ▼
semantic_cache_check ──命中──▶ save_response ──▶ END
    │未命中
    ▼
vision_node          （图片分析，流式推送思考过程）
    │
    ▼
route_model          （chat / code / search / search_code）
    │
    ▼
retrieve_context     （历史消息 + RAG 向量检索）
    │
    ▼
planner              （search 类：生成 1-10 步执行计划）
    │
    ▼
call_model ──工具调用──▶ tools ──▶ call_model_after_tool
    │无工具调用                            │
    ▼                                      │
reflector ◀────────────────────────────────┘
    │
    ├── continue / retry ──▶ call_model（下一步）
    │
    └── done ──▶ save_response ──▶ compress_memory ──▶ END
```

---

## API 接口

后端启动后访问 **http://localhost:8000/docs** 查看完整文档。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 流式对话（SSE） |
| `POST` | `/api/chat/{id}/stop` | 停止对话 |
| `GET` | `/api/conversations` | 对话列表 |
| `POST` | `/api/conversations` | 创建对话 |
| `GET` | `/api/conversations/{id}` | 对话详情 |
| `DELETE` | `/api/conversations/{id}` | 删除对话 |
| `GET` | `/api/conversations/{id}/tools` | 工具调用历史 |
| `GET` | `/api/tools` | 可用工具列表 |

---

## 许可证

[MIT License](LICENSE)
