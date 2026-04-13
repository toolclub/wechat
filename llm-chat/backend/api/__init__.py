"""
API 路由模块

把 main.py 按业务边界拆分成 5 个 APIRouter 模块：
  - conversations.py : 对话 CRUD + full-state + streaming-status
  - chat.py          : 流式聊天 + 停止 + 恢复（含 StopEventRegistry）
  - artifacts.py     : 文件产物（元数据 / 详情 / 下载）
  - tools.py         : 工具列表 + 对话工具历史
  - debug.py         : 记忆 / 沙箱 / embedding / plan / 模型列表

main.py 仅保留 FastAPI() + lifespan + app.include_router(...) × 5，不再
承担业务逻辑。每个子模块拥有独立的 APIRouter 实例和局部依赖。
"""
