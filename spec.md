# ChatFlow 架构规格文档

> 核心原则：**DB 驱动 + 状态机 + 模型无关**
> 前端只渲染，后端只存储，模型只推理，三者通过结构化数据契约解耦。

---

## 一、架构总览

```
用户浏览器 (Vue 3)
    ↕ SSE / REST
FastAPI Backend
    ├── LangGraph Agent（图执行引擎）
    │   ├── retrieve_context  → 组装 LLM 上下文
    │   ├── call_model        → LLM 推理 + 工具调用
    │   ├── tools             → 沙箱执行 / 搜索 / 抓取
    │   ├── call_model_after_tool → 综合工具结果
    │   ├── reflector         → 步骤评估（快速路径 >90%）
    │   ├── planner           → 任务规划
    │   └── save_response     → 持久化到 DB
    ├── StreamSession（DB-first 流管理）
    ├── Memory Store（PostgreSQL + 内存缓存）
    ├── Qdrant（长期向量记忆）
    └── Redis（语义缓存）
```

### 数据流

```
用户消息 → 立即 INSERT messages 表
         → LangGraph 图执行
         → 每 500ms 批量写 event_log + UPDATE stream_buffer
         → 工具调用立即 INSERT tool_executions
         → 完成后 UPDATE messages.content + stream_completed=True
         → 前端通过 SSE 实时渲染
         → 刷新后从 DB full-state API 完整恢复
```

---

## 二、核心设计原则

### 2.1 DB 是唯一真相源

| 规则 | 说明 |
|------|------|
| 所有状态由 DB 字段表达 | 不从文本推断工具成败、不从内容解析澄清数据 |
| 结构化数据存独立字段 | `tool_summary`、`step_summary`、`clarification_data` 各自独立，不混入 `content` |
| 前端从 API 拿结构化数据 | 不对模型输出做正则/字符串解析 |
| 内存只做推送缓存 | 进程崩溃后从 DB 恢复，不丢数据 |

### 2.2 状态机驱动

所有实体的状态转换在 `db/state_machine.py` 中显式声明：

```python
# 对话状态机
ACTIVE → STREAMING → COMPLETED
                   → ERROR
                   → ACTIVE（用户停止）
COMPLETED → STREAMING（新一轮）

# 消息状态机
PRE_WRITE → STREAMING → FINALIZED
                      → PARTIAL（中断保存）

# 工具执行状态机
RUNNING → DONE | ERROR | TIMEOUT

# SSE 事件类型注册表（按优先级排序）
DONE > ERROR > TOOL_RESULT > TOOL_CALL > THINKING > CONTENT > PING
```

非法转换只记警告不抛异常（避免卡死），但会在日志中暴露问题。

### 2.3 模型无关

```
┌─────────────────────────────────────────────────┐
│           业务逻辑层（模型无关）                    │
│  图节点、状态机、DB 存储、前端渲染                   │
└──────────────────────┬──────────────────────────┘
                       │ OpenAI 兼容协议
┌──────────────────────▼──────────────────────────┐
│           LLM 适配层（llm/client.py）              │
│  AsyncOpenAI 封装，自动检测 reasoning_content      │
└──────────────────────┬──────────────────────────┘
                       │ HTTP
            ┌──────────▼──────────┐
            │  任意 OpenAI 兼容 API │
            │  MiniMax / Qwen /    │
            │  Claude / GPT / 本地  │
            └─────────────────────┘
```

**切换模型 = 改 `.env` 配置文件**，无需改代码：

```bash
LLM_BASE_URL="https://api.anthropic.com/v1"
CHAT_MODEL="claude-sonnet-4-20250514"
```

---

## 三、DB Schema

### 核心表

```sql
-- 对话
conversations (
  id, title, system_prompt, mid_term_summary, mid_term_cursor,
  client_id, status, mode, model_name, created_at, updated_at
)

-- 消息（独立字段，不混入 content）
messages (
  id, conv_id, message_id, role, content, thinking,
  stream_buffer, stream_completed, sequence_number, images,
  tool_summary,          -- 工具调用记录（独立字段）
  step_summary,          -- 执行过程摘要（独立字段）
  clarification_data,    -- 澄清数据 JSONB（独立字段）
  created_at
)

-- 工具调用（独立记录，带状态机）
tool_executions (
  id, conv_id, message_id, tool_name, tool_input,
  tool_output, search_items, status, sequence_number,
  duration, created_at
)

-- SSE 事件持久化（断线恢复）
event_log (id, conv_id, message_id, event_type, event_data, sse_string, created_at)

-- 执行计划
plan_steps (id, conv_id, goal, steps, current_step, total_steps, created_at, updated_at)

-- 文件产物（关联到 message）
artifacts (id, conv_id, message_id, name, path, language, content, size, slide_count, created_at)
```

---

## 四、COMPAT 兼容层清单

