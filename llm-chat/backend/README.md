# LLM Chat 后端

## 启动步骤

```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. 安装依赖
pip install -e .

# 4. 启动服务
python main.py
```

服务启动后访问 http://localhost:8000/docs 查看 API 文档。

---

## 前提条件

- 已安装并运行 Ollama（https://ollama.com/download）
- 已下载所需模型：
  ```bash
  ollama pull qwen2.5:14b      # 对话主模型
  ollama pull qwen2.5:1.5b     # 摘要压缩模型
  ollama pull bge-m3           # Embedding 模型（长期记忆启用时需要）
  ```
- （可选）已部署 Qdrant，用于长期记忆（RAG）：
  ```bash
  docker run -p 6333:6333 qdrant/qdrant
  ```
  不使用时在 `config.py` 中将 `LONGTERM_MEMORY_ENABLED` 设为 `False`。

---

## 层级架构

```
1. Prompt      → layers/prompt.py        人格 / 提示模板
2. Capability  → layers/capability.py    工具：模型列表、Embedding
3. Memory      → layers/memory.py        数据结构：Message、Conversation
3b.LongTerm   → layers/longterm.py      长期记忆：Qdrant 向量检索（可禁用）
4. Runtime     → layers/runtime.py       代理循环：流式 / 同步调用
5. State       → layers/state.py         工作记忆：进程内存储
6. Context     → layers/context.py       消息组装 + 压缩触发 + 遗忘模式
7. Persistence → layers/persistence.py  磁盘检查点：保存/加载/删除
8. Verification→ layers/verification.py 日志 / 可观测性
9. Extension   → layers/extension.py    CORS、插件
```

---

## 记忆与遗忘机制

### 三级记忆

| 层级 | 名称 | 存储位置 | 触发时机 |
|------|------|----------|----------|
| 短期 | 滑动窗口 | 内存 | 每轮，保留最近 N 轮原文 |
| 中期 | 滚动摘要 | 磁盘 | 累计超过 `COMPRESS_TRIGGER` 轮时压缩 |
| 长期 | 向量检索 | Qdrant | 压缩时批量写入，每轮检索注入 |

### 选择性遗忘（Selective Forgetting）

每轮对话前，系统通过 Embedding 余弦相似度判断当前问题是否与历史相关：

```
RAG 命中？ → 不遗忘
    ↓ 未命中
有摘要？
  ├─ 是 → sim(query, 摘要) ≥ 阈值？→ 不遗忘 / 遗忘
  └─ 否 → sim(query, 近2条用户消息均值) ≥ 阈值？→ 不遗忘 / 遗忘
```

遗忘时只发最近 `SHORT_TERM_FORGET_TURNS` 轮给模型，摘要和长期记忆均不注入。

### LONGTERM_MEMORY_ENABLED 开关

设为 `False` 后：
- 启动时跳过 Qdrant 连接，不报错
- RAG 检索始终返回空（`[]`），视为未命中
- 遗忘机制仍正常工作（基于摘要或近期消息相似度）
- 删除对话时跳过 Qdrant 清除

---

## 主要配置项（config.py）

```python
LONGTERM_MEMORY_ENABLED = True      # False = 不连 Qdrant，禁用 RAG
COMPRESS_TRIGGER = 8                # 每 N 轮触发一次压缩+RAG批量写入
SHORT_TERM_MAX_TURNS = 10           # 滑动窗口保留轮数
SUMMARY_RELEVANCE_THRESHOLD = 0.4  # 话题相关性阈值（遗忘判断）
SHORT_TERM_FORGET_TURNS = 2         # 遗忘模式下保留的最近轮数
LONGTERM_SCORE_THRESHOLD = 0.5     # RAG 最低相似度过滤阈值
LONGTERM_TOP_K = 3                  # RAG 最多返回的记忆条数
```

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/models` | 获取可用模型列表 |
| GET | `/api/conversations` | 获取所有对话 |
| POST | `/api/conversations` | 创建新对话 |
| GET | `/api/conversations/{id}` | 获取对话详情 |
| PATCH | `/api/conversations/{id}` | 更新对话标题/系统提示 |
| DELETE | `/api/conversations/{id}` | 删除对话（含 Qdrant 数据） |
| POST | `/api/chat` | 流式聊天（SSE） |
| GET | `/api/conversations/{id}/memory` | 记忆状态调试接口 |
| POST | `/api/embedding` | Embedding 测试接口 |
