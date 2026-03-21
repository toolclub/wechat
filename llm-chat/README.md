# LLM Chat — 本地大语言模型对话系统

## 目录结构

```
llm-chat/
├── backend/
│   ├── main.py              # FastAPI 主入口
│   ├── config.py            # 集中配置（含功能开关）
│   ├── harness.py           # Agent 总线，连接各层
│   ├── ollama_client.py     # Ollama API 客户端
│   ├── models.py            # Pydantic 数据模型
│   ├── layers/
│   │   ├── prompt.py        # 第 1 层：System Prompt 管理
│   │   ├── capability.py    # 第 2 层：模型列表、Embedding
│   │   ├── memory.py        # 第 3 层：记忆数据结构
│   │   ├── longterm.py      # 第 3b 层：长期记忆（Qdrant RAG）
│   │   ├── runtime.py       # 第 4 层：流式/同步调用
│   │   ├── state.py         # 第 5 层：进程内工作记忆
│   │   ├── context.py       # 第 6 层：上下文组装 + 压缩
│   │   ├── persistence.py   # 第 7 层：磁盘持久化
│   │   ├── verification.py  # 第 8 层：日志可观测性
│   │   └── extension.py     # 第 9 层：CORS 等扩展
│   └── conversations/       # 对话持久化存储（自动创建）
└── frontend/
    ├── src/
    │   ├── App.vue
    │   ├── main.ts
    │   ├── style.css
    │   ├── api/index.ts
    │   ├── components/
    │   │   ├── Sidebar.vue
    │   │   ├── ChatView.vue
    │   │   ├── MessageItem.vue
    │   │   └── InputBox.vue
    │   ├── composables/useChat.ts
    │   └── types/index.ts
    ├── package.json
    └── vite.config.ts
```

---

## 前提条件

1. 安装 [Ollama](https://ollama.com/download)（Windows 版双击安装，安装后自动后台运行）
2. 下载模型：
   ```bash
   ollama pull qwen2.5:14b      # 对话主模型
   ollama pull qwen2.5:1.5b     # 摘要压缩模型
   ollama pull bge-m3           # Embedding 模型（长期记忆启用时需要）
   ```
3. （可选）部署 [Qdrant](https://qdrant.tech/documentation/quick-start/) 以启用长期记忆：
   ```bash
   docker run -p 6333:6333 qdrant/qdrant
   ```
   > 不部署 Qdrant 时，将 `config.py` 中的 `LONGTERM_MEMORY_ENABLED` 设为 `False` 即可。

---

## 启动后端

```bash
cd llm-chat/backend

# 创建虚拟环境
python -m venv venv

# 激活（Windows）
venv\Scripts\activate

# 安装依赖
pip install -e .

# 启动
python main.py
```

后端运行在 http://localhost:8000，API 文档：http://localhost:8000/docs

---

## 启动前端

```bash
cd llm-chat/frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端运行在 http://localhost:5173

---

## 每次使用

```bash
# 1. 确认 Ollama 已运行
ollama list

# 2. 启动后端（新终端）
cd llm-chat/backend
venv\Scripts\activate
python main.py

# 3. 启动前端（新终端）
cd llm-chat/frontend
npm run dev
```

浏览器打开 http://localhost:5173 即可使用。

---

## 记忆体系

系统采用三级记忆架构，兼顾上下文丰富性与 Token 效率：

### 1. 短期记忆（滑动窗口）

最近 `SHORT_TERM_MAX_TURNS`（默认 10）轮的完整对话原文，每轮都会发送给模型。对话历史永久保留在磁盘，不会删除。

### 2. 中期摘要（语义压缩）

当未摘要的消息数量达到 `COMPRESS_TRIGGER`（默认 8）轮时，自动触发压缩：
- 用轻量摘要模型（`qwen2.5:1.5b`）将旧对话压缩为滚动摘要
- 摘要以 `【对话背景摘要】` 的形式注入上下文
- 原始消息永远不删除，游标向前推进

### 3. 长期记忆（RAG 向量检索）

> 需要部署 Qdrant，并将 `LONGTERM_MEMORY_ENABLED = True`

- 每次触发压缩时，将该批对话 Q&A 对批量写入 Qdrant（而非每轮写入）
- 每轮对话开始前，用当前问题做 Embedding 检索最相关的历史 Q&A
- 相关结果以 `【长期记忆】` 的形式注入上下文
- 检索分数低于 `LONGTERM_SCORE_THRESHOLD`（默认 0.5）的结果自动过滤

---

## 选择性遗忘

当模型收到的问题与当前对话历史无关时，系统会自动"忘记"无关上下文，只将最近 `SHORT_TERM_FORGET_TURNS`（默认 2）轮发送给模型，避免无关历史干扰回答质量。

### 触发条件（同时满足）

1. **RAG 未命中**：向量检索没有找到相关历史记忆（`LONGTERM_MEMORY_ENABLED=False` 时此条件视为满足）
2. **话题不相关**：
   - 若已有摘要：当前问题与摘要的余弦相似度低于 `SUMMARY_RELEVANCE_THRESHOLD`（默认 0.4）
   - 若尚无摘要（早期对话）：当前问题与最近 2 条用户消息的平均余弦相似度低于阈值

### 效果示例

```
第1轮：如何用 Python 写快速排序？   → 正常流程（历史不足）
第2轮：能再优化一下时间复杂度吗？   → 正常流程（相关追问，相似度高）
第3轮：苹果是什么颜色？             → 触发遗忘（话题切换，只发近2轮）
```

### 相关配置

```python
LONGTERM_MEMORY_ENABLED = True      # 是否启用 RAG 长期记忆
SUMMARY_RELEVANCE_THRESHOLD = 0.4   # 相似度低于此值触发遗忘
SHORT_TERM_FORGET_TURNS = 2         # 遗忘模式下只保留最近 N 轮
```

---

## 配置说明（config.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CHAT_MODEL` | `qwen2.5:14b` | 对话主模型 |
| `SUMMARY_MODEL` | `qwen2.5:1.5b` | 摘要压缩模型 |
| `EMBEDDING_MODEL` | `bge-m3` | Embedding 模型 |
| `SHORT_TERM_MAX_TURNS` | `10` | 短期记忆滑动窗口轮数 |
| `COMPRESS_TRIGGER` | `8` | 触发摘要压缩的轮数 |
| `LONGTERM_MEMORY_ENABLED` | `True` | 是否启用 Qdrant 长期记忆 |
| `LONGTERM_SCORE_THRESHOLD` | `0.5` | RAG 最低相似度过滤阈值 |
| `SUMMARY_RELEVANCE_THRESHOLD` | `0.4` | 话题相关性判断阈值（遗忘机制） |
| `SHORT_TERM_FORGET_TURNS` | `2` | 遗忘模式下保留的对话轮数 |
