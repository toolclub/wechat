# ChatFlow — 本地 / 云端 LLM 智能对话系统

基于 LangChain + LangGraph 构建的 AI 对话系统，支持多意图路由、自动规划、工具调用、长期记忆、语义缓存和多模态图文识别。

---

## 核心特性

- **多模态输入**：支持图片 + 文字混合输入（粘贴 / 拖拽 / 上传），图片以 base64 data URI 发给 LLM，存储时自动替换为 AI 生成的描述占位符
- **多意图路由**：自动识别问题类型（代码 / 搜索 / 对话 / 搜索+代码），路由到对应模型
- **语义缓存**：相似问题命中 Redis Search 缓存，跳过整个 LLM 推理链路，响应从秒级降至毫秒级
- **自动规划**：复杂任务自动拆分为多步骤执行计划，可视化展示进度
- **工具调用**：Web 搜索、网页阅读、时间查询、计算器，支持 MCP 协议扩展
- **三级记忆体系**：短期（滑动窗口）→ 中期（语义压缩摘要）→ 长期（Qdrant RAG 向量检索）
- **选择性遗忘**：话题切换时自动忽略无关历史，保持回答质量
- **云端 / 本地 API 通吃**：统一 OpenAI 兼容接口，一键切换 Ollama / MiniMax / GLM / OpenAI 等任意提供商
- **流式 SSE 输出**：实时逐 token 渲染，工具调用进度实时展示

---

## 快速开始

### 方式一：Docker Compose 一键部署（推荐）

**前提**：安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)

**配置 `.env`**：

```bash
cd llm-chat
cp .env.example .env
# 编辑 .env，填入 LLM 提供商信息（见下方配置说明）
```

**启动**：

```bash
docker compose up -d

# 查看日志
docker compose logs -f
```

浏览器访问 **http://localhost** 即可使用。

**停止**：
```bash
docker compose down
```

**重新构建**（代码变更后）：
```bash
docker compose up -d --build
```

---

### 方式二：本地手动启动（开发模式）

**前提**：Python 3.11+、Node.js 18+

```bash
# 1. 启动后端
cd llm-chat/backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
python main.py

# 2. 启动前端（新终端）
cd llm-chat/frontend
npm install
npm run dev
```

访问 **http://localhost:5173**

---

## 配置说明

所有配置均通过 `.env` 文件注入，无需修改代码。完整模板见 [`.env.example`](.env.example)。

### LLM 提供商选择

| 提供商 | `LLM_BASE_URL` | `API_KEY` | 备注 |
|--------|---------------|-----------|------|
| 本地 Ollama（Docker 内） | `http://host.docker.internal:11434/v1` | `ollama` | 需本机运行 Ollama |
| 本地 Ollama（宿主机直连） | `http://localhost:11434/v1` | `ollama` | 开发模式用 |
| MiniMax | `https://api.minimaxi.com/v1` | 你的 key | M2.7 支持多模态 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | 你的 key | |
| OpenAI | `https://api.openai.com/v1` | 你的 key | |

Embedding 使用独立的 `EMBEDDING_BASE_URL`，可与 LLM 指向不同提供商（例如 LLM 用云端，Embedding 用本地 Ollama）。

### 主要配置项

| 环境变量 | 说明 |
|---------|------|
| `LLM_BASE_URL` | LLM 服务地址（OpenAI 兼容接口，含 `/v1`） |
| `API_KEY` | LLM API Key |
| `EMBEDDING_BASE_URL` | Embedding 服务地址（独立于 LLM） |
| `CHAT_MODEL` | 主对话模型名称 |
| `SUMMARY_MODEL` | 摘要压缩模型（速度优先） |
| `EMBEDDING_MODEL` | Embedding 模型名称 |
| `ROUTER_ENABLED` | 是否启用意图路由（`true` / `false`） |
| `ROUTER_MODEL` | 意图分类模型（速度优先） |
| `ROUTE_MODEL_MAP` | JSON 格式，各路由类型对应模型 |
| `SEMANTIC_CACHE_ENABLED` | 是否启用语义缓存 |
| `REDIS_URL` | Redis 连接串（Docker 内用 `redis://redis:6379`） |
| `SEMANTIC_CACHE_THRESHOLD` | 缓存命中相似度阈值（推荐 0.85~0.92） |
| `LONGTERM_MEMORY_ENABLED` | 是否启用 Qdrant 长期记忆 |
| `QDRANT_URL` | Qdrant 地址（Docker 内用 `http://qdrant:6333`） |

