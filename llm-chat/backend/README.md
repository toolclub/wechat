# ChatFlow 后端架构详解

## 目录

- [整体请求链路](#整体请求链路)
- [LangGraph 图结构](#langgraph-图结构)
- [多模态输入](#多模态输入)
- [语义缓存（Semantic Cache）](#语义缓存semantic-cache)
- [asyncio 并发架构（核心优化）](#asyncio-并发架构核心优化)
- [SSE 事件处理链](#sse-事件处理链)
- [think-block 三层过滤](#think-block-三层过滤)
- [记忆系统](#记忆系统)
- [节点详解](#节点详解)
- [配置参考](#配置参考)

---

## 整体请求链路

```mermaid
sequenceDiagram
    participant B as 浏览器
    participant N as nginx
    participant F as FastAPI
    participant R as runner.py
    participant G as LangGraph

    B->>N: POST /api/chat {message, images?}
    N->>F: proxy_pass (timeout 600s)
    F->>R: stream_response(images=[...])
    R->>R: 创建 asyncio.Queue
    R->>G: create_task(_graph_producer)
    R->>R: create_task(_heartbeat)

    loop 每 20 秒（心跳）
        R-->>N: data: {"ping":true}
        N-->>B: 心跳（重置超时计时器）
    end

    loop 图执行期间
        G-->>R: LangGraph 事件
        R-->>N: data: {SSE事件}
        N-->>B: 流式推送
    end

    R-->>N: data: {"done":true}
    N-->>B: 流结束
```

> **关键**：心跳每 20s 发一次，让 nginx 的 `proxy_read_timeout` 计时器持续重置。`<think>` 块被过滤不发送，否则长推理时间会导致 nginx 判定连接空闲而断流。

---

## LangGraph 图结构

### 完整图（ROUTER_ENABLED=true）

```mermaid
flowchart TD
    START([START]) --> semantic_cache_check

    semantic_cache_check["⚡ semantic_cache_check\n语义缓存检查（最前置）\n含图片时直接跳过"]
    semantic_cache_check -->|cache HIT| save_response
    semantic_cache_check -->|cache MISS| route_model

    route_model["🔀 route_model\n判断意图\nchat / code / search / search_code"]
    route_model --> retrieve_context

    retrieve_context["📚 retrieve_context\nRAG检索 + 组装历史消息\n含图片时构建多模态 HumanMessage"]
    retrieve_context --> planner

    planner["📋 planner\n生成执行计划\n仅 search / search_code 触发"]
    planner --> call_model

    call_model["🧠 call_model\ntool_model 调用\n绑定工具（search路由）"]

    call_model -->|有工具调用| tools
    call_model -->|无工具 + 有计划| reflector
    call_model -->|无工具 + 无计划| save_response

    tools["⚙️ tools\nToolNode\n并发执行工具"]
    tools --> call_model_after_tool

    call_model_after_tool["🧠 call_model_after_tool\nanswer_model 综合工具结果"]
    call_model_after_tool -->|还有工具调用| tools
    call_model_after_tool -->|无工具 + 有计划| reflector
    call_model_after_tool -->|无工具 + 无计划| save_response

    reflector["🔍 reflector\n评估步骤完成情况"]
    reflector -->|continue| call_model
    reflector -->|retry| call_model
    reflector -->|done| save_response

    save_response["💾 save_response\n持久化消息 + 工具摘要\n含图片时生成描述占位符"]
    save_response --> compress_memory

    compress_memory["🗜️ compress_memory\n按需压缩 → 写 Qdrant"]
    compress_memory --> END([END])

    style route_model fill:#dbeafe
    style planner fill:#fef3c7
    style call_model fill:#dcfce7
    style call_model_after_tool fill:#dcfce7
    style reflector fill:#fce7f3
    style tools fill:#f3e8ff
    style save_response fill:#e0f2fe
    style compress_memory fill:#e0f2fe
```

### 递归上限计算

`recursion_limit = 60`，支持最多 **13 个计划步骤**：

```
固定(5) + 每步(4) × 13步 = 57 ≤ 60
```

### chat / code 快速路径

```mermaid
flowchart LR
    S([START]) --> CC[semantic_cache_check]
    CC -->|HIT| SR[save_response]
    CC -->|MISS| RM[route_model]
    RM --> RC[retrieve_context]
    RC --> PL["planner\n(跳过，返回空计划)"]
    PL --> CM[call_model]
    CM -->|无工具| SR
    CM -->|有工具| T[tools]
    T --> CMT[call_model_after_tool]
    CMT --> SR
    SR --> CMP[compress_memory]
    CMP --> E([END])
```

---

## 多模态输入

支持图片 + 文字混合输入，全链路处理如下：

### 请求到 LLM

```mermaid
flowchart LR
    FE["前端\nInputBox\n粘贴/拖拽/上传图片"] -->|base64，去掉 data: 前缀| API["POST /api/chat\n{message, images:[...]}"]
    API --> RC["retrieve_context\n构建多模态 HumanMessage"]
    RC --> LLM["LLM\n(需支持视觉的模型)"]
```

`retrieve_context` 构建的多模态消息格式（OpenAI 兼容）：
```json
[
  {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
  {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
  {"type": "text",      "text": "用户的文字消息"}
]
```

### 存储替换

base64 原始数据不存入数据库和记忆系统。`save_response` 在持久化前调用 LLM 生成图片描述，存储格式为：

```
{用户文字消息}
[用户上传了图片：图片内容大致为{AI描述，不超过50字}]
```

### 多模态与缓存的关系

- `semantic_cache_check`：含图片请求直接跳过缓存检查
- `save_response`：含图片的回复不写回缓存

> 支持的模型：MiniMax M2.7、GPT-4o、GLM-4V、Ollama LLaVA 等支持 `image_url` 格式的视觉模型。

---

## 语义缓存（Semantic Cache）

相同语义的问题直接命中缓存，**跳过整个 LLM 推理链路**，响应时间从秒级降至毫秒级。

### 缓存流程

```mermaid
flowchart LR
    Q["用户提问"] --> IMG{"含图片?"}
    IMG -->|是| MISS2["直接跳过\n→ LLM"]
    IMG -->|否| EMB["embed_text(question)"]
    EMB --> KNN["RediSearch KNN\n(@namespace:{ns})=>[KNN 1]"]
    KNN -->|similarity ≥ threshold| HIT["Cache HIT\n返回缓存答案"]
    KNN -->|similarity < threshold| MISS["Cache MISS\n调用 LLM"]
    MISS --> LLM["LLM 推理"]
    LLM --> STORE["cache.store()\n写回 Redis\n（仅 chat/code，无工具，无图片）"]
    HIT --> SSE["SSE: status=cache_hit\n+ content=..."]
    STORE --> SSE2["SSE: 正常流式输出"]
```

### 命名空间隔离（`SEMANTIC_CACHE_NAMESPACE_MODE`）

| 模式 | namespace 值 | 适用场景 |
|------|-------------|---------|
| `prompt`（默认）| `md5(system_prompt)[:8]` | 同 system_prompt 跨 session 共享，不同 prompt 隔离 |
| `global` | `"global"` | 所有对话完全共享，最大命中率 |
| `conv` | `conv_id` | 每个 session 独立，相当于禁用跨 session 共享 |

Redis key 格式：`cache:{namespace}:{md5(question)}`

### 不缓存的场景

- 含图片的请求（图片内容影响语义，且不参与向量匹配）
- `search` / `search_code` 路由（含实时数据）
- 含工具调用的响应
- 缓存命中的回复（避免二次写入）

### OOP 扩展接口

```
SemanticCache (ABC)          ← cache/base.py
├── RedisCacheBackend        ← cache/redis_cache.py（当前实现）
└── _NullCache               ← 禁用/降级时自动启用

CacheFactory.get_cache()     ← 全局单例入口
```

新增后端只需：继承 `SemanticCache`，实现 `init/lookup/store/clear`，在 `cache/factory.py` 的 `init_cache()` 中按配置选择实例化。

### 新增 SSE 事件

| 事件 | 含义 |
|------|------|
| `{"status": "cache_hit", "similarity": 0.92}` | 命中缓存，后续 content 来自缓存 |

---

## asyncio 并发架构（核心优化）

### 旧版 vs 新版对比

```mermaid
flowchart LR
    subgraph OLD["❌ 旧版：串行"]
        direction TB
        O1["graph.astream_events()"] --> O2["yield chunk"]
        O2 --> O3["nginx 等待..."]
        O3 --> O4["300s 无数据 → 断流"]
    end

    subgraph NEW["✅ 新版：并发队列+心跳"]
        direction TB
        N1["_graph_producer Task"]
        N2["_heartbeat Task\n每 20s"]
        N3["asyncio.Queue"]
        N4["主循环\nawait queue.get()"]
        N1 -->|事件| N3
        N2 -->|ping| N3
        N3 --> N4
        N4 -->|yield| N5["nginx ← 持续有数据"]
    end
```

### stream_response 完整数据流

#### 阶段一：启动

```mermaid
sequenceDiagram
    participant FA as FastAPI
    participant SR as stream_response
    participant Q  as asyncio.Queue
    participant GA as Task A
    participant HB as Task B

    FA->>SR: stream_response(conv_id, message, model, images)
    SR->>SR: 构建 initial_state（含 images 字段）
    SR->>Q: 创建空队列
    SR->>GA: create_task(_graph_producer)
    SR->>HB: create_task(_heartbeat)
    SR->>SR: while True 主循环 await queue.get() 挂起
```

#### 阶段二：正常执行期间的数据流

```mermaid
flowchart TD
    subgraph TaskA["Task A: _graph_producer"]
        A1["graph.astream_events\nrecursion_limit=60"]
        A2["await queue.put event"]
        A1 --> A2 --> A1
    end

    subgraph TaskB["Task B: _heartbeat"]
        B1["await asyncio.sleep 20s"]
        B2["await queue.put ping"]
        B1 --> B2 --> B1
    end

    subgraph MAIN["主协程 while True"]
        M1["await queue.get()"]
        M2{"kind?"}
        M3["dispatcher.dispatch → yield chunk"]
        M4["yield ping SSE"]
        M5["yield error SSE"]
        M6["graph_done=True break"]
        M1 --> M2
        M2 -->|event| M3 --> M1
        M2 -->|ping| M4 --> M1
        M2 -->|error| M5 --> M1
        M2 -->|done| M6
    end

    TaskA -->|put| Q[(asyncio.Queue)]
    TaskB -->|put| Q
    Q -->|get| MAIN
    MAIN -->|yield SSE| NGINX["nginx → 浏览器"]
```

#### 阶段三：客户端断开时的清理

```mermaid
sequenceDiagram
    participant C as 客户端
    participant M as 主协程
    participant A as Task A
    participant B as Task B

    C->>M: TCP 断开 → CancelledError
    M->>M: except CancelledError\ngraph_done = False
    M->>A: graph_task.cancel()
    M->>B: hb_task.cancel() [finally]
    Note over M: 不发 done 事件，静默退出
```

---

## SSE 事件处理链

```mermaid
flowchart TD
    EV["LangGraph astream_events 事件"]

    EV --> D{EventDispatcher\n顺序匹配}

    D -->|on_chain_end + semantic_cache_check| H0["CacheHitEndHandler"]
    D -->|on_chain_start + route_model| H1["RouteStartHandler"]
    D -->|on_chain_end + route_model| H2["RouteEndHandler"]
    D -->|on_chain_start + planner| H3["PlannerStartHandler"]
    D -->|on_chain_end + planner| H4["PlannerEndHandler"]
    D -->|on_chain_end + reflector| H5["ReflectorEndHandler"]
    D -->|on_chat_model_start + call_model*| H6["LLMStartHandler"]
    D -->|on_chat_model_stream + call_model*| H7["LLMStreamHandler\n过滤 think 块"]
    D -->|on_tool_start| H8["ToolStartHandler"]
    D -->|on_tool_end| H9["ToolEndHandler"]
    D -->|on_chain_end + compress_memory| H10["CompressEndHandler\n仅更新 ctx"]

    H0 --> S0["{'status':'cache_hit','similarity':0.92}\n+ {'content':'...'}"]
    H1 --> S1["{'status':'routing'}"]
    H2 --> S2["{'route':{'model':...,'intent':...}}"]
    H3 --> S3["{'status':'planning'}"]
    H4 --> S4["{'plan_generated':{'steps':[...]}}"]
    H5 --> S5["{'plan_generated'} + {'reflection':...}"]
    H6 --> S6["{'status':'thinking','model':'...'}"]
    H7 --> S7["{'content':'...token...'}"]
    H8 --> S8["{'tool_call':{'name':...,'input':...}}"]
    H9 --> TF{"ToolResultFormatter"}
    TF -->|web_search| S9a["{'search_item':...} × N条"]
    TF -->|fetch_webpage| S9b["{'tool_result':{'status':'done|fail'}}"]
    TF -->|其他| S9c["{'tool_result':{'output':'...'}}"]
```

---

## think-block 三层过滤

qwen3 在 search/planning 模式下输出大量 `<think>...</think>` 推理内容，如果不过滤会破坏 markdown 代码块渲染。

```mermaid
flowchart LR
    subgraph L1["层 1：流式过滤\nrunner.py LLMStreamHandler"]
        T1["token chunk"] --> T2{"in_think_block?"}
        T2 -->|是| T3["丢弃，找 </think>"] --> T2
        T2 -->|否| T4["保留，找 <think>"]
    end

    subgraph L2["层 2：存储过滤\nnodes.py save_response"]
        S1["full_response"] --> S2["re.sub(think块)"] --> S3["写入 PostgreSQL"]
    end

    subgraph L3["层 3：渲染过滤\nMessageItem.vue"]
        V1["message.content"] --> V2[".replace(think块正则)"] --> V3["marked.parse()"]
    end
```

---

## 记忆系统

```mermaid
flowchart TD
    subgraph PG["PostgreSQL（短期/结构化）"]
        P1[conversations 表]
        P2[messages 表\n图片存占位符而非 base64]
        P3[tool_events 表]
    end

    subgraph QD["Qdrant（长期/向量）"]
        Q1["向量集合 per conv_id"]
        Q2["cos_similarity 检索"]
    end

    subgraph RC["retrieve_context 节点"]
        R1["向量检索长期记忆"]
        R2{"检索到相关记忆?"}
        R3["forget_mode=false"]
        R4{"新问题与近期话题相关?"}
        R5["forget_mode=true"]
        R1 --> R2
        R2 -->|是| R3
        R2 -->|否| R4
        R4 -->|是| R3
        R4 -->|否| R5
    end

    QD -->|检索| RC
    PG -->|加载历史| RC
    RC -->|组装 messages| LLM["LLM 推理"]
    LLM -->|对话结束| PG
    PG -->|触发压缩| CM["compress_memory → Qdrant"]
```

---

## 节点详解

### 路由决策表

| route | 触发场景 | tool_model | answer_model |
|---|---|---|---|
| `chat` | 通用聊天、推理、翻译、写作 | = answer_model | CHAT_MODEL |
| `code` | 纯代码编写/调试，需求明确 | = answer_model | CHAT_MODEL |
| `search` | 需联网查实时信息，不写代码 | SEARCH_MODEL | SEARCH_MODEL |
| `search_code` | 查文档/仓库后再写代码 | SEARCH_MODEL | CHAT_MODEL |

### reflector 决策逻辑

```mermaid
flowchart TD
    IN["reflector 收到状态"]
    A{"current_idx >= total\n或 step_iters >= 2?"}
    B{"是最后一步且有响应?"}
    C["LLM 评估最近5条消息"]
    D{"LLM 决策"}

    IN --> A
    A -->|是| DONE["done（安全边界）"]
    A -->|否| B
    B -->|是| DONE
    B -->|否| C
    C --> D
    D -->|done| DONE
    D -->|continue| CONT["continue\n下一步 index++"]
    D -->|retry| RETRY["retry\nstep_iterations++（最多2次）"]
    D -->|解析失败| DONE

    DONE --> SR["→ save_response"]
    CONT --> CM2["→ call_model"]
    RETRY --> CM2
```

---

## 配置参考

| 环境变量 | 用途 |
|---|---|
| `LLM_BASE_URL` | LLM 服务地址（OpenAI 兼容，含 `/v1`） |
| `API_KEY` | LLM API Key |
| `EMBEDDING_BASE_URL` | Embedding 服务地址（独立配置，可与 LLM 不同提供商） |
| `CHAT_MODEL` | chat 路由 answer_model |
| `ROUTER_MODEL` | route_model 节点，temperature=0 |
| `SEARCH_MODEL` | search 路由 tool_model |
| `SUMMARY_MODEL` | compress_memory 摘要生成 |
| `EMBEDDING_MODEL` | Qdrant 向量化 + 语义缓存向量化 |
| `ROUTER_ENABLED` | 是否启用 route_model 节点 |
| `ROUTE_MODEL_MAP` | JSON，各路由类型对应模型 |
| `LONGTERM_MEMORY_ENABLED` | 是否启用 Qdrant 长期记忆 |
| `QDRANT_URL` | Qdrant 地址 |
| `SEMANTIC_CACHE_ENABLED` | 是否启用语义缓存 |
| `REDIS_URL` | Redis 连接串 |
| `SEMANTIC_CACHE_INDEX` | RediSearch 索引名 |
| `SEMANTIC_CACHE_THRESHOLD` | 命中相似度阈值（0-1，推荐 0.85~0.92） |
| `SEMANTIC_CACHE_NAMESPACE_MODE` | 命名空间模式：`prompt` / `global` / `conv` |
| `SHORT_TERM_MAX_TURNS` | 短期记忆保留轮数 |
| `COMPRESS_TRIGGER` | 触发压缩的消息条数 |
| `recursion_limit` | 60（硬编码），支持最多 13 步计划 |
