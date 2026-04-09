# 设计文档：沙箱会话持久化 + 文件打包下载

## 一、问题

### 问题 1：沙箱 Worker 分配不持久
当前 `SandboxManager._sessions` 是进程内 dict，记录 `conv_id → (worker_id, session_dir)`。
- 用户刷新 → 请求可能落到不同 backend worker → 新 worker 没有映射 → 分配新的沙箱 worker → 之前的文件找不到
- 违反 spec 铁律："永远不信任进程内数据"

### 问题 2：无法打包下载沙箱文件
用户说"帮我打包文件"，模型在沙箱执行 `tar` 打包，但：
- 打包后的 `.tar.gz` 在沙箱 filesystem 中（如 `/sandbox/sess_abc123/output.tar.gz`）
- 前端没有下载沙箱文件的接口
- `artifacts` 表只存 `sandbox_write` 写入的文件，不存 `tar` 命令生成的文件

---

## 二、设计方案

### 2.1 沙箱会话持久化（DB-first）

**方案**：在 `conversations` 表新增 `sandbox_worker_id` 字段。

```sql
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS sandbox_worker_id VARCHAR(50) NOT NULL DEFAULT '';
```

**改动清单**：

| 文件 | 改动 |
|------|------|
| `db/models.py` | `ConversationModel` 加 `sandbox_worker_id` 列 |
| `db/migrate.py` | 加 ALTER TABLE 迁移语句 |
| `sandbox/manager.py` | `_get_worker_for_session()` 优先从 DB 读 `sandbox_worker_id`；首次分配后写 DB |
| `memory/store.py` | `Conversation` dataclass 不需要改（sandbox_worker_id 只由 manager 使用，不走内存缓存） |

**流程**：

```
首次工具调用：
  manager._get_worker_for_session(conv_id)
    → DB 查 conversations.sandbox_worker_id
    → 为空 → 负载均衡选 worker → UPDATE sandbox_worker_id = "w2"
    → 返回 (w2, /sandbox/sess_abc123)

刷新后再次调用：
  manager._get_worker_for_session(conv_id)
    → DB 查 conversations.sandbox_worker_id = "w2"
    → 直接用 w2（不管落到哪个 backend worker）
    → 文件还在 /sandbox/sess_abc123/

Worker 宕机：
  → DB 中 sandbox_worker_id = "w2" 但 w2 不健康
  → 迁移到 w1，UPDATE sandbox_worker_id = "w1"
  → 日志 warning（文件可能丢失）
```

### 2.2 文件打包下载

**方案**：新增一个 `download_file` 工具 + 后端下载 API。

#### 后端

**新工具 `sandbox_download`**（`tools/builtin/sandbox_tools.py`）：

```python
@tool
async def sandbox_download(path: str) -> str:
    """
    将沙箱中的文件打包供用户下载。
    
    如果 path 是目录，自动 tar.gz 打包。
    如果 path 是单个文件，直接提供下载。
    
    返回下载链接，前端自动渲染为下载按钮。
    """
    # 1. 检查文件存在性
    # 2. 目录 → tar -czf /tmp/{conv_id}_{name}.tar.gz -C {session_dir} {path}
    # 3. 通过 SSH cat 读取文件内容（base64）
    # 4. 保存到 artifacts 表（language="archive", content=base64）
    # 5. 返回 artifact_id，前端通过 /api/artifacts/{id}/download 下载
```

**新 API 端点**（`main.py`）：

```python
@app.get("/api/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: int):
    """
    下载文件产物（返回二进制流，浏览器直接触发下载）。
    
    支持所有 artifact 类型：
    - code/html: 直接下载源码
    - pptx: 下载 .pptx 二进制
    - archive: 下载 .tar.gz 打包
    """
    # 1. 从 artifacts 表读取
    # 2. binary_b64 字段 → base64 decode → StreamingResponse
    # 3. 设置 Content-Disposition: attachment; filename="xxx"
```

#### 前端

**FileArtifactCard 增加下载按钮**：
- 所有 artifact 卡片右侧加下载图标
- 点击调用 `/api/artifacts/{id}/download`
- 浏览器 `<a download>` 触发本地保存

**新 SSE 事件类型**（可选，复用 `file_artifact`）：
- `sandbox_download` 工具完成后发 `file_artifact` 事件，`language="archive"`
- 前端 FileArtifactCard 检测到 `archive` 类型时显示"下载压缩包"样式

---

## 三、数据流

### 打包下载完整链路

```
用户："帮我把代码打包"
  → 模型调用 sandbox_download(path=".")
    → manager: SSH 到 sandbox worker (DB 确定 worker_id)
    → worker: tar -czf /tmp/pack.tar.gz -C /sandbox/sess_abc123 .
    → worker: cat /tmp/pack.tar.gz | base64
    → 后端: 保存到 artifacts 表 (language="archive", content=base64)
    → 后端: 发 file_artifact SSE 事件
  → 前端: 文件卡片出现，显示"下载压缩包"
  → 用户点击下载
    → GET /api/artifacts/{id}/download
    → 后端: base64 decode → StreamingResponse
    → 浏览器: 保存 .tar.gz 文件
```

### 沙箱会话恢复链路

```
用户 F5 刷新
  → full-state API 返回对话
  → 模型继续回答，调用 execute_code
    → manager._get_worker_for_session(conv_id)
      → 本地 _sessions 无记录
      → DB 查 conversations.sandbox_worker_id = "w2"
      → 用 w2，session_dir = /sandbox/sess_{conv_id}
      → 文件还在，继续执行
```

---

## 四、涉及文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `db/models.py` | 加列 | `sandbox_worker_id VARCHAR(50)` |
| `db/migrate.py` | 加 SQL | `ALTER TABLE conversations ADD COLUMN IF NOT EXISTS...` |
| `sandbox/manager.py` | 核心改动 | `_get_worker_for_session` 从 DB 读/写 worker 分配 |
| `tools/builtin/sandbox_tools.py` | 新增工具 | `sandbox_download` 打包+保存 artifact |
| `main.py` | 新增 API | `/api/artifacts/{id}/download` 二进制流下载 |
| `db/artifact_store.py` | 可能改动 | 支持 `language="archive"` 类型 |
| `fsm/sse_events.py` | 不改 | 复用现有 `FILE_ARTIFACT` 事件类型 |
| `frontend/src/components/FileArtifactCard.vue` | 样式 | archive 类型卡片 + 所有卡片加下载按钮 |
| `frontend/src/api/index.ts` | 新函数 | `downloadArtifact(id)` 触发浏览器下载 |

---

## 五、遵循 spec 规范检查

| 铁律 | 是否遵循 | 说明 |
|------|---------|------|
| DB 驱动 | ✅ | sandbox_worker_id 存 DB，不靠内存 |
| 不从文本推断 | ✅ | worker 分配从 DB 字段读，不解析工具输出 |
| 状态机 | ✅ | 无新状态需要，复用现有 |
| SSE 枚举 | ✅ | 复用 `FILE_ARTIFACT`，不新增 |
| 不截断 | ✅ | 不涉及消息列表 |
| 新功能 checklist | ✅ | DB 字段 + migrate + 新工具 + 新 API |

---

## 六、风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| 大文件 base64 撑爆 DB | 中 | 限制打包大小（如 50MB），超过提示用户 |
| SSH cat 大文件阻塞 | 中 | 用流式读取 + 超时保护 |
| Worker 宕机后文件丢失 | 低 | 已有迁移机制 + DB 记录 worker_id，日志 warning |
| artifacts 表膨胀 | 低 | archive 类型可设 TTL 定期清理 |