以下代码依赖特定模型行为，已标记 `# COMPAT:`，明确了移除条件。

| ID | 位置 | 依赖 | 影响 | 移除条件 |
|----|------|------|------|---------|
| C1 | `llm_handlers.py` | `<think>` 标签状态机 | Qwen3/GLM 推理块分离 | 模型 API 支持 `enable_thinking` 结构化字段 |
| C2 | `save_response_node.py` | `<think>` 正则移除 | 存储前清理 | 同 C1 |
| C3 | `save_response_node.py` | `[NEED_CLARIFICATION]` 文本解析 | 模型主动澄清 | system prompt 改用 tool_call 发起澄清 |
| C4 | `llm_handlers.py` | `_TOOL_CALL_ARTIFACTS` 过滤 | MiniMax 流式输出残留 | MiniMax 修复此 bug |
| C5 | `base.py` | `content=None` 强制 | MiniMax tool_calls 时注入 XML | 同 C4 |
| C6 | `planner_node.py` | JSON 文本提取 + 引号修复 | 模型不支持 JSON mode | 所有模型支持 `response_format: json_object` |
| C7 | `compressor.py` | `【工具调用记录】` 标记清理 | 旧数据迁移 | 所有旧消息完成压缩 |
| C8 | `context_builder.py` | `【执行过程摘要】` 标记截断 | 旧数据兼容 | 同 C7 |
| C9 | `useChat.ts` | `.replace()` 清理旧标记 | 前端旧数据显示 | 同 C7 |
| C10 | `MessageItem.vue` | PPT 文件名正则提取 | 兜底方案 | 所有 artifact 通过 DB 外键关联 |

**关键特性**：所有 COMPAT 代码对不适用的模型**空转无副作用**。换模型不会崩溃，只是兼容代码变为冗余。

---

## 五、模型切换指南

### 5.1 零代码切换

修改 `.env` 即可：

```bash
# 示例：MiniMax → Claude
LLM_BASE_URL="https://api.anthropic.com/v1"
API_KEY="sk-ant-xxx"
CHAT_MODEL="claude-sonnet-4-20250514"
SUMMARY_MODEL="claude-haiku-4-5-20251001"

# 示例：MiniMax → Qwen
LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
API_KEY="sk-xxx"
CHAT_MODEL="qwen-plus"

# 视觉模型可独立配置
VISION_BASE_URL="https://open.bigmodel.cn/api/paas/v4"
VISION_MODEL="glm-4v-plus"

# 路由可为不同意图分配不同模型
ROUTE_MODEL_MAP={"code":"claude-sonnet-4-20250514","search":"qwen-plus","chat":"gpt-4o"}
```

### 5.2 需要桥接的场景

如果新模型的 API **不完全兼容 OpenAI 协议**，需要在 `llm/client.py` 中添加适配：

```python
# llm/client.py 已有的适配点：
# 1. reasoning_content 字段检测（DeepSeek-R1、Claude Thinking）→ 自动转为 THINK 前缀
# 2. tool_calls 流式拼装 → 通用 OpenAI 协议
# 3. extra_body 透传 → 支持厂商特定参数（如 response_format）

# 如果新模型有新的结构化字段，只需在 astream() 中添加检测：
if hasattr(delta, "new_thinking_field") and delta.new_thinking_field:
    yield "\x00THINK\x00" + delta.new_thinking_field
```

工作量：通常 5~10 行代码。

### 5.3 什么情况会出问题

| 场景 | 会不会崩 | 表现 |
|------|---------|------|
| 模型不输出 `<think>` 块 | 不会 | COMPAT 代码空转，thinking 面板为空 |
| 模型不支持 function calling | **会** | 工具调用失败，需要换支持 FC 的模型 |
| 模型输出非标准 JSON | 不会 | planner 有 3 层兜底（JSON mode → 正则提取 → 单步兜底） |
| 模型审核拒绝 | 不会 | 返回优雅降级文本 "触发安全审核" |
| API 返回格式不同 | 看情况 | 如果兼容 OpenAI 协议则无问题 |

---

## 六、开发注意事项

### 6.1 绝对禁止

- **禁止从模型输出文本中推断状态**：用 DB 字段（`tool_executions.status`、`messages.clarification_data`）
- **禁止在 `content` 字段中嵌入结构化数据**：用独立字段（`tool_summary`、`step_summary`）
- **禁止硬编码 SSE 事件类型字符串**：用 `SSEEventType` 枚举
- **禁止无脑截断消息列表**：历史窗口由 `context_builder` 控制，当前轮工具调用对必须完整
- **禁止在非 async 函数中使用 await**

### 6.2 新增功能时

