"""
ChatFlow Backend —— LangChain + LangGraph 重构版
author: leizihao
email: lzh19162600626@gmail.com

═══════════════════════════════════════════════════════════════════════════════
本文件职责
═══════════════════════════════════════════════════════════════════════════════

重构后 main.py 只承担三件事：

  1. 应用生命周期（lifespan）：初始化日志 / DB / 缓存 / RAG / MCP / 沙箱 /
     LangGraph 图。顺序和故障降级策略见 lifespan() 函数。
  2. 创建 FastAPI app 实例并挂上跨域策略（layers.extension.apply_cors）。
  3. 按业务边界把 5 个 APIRouter 包含进来：
        api.conversations   —— 对话 CRUD + 完整状态 + 流式状态
        api.chat            —— 流式对话 + 停止 + 恢复
        api.artifacts       —— 文件产物元数据 / 详情 / 下载
        api.tools           —— 工具清单 + 对话工具历史
        api.debug           —— 记忆 / 沙箱 / embedding / plan / 模型列表

路由处理函数不再放在这里。想改某个接口去对应的 api/*.py 文件编辑。
"""
import logging

import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import artifacts as artifacts_router
from api import chat as chat_router
from api import conversations as conversations_router
from api import debug as debug_router
from api import tools as tools_router
from cache.factory import init_cache
from config import (
    BACKEND_HOST,
    BACKEND_PORT,
    CHAT_MODEL,
    DATABASE_URL,
    LOG_DIR,
    LONGTERM_MEMORY_ENABLED,
    MCP_SERVERS,
    SEMANTIC_CACHE_ENABLED,
)
from db.database import get_engine, init_engine
from db.models import Base
from graph import agent as graph_agent
from layers.extension import apply_cors
from logging_config import setup_logging
from memory import store as memory_store
from rag import retriever as rag_retriever
from tools import get_all_tools
from tools.mcp.loader import load_mcp_tools

logger = logging.getLogger("main")


# ═══════════════════════════════════════════════════════════════════════════════
# 应用生命周期
# ═══════════════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用启动 / 关闭钩子。

    启动顺序（每步失败的降级策略不同，见函数内注释）：
      0. setup_logging           ← 必须最先，否则后续异常无法落盘
      1. init_engine + 建表 + 迁移 ← DB 不通直接启动失败（无法降级）
      2. memory_store.init        ← 对话存储（DB-first，无内存预热）
      3. init_cache + 清缓存       ← 失败降级为 NullCache
      4. init_collection (Qdrant) ← 失败降级为长期记忆不可用
      5. load_mcp_tools           ← 失败降级为该 MCP Server 不可用
      5.5 sandbox.init            ← 失败降级为沙箱工具不注册
      6. graph_agent.init         ← 编译 Agent 图，必须最后（依赖所有工具）
    """
    # ── 启动 ──

    # 0. 初始化日志系统
    setup_logging(LOG_DIR)

    # 1. 初始化数据库连接并自动建表 + 增量迁移
    init_engine(DATABASE_URL)
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from db.migrate import run_migrations
        await run_migrations(conn)
    logger.info("数据库初始化完成")

    # 2. 初始化对话存储（DB-first，无内存预加载）
    await memory_store.init()

    # 3. 初始化语义缓存（Redis Search）
    try:
        await init_cache()
        # 启动时清理语义缓存（清除可能含工具调用响应的旧脏数据）
        # 缓存是加速层，清空后会自然重建，不影响功能
        try:
            from cache.factory import get_cache
            await get_cache().clear()
            logger.info("语义缓存已清理（启动时一次性清除旧数据）")
        except Exception as exc:
            # spec 铁律 #9：不吞异常。启动时清缓存失败不致命，但要落日志。
            logger.warning("启动时清理语义缓存失败（不影响启动）: %s", exc)
    except Exception as exc:
        logger.error("语义缓存初始化失败（已降级为 NullCache）: %s", exc)

    # 4. 初始化 Qdrant
    if LONGTERM_MEMORY_ENABLED:
        try:
            await rag_retriever.init_collection()
        except Exception as exc:
            logger.error("Qdrant 初始化失败（长期记忆不可用）: %s", exc)
    else:
        logger.info("长期记忆（RAG）已禁用，跳过 Qdrant 初始化")

    # 5. 加载 MCP 工具
    if MCP_SERVERS:
        await load_mcp_tools(MCP_SERVERS)
    else:
        logger.info("未配置 MCP 服务器，跳过 MCP 工具加载")

    # 5.5 初始化沙箱代码执行
    # 策略：SSH 连接成功后才注册沙箱工具，连接失败则不注册。
    # 这样模型根本看不到沙箱工具，不会尝试调用后失败。
    # 无需先启动沙箱再启后端——后端正常启动，沙箱连不上只是少几个工具。
    sandbox_ok = False
    from config import SANDBOX_ENABLED, SANDBOX_WORKERS, SANDBOX_TIMEOUT, SANDBOX_CLEANUP_HOURS
    if SANDBOX_ENABLED and SANDBOX_WORKERS:
        from sandbox.manager import sandbox_manager
        try:
            await sandbox_manager.init(SANDBOX_WORKERS, SANDBOX_TIMEOUT, SANDBOX_CLEANUP_HOURS)
            if sandbox_manager.available:
                # SSH 连接成功，动态注册沙箱工具
                from tools import register_tool
                from tools.builtin.sandbox_tools import execute_code, run_shell, sandbox_write, sandbox_read, sandbox_download
                from tools.builtin.ppt_tool import create_ppt
                for t in [execute_code, run_shell, sandbox_write, sandbox_read, sandbox_download, create_ppt]:
                    register_tool(t)
                sandbox_ok = True
                logger.info("沙箱工具已注册（6 个，含 PPT + 下载）")
            else:
                logger.warning("沙箱 Worker 全部连接失败，沙箱工具未注册（模型不可见）")
        except Exception as exc:
            logger.error("沙箱初始化异常，沙箱工具未注册: %s", exc)
    else:
        logger.info("沙箱代码执行已禁用（SANDBOX_ENABLED=false 或无 Worker 配置）")

    # 6. 构建 LangGraph Agent 图
    all_tools = get_all_tools()
    graph_agent.init(tools=all_tools, model=CHAT_MODEL)

    logger.info(
        "ChatFlow 启动完成 | 模型: %s | 工具数: %d | 长期记忆: %s | 语义缓存: %s | 沙箱: %s",
        CHAT_MODEL,
        len(all_tools),
        "开启" if LONGTERM_MEMORY_ENABLED else "关闭",
        "开启" if SEMANTIC_CACHE_ENABLED else "关闭",
        "开启" if sandbox_ok else "关闭",
    )

    yield

    # ── 关闭 ──
    if sandbox_ok:
        from sandbox.manager import sandbox_manager
        await sandbox_manager.shutdown()


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI app + 路由挂载
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="ChatFlow", version="2.0.0", lifespan=lifespan)
apply_cors(app)

# 5 个业务 Router 按业务边界分别挂载（内部路由路径保持和旧版完全一致，
# 前端接口契约不变）
app.include_router(conversations_router.router)
app.include_router(chat_router.router)
app.include_router(artifacts_router.router)
app.include_router(tools_router.router)
app.include_router(debug_router.router)


# ═══════════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    setup_logging(LOG_DIR)
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
