"""
量化独立进程 Worker

为了防止量化选股（Pandas CPU密集型、大量同步网络请求）阻塞主 FastAPI 事件循环，
我们将选股任务和预热任务放到独立的常驻系统进程中执行。
每个 Worker 有自己独立的 Event Loop 和进程级任务队列，避免了每次请求的冷启动开销，
同时与普通聊天请求做到 100% 物理隔离。
"""
import asyncio
import logging
import multiprocessing as mp
from typing import Optional

logger = logging.getLogger("quant.worker")

def _init_worker_env():
    """初始化子进程的环境（日志、数据库等）"""
    from config import LOG_DIR, DATABASE_URL
    from logging_config import setup_logging
    from db.database import init_engine
    
    setup_logging(LOG_DIR)
    init_engine(DATABASE_URL)


class ScreenWorker:
    def __init__(self):
        # 强制使用 spawn，确保进程纯净，不继承 uvicorn/fastapi 状态
        self.ctx = mp.get_context('spawn')
        self.queue = self.ctx.Queue()
        self.process: Optional[mp.Process] = None

    def start(self):
        if self.process is None or not self.process.is_alive():
            self.process = self.ctx.Process(target=self._run, daemon=True, name="QuantScreenWorker")
            self.process.start()
            logger.info("QuantScreenWorker 进程已启动 (pid: %s)", self.process.pid)

    def stop(self):
        if self.process and self.process.is_alive():
            self.queue.put(None) # 发送结束信号
            self.process.join(timeout=3.0)
            if self.process.is_alive():
                self.process.terminate()

    def submit(self, snapshot_id: str, client_id: str, criteria: dict, user_id: str):
        self.queue.put(("screen", (snapshot_id, client_id, criteria, user_id)))

    def _run(self):
        _init_worker_env()
        asyncio.run(self._async_run())

    async def _async_run(self):
        from quant.bootstrap import init_quant
        await init_quant()
        
        from graph.quant_agent import background_screen
        
        logger.info("QuantScreenWorker 启动，等待选股任务...")
        while True:
            try:
                # 放入独立线程阻塞读取 queue，不阻塞当前 worker 的事件循环
                task = await asyncio.to_thread(self.queue.get)
                if task is None:
                    break
                
                cmd, args = task
                if cmd == "screen":
                    snapshot_id, client_id, criteria, user_id = args
                    # 抛出后台任务处理选股，允许并发处理多个选股请求
                    asyncio.create_task(background_screen(snapshot_id, client_id, criteria, user_id))
            except Exception as exc:
                logger.error("ScreenWorker 执行异常: %s", exc, exc_info=True)


class WarmerWorker:
    def __init__(self):
        self.ctx = mp.get_context('spawn')
        self.queue = self.ctx.Queue()
        self.process: Optional[mp.Process] = None

    def start(self):
        if self.process is None or not self.process.is_alive():
            self.process = self.ctx.Process(target=self._run, daemon=True, name="QuantWarmerWorker")
            self.process.start()
            logger.info("QuantWarmerWorker 进程已启动 (pid: %s)", self.process.pid)

    def stop(self):
        if self.process and self.process.is_alive():
            self.queue.put(None)
            self.process.join(timeout=3.0)
            if self.process.is_alive():
                self.process.terminate()

    def submit_refresh(self, kinds: list[str] | None):
        self.queue.put(("refresh", (kinds,)))

    def _run(self):
        _init_worker_env()
        asyncio.run(self._async_run())

    async def _async_run(self):
        from quant.bootstrap import init_quant
        await init_quant()
        
        from quant.cache_warmer import get_warmer
        warmer = get_warmer()
        
        # 启动定时预热循环（它会在后台 create_task 跑，不阻塞）
        await warmer.start(initial_delay=2.0)
        
        logger.info("QuantWarmerWorker 启动，等待手动刷新任务...")
        while True:
            try:
                task = await asyncio.to_thread(self.queue.get)
                if task is None:
                    break
                
                cmd, args = task
                if cmd == "refresh":
                    kinds = args[0]
                    # 手动刷新阻塞执行即可，反正 warmer 是单实例
                    await warmer._refresh_once(kinds, manual=True)
            except Exception as exc:
                logger.error("WarmerWorker 执行异常: %s", exc, exc_info=True)


_screen_worker = ScreenWorker()
_warmer_worker = WarmerWorker()

def start_quant_workers():
    _screen_worker.start()
    _warmer_worker.start()

def stop_quant_workers():
    _screen_worker.stop()
    _warmer_worker.stop()

def submit_screen_task(snapshot_id: str, client_id: str, criteria: dict, user_id: str):
    _screen_worker.submit(snapshot_id, client_id, criteria, user_id)

def submit_refresh_task(kinds: list[str] | None):
    _warmer_worker.submit_refresh(kinds)