1. **新增 DB 字段**：在 `db/models.py` 添加列 + `db/migrate.py` 添加幂等 ALTER + `memory/schema.py` 更新 dataclass
2. **新增状态**：在 `db/state_machine.py` 添加枚举值 + 合法转换
3. **新增 SSE 事件类型**：在 `SSEEventType` 枚举添加 + `_SSE_PRIORITY_ORDER` 列表排序
4. **新增工具**：在 `tools/builtin/` 添加 `@tool` 函数 + `tools/__init__.py` 注册
5. **新增图节点**：继承 `BaseNode` + 在 `graph/agent.py` 注册 + `edges.py` 添加路由

### 6.3 前端开发

- **只渲染 API 返回的结构化数据**，不解析模型文本
- **SSE 事件即时渲染**：`onChunk`、`onToolCall`、`onThinking` 等回调直接更新 Vue 响应式状态
- **刷新恢复**：调用 `full-state` API 从 DB 完整重建 UI（消息 + 工具调用 + 计划 + 产物）
- **COMPAT 代码加注释**：旧数据清理逻辑必须标注 `// COMPAT:` 和移除条件

### 6.4 并发安全

- `_finalize_lock`：防止 `_periodic_flush` 和 `_finalize_message` 竞态写入 messages 表
- `_finalized` 标记：幂等保护，防止重复终态化
- event_log 写入不受 `_finalized` 限制：done/stopped 事件必须持久化（断线恢复依赖）
- 对话状态转换经 `validate_conv_transition()` 校验

---

## 七、三层记忆架构

```
短期（滑动窗口）     中期（语义压缩）      长期（向量检索）
messages 表最近 N 轮  mid_term_summary     Qdrant collection
context_builder 组装  compressor 触发压缩   retriever 相似度检索
─────────────────────────────────────────────────────────
     ← 实时对话 →    ← 超过阈值自动压缩 →   ← 按需 RAG 注入 →
```

- 短期：`SHORT_TERM_MAX_TURNS` 轮滑动窗口，超长回复截断到 800 字符
- 中期：累积超过 `COMPRESS_TRIGGER` 条后触发 LLM 摘要，游标前推
- 长期：压缩时同步写入 Qdrant，检索时按相似度注入系统提示（去重）

---

## 八、工具调用全链路

```
call_model 返回 tool_calls
  → ToolNode 并行执行
    → sandbox_tools: SSH 远程执行，流式推送 sandbox_output
    → web_search: DuckDuckGo 搜索，逐条推送 search_item
    → fetch_webpage: HTTP 抓取 + HTML 清洗
  → tool_result SSE 事件
    → stream.py 立即 UPDATE tool_executions（含 status、output、search_items）
  → call_model_after_tool 综合结果
    → 可继续调用工具（每步最多 6 次）
    → 或生成最终回复
```

### 工具失败处理

1. `SandboxFormatter` 从输出提取 `exit_code`，非 0 时设 `status="error"`
2. `_track_sse_for_db` 将 status 透传到 `tool_executions` 表
3. `reflector_node` 检查 `_last_tool_failed()`：最后一步工具失败时 retry 而非 done
4. `call_model_after_tool` 检查 `_check_last_tool_failed()`：生成修复指令

---

## 九、已完成的重构项

| 项 | 状态 | 说明 |
|----|------|------|
| P0-1 artifacts message_id 外键 | ✅ | 前端从 DB 关联恢复产物，不依赖正则 |
| P0-2 澄清机制重构 | ✅ | 预检走 state 字段，模型输出走 COMPAT 降级 |
| P1-1 think 块结构化 | ✅ 标记 | COMPAT 标记，待 API 支持 enable_thinking |
| P1-2 工具调用残留文本 | ✅ | 流式层拦截 + 存储层兜底，均标记 COMPAT |
| P1-3 工具执行状态从 DB 读取 | ✅ | `tool_executions.status` 替代文本关键词匹配 |
| P1-4 工具/步骤摘要分离 | ✅ | `tool_summary`、`step_summary` 独立字段 |
| P1-5 计划 JSON mode | ✅ | 首次尝试 JSON mode，降级文本提取加 COMPAT |
| P1-6 think 块状态机标记 | ✅ 标记 | COMPAT 标记，同 P1-1 |
| 状态机架构 | ✅ | 对话/消息/工具/SSE 四层状态机 |
| search_items 写入 DB | ✅ | 搜索结果累积后写入 tool_executions.search_items |
| 工具失败状态写入 DB | ✅ | SandboxFormatter 提取 exit_code 设 status=error |
| 消息终态化锁 | ✅ | `_finalize_lock` 防竞态，event_log 不受限 |
| 消息不截断 | ✅ | 删除 `_MAX_MESSAGES` 截断，保持工具调用对完整 |
| reflector 工具失败检测 | ✅ | 最后一步工具失败时 retry，不盲目 done |
| sandbox 超时提升 | ✅ | 30s → 120s，覆盖 mvn/gradle 构建 |
| 每步工具调用上限提升 | ✅ | 3 → 6，覆盖 构建+检查+启动+验证+清理 |
