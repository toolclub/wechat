"""
量化独立进程 Worker

为了防止量化选股（Pandas CPU密集型、大量同步网络请求）阻塞主 FastAPI 事件循环，
我们将选股任务和预热任务放到独立的系统进程中执行。使用 subprocess 直接启动，避免 multiprocessing 和 uvicorn 的冲突。
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("quant.worker")

def _init_worker_env():
    """初始化子进程的环境（日志、数据库等）"""
    from config import LOG_DIR, DATABASE_URL
    from logging_config import setup_logging
    from db.database import init_engine
    
    setup_logging(LOG_DIR)
    init_engine(DATABASE_URL)


# ── 选股进程 ─────────────────────────────────────────────────────────────

def _run_screen_sync(snapshot_id: str, client_id: str, criteria: dict, user_id: str):
    """选股独立进程入口点"""
    _init_worker_env()
    
    async def _main():
        from quant.bootstrap import init_quant
        await init_quant()
        
        from graph.quant_agent import background_screen
        await background_screen(snapshot_id, client_id, criteria, user_id)
        
        # 稍微延迟退出，确保底层网络连接（如 aiohttp）能正常关闭
        await asyncio.sleep(0.5)
        
    asyncio.run(_main())

def start_screen_process(snapshot_id: str, client_id: str, criteria: dict, user_id: str) -> subprocess.Popen:
    """通过 subprocess 启动选股独立进程"""
    backend_dir = str(Path(__file__).resolve().parent.parent)
    criteria_json = json.dumps(criteria)
    
    code = f"""
import sys
sys.path.insert(0, {repr(backend_dir)})
import json
from quant.worker import _run_screen_sync

snapshot_id = {repr(snapshot_id)}
client_id = {repr(client_id)}
criteria = json.loads({repr(criteria_json)})
user_id = {repr(user_id)}

_run_screen_sync(snapshot_id, client_id, criteria, user_id)
"""
    p = subprocess.Popen(
        [sys.executable, "-c", code],
        env=os.environ.copy()
    )
    return p


# ── 预热常驻进程 ─────────────────────────────────────────────────────────

def _run_warmer_sync():
    """预热常驻进程入口点"""
    _init_worker_env()
    
    async def _main():
        from quant.bootstrap import init_quant
        await init_quant()
        
        from quant.cache_warmer import get_warmer
        warmer = get_warmer()
        await warmer.start(initial_delay=2.0)
        
        # 阻塞进程，保持 warmer 的 loop 持续运行
        try:
            while True:
                await asyncio.sleep(3600)
        except (asyncio.CancelledError, KeyboardInterrupt):
            await warmer.stop(timeout=5.0)
            
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass

def start_warmer_process() -> subprocess.Popen:
    """启动预热独立进程"""
    backend_dir = str(Path(__file__).resolve().parent.parent)
    code = f"""
import sys
sys.path.insert(0, {repr(backend_dir)})
from quant.worker import _run_warmer_sync

_run_warmer_sync()
"""
    p = subprocess.Popen(
        [sys.executable, "-c", code],
        env=os.environ.copy()
    )
    return p


# ── 手动刷新进程 ─────────────────────────────────────────────────────────

def _run_refresh_sync(kinds: list[str] | None):
    """手动刷新独立进程入口点"""
    _init_worker_env()
    
    async def _main():
        from quant.bootstrap import init_quant
        await init_quant()
        
        from quant.cache_warmer import get_warmer
        warmer = get_warmer()
        # 作为独立进程被触发，手动执行一次 refresh_once
        await warmer._refresh_once(kinds or ["spot", "index", "bars", "prune"], manual=True)
        
        await asyncio.sleep(0.5)
        
    asyncio.run(_main())

def start_refresh_process(kinds: list[str] | None) -> subprocess.Popen:
    """启动手动刷新独立进程"""
    backend_dir = str(Path(__file__).resolve().parent.parent)
    kinds_json = json.dumps(kinds) if kinds else "None"
    
    code = f"""
import sys
sys.path.insert(0, {repr(backend_dir)})
import json
from quant.worker import _run_refresh_sync

kinds = json.loads({repr(kinds_json)}) if {repr(kinds_json)} != "None" else None
_run_refresh_sync(kinds)
"""
    p = subprocess.Popen(
        [sys.executable, "-c", code],
        env=os.environ.copy()
    )
    return p