---

## 多模态使用

在输入框：
- **粘贴**：`Ctrl+V` 粘贴截图或复制的图片
- **拖拽**：拖入图片文件
- **上传**：点击输入框旁的图片按钮

图片在输入框上方预览，支持删除单张。发送后图片与文字一起送给 LLM 识别。

> **注意**：需要使用支持多模态的模型（如 MiniMax M2.7、GPT-4o、GLM-4V 等）。多模态请求自动跳过语义缓存。

---

## 项目结构

```
llm-chat/
├── backend/
│   ├── config.py          # 配置中心（pydantic-settings，从 .env 读取）
│   ├── main.py            # FastAPI 入口
│   ├── models.py          # Pydantic 请求模型（含 images 字段）
│   ├── graph/             # LangGraph Agent 图
│   │   ├── agent.py       # 图构建与编译
│   │   ├── nodes.py       # 路由 / 规划 / 执行 / 反思节点
│   │   ├── edges.py       # 条件路由逻辑
│   │   ├── runner.py      # 流式执行 + SSE 事件生成
│   │   ├── state.py       # GraphState 类型定义
│   │   └── event_types.py # SSE 事件类型定义
│   ├── cache/             # 语义缓存层
│   │   ├── base.py        # SemanticCache 抽象基类
│   │   ├── redis_cache.py # RedisCacheBackend（Redis Search KNN）
│   │   └── factory.py     # 缓存单例工厂
│   ├── llm/               # LLM / Embedding 工厂
│   ├── memory/            # 短期 + 中期记忆
│   ├── rag/               # 长期记忆（Qdrant RAG）
│   ├── tools/             # 内置工具 + MCP 加载器
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/    # Vue 组件（InputBox 含图片预览 / MessageItem / CognitivePanel）
│   │   ├── composables/   # useChat 组合式函数
│   │   ├── types/         # TypeScript 类型定义
│   │   └── api/           # 后端 API 调用封装
│   ├── nginx.conf         # 生产 Nginx 配置
│   └── Dockerfile
├── docker-compose.yml     # 五容器编排（backend + frontend + qdrant + postgres + redis）
├── .env.example           # 配置模板
├── LICENSE
└── CHANGELOG.md
```

---

## 三级记忆体系

| 层级 | 机制 | 存储 |
|------|------|------|
| **短期记忆** | 滑动窗口（最近 10 轮） | PostgreSQL |
| **中期摘要** | 达到触发轮数时自动压缩 | PostgreSQL |
| **长期记忆** | 压缩时写入 Qdrant，每轮检索 Top-K | Qdrant 向量库 |

**选择性遗忘**：当前问题与历史话题相似度低于阈值时，自动只发近 2 轮消息给模型，避免无关历史干扰。

---

## 语义缓存

相同语义的问题（如"Python 怎么读文件？"和"如何用 Python 打开文件？"）命中缓存后直接返回答案，完全跳过 LLM 推理。

**不缓存的场景**：`search` / `search_code`（含实时数据）、含工具调用的回复、含图片的请求。

缓存支持三种命名空间隔离模式（`SEMANTIC_CACHE_NAMESPACE_MODE`）：
- `prompt`（默认）：同 system_prompt 跨会话共享
- `global`：所有对话共享，命中率最高
- `conv`：每个会话独立

---

## MCP 工具扩展

在 `.env` 中添加：

```bash
MCP_SERVERS={"filesystem":{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","./data"],"transport":"stdio"}}
```

---

## API 文档

后端启动后访问：**http://localhost:8000/docs**

主要接口：
- `POST /api/chat` — 流式对话（SSE），支持 `images` 字段
- `GET /api/conversations` — 对话列表
- `GET /api/tools` — 可用工具列表
- `GET /api/conversations/{id}/memory` — 记忆状态调试
- `GET /api/conversations/{id}/tools` — 工具调用历史

---

## 许可证

[MIT License](LICENSE)
