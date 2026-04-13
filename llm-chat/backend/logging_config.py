"""
日志配置模块：支持全局日志 + 按 client_id/conv_id 分文件记录

文件结构：
  {LOG_DIR}/chatflow.log              ← 全局日志（所有请求）
  {LOG_DIR}/prompts.log               ← LLM 调用前完整提示词（独立文件，按需查看）
  {LOG_DIR}/{client_id}/{conv_id}.log ← 每次对话的完整链路日志

内存与文件描述符管理：
  对话级 logger 用 OrderedDict + LRU 容量上限 _CONV_LOGGER_CAP 管理。
  长跑实例下不同 conv_id 累积可能耗尽 ulimit -n（每个 logger 持有一个
  RotatingFileHandler，对应一个打开的文件描述符）。淘汰时显式 close handler
  释放 fd，避免 fd 泄漏。
"""
import logging
import os
from collections import OrderedDict
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# 避免循环导入：LOG_DIR 在 setup_logging() 调用时从 config 获取
_log_dir: Path | None = None

# LRU 容量上限：超出后淘汰最久未使用的 logger 并释放其 file handler
_CONV_LOGGER_CAP: int = 512
# OrderedDict 的 move_to_end 让"刚 get 过的"被视为最近使用
_conv_loggers: "OrderedDict[str, logging.Logger]" = OrderedDict()

# 专用提示词日志记录器（写 prompts.log，不传播到根日志）
_prompt_logger: logging.Logger | None = None


def setup_logging(log_dir: str) -> None:
    """
    初始化全局日志：控制台 + 主日志文件 + 提示词日志文件。
    应在应用启动时（lifespan）调用一次。
    """
    global _log_dir, _prompt_logger
    _log_dir = Path(log_dir)
    _log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # 避免重复添加 handler（reload 场景）
    if root.handlers:
        return

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # 控制台
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # 全局文件（20 MB × 5 个备份）
    fh = RotatingFileHandler(
        _log_dir / "chatflow.log",
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # ── 提示词专用日志（独立文件，不传播到 chatflow.log）─────────────────────
    _prompt_logger = logging.getLogger("graph.prompts")
    _prompt_logger.propagate = False          # 不写入 chatflow.log
    _prompt_logger.setLevel(logging.DEBUG)
    pf = RotatingFileHandler(
        _log_dir / "prompts.log",
        maxBytes=50 * 1024 * 1024,            # 50 MB（提示词可能很长）
        backupCount=3,
        encoding="utf-8",
    )
    pf.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _prompt_logger.addHandler(pf)


def log_prompt(
    conv_id: str,
    node: str,
    model: str,
    messages: list[Any],
) -> None:
    """
    将发送给 LLM 的完整提示词写入 prompts.log。

    格式：
      ══════════════════════════════
      [PROMPT] conv=abc  node=call_model
      模型: MiniMax-M2.5  消息数: 4
      ── [0] system ──────────────
      提示词:
      你是一个准确、诚实的AI助手...
      ── [1] human ───────────────
      提示词:
      [图片内容]\n这张图片是...
      ══════════════════════════════
    """
    if _prompt_logger is None:
        return

    lines: list[str] = [
        "══════════════════════════════════════════════════════════════",
        f"[PROMPT] conv={conv_id}  node={node}",
        f"模型: {model}  消息数: {len(messages)}",
    ]

    for i, msg in enumerate(messages):
        # 兼容 dict（OpenAI 格式）和 LangChain BaseMessage
        if isinstance(msg, dict):
            role    = msg.get("role", "?")
            content = msg.get("content", "")
        else:
            role    = getattr(msg, "type", type(msg).__name__)
            content = getattr(msg, "content", str(msg))

        # content 可能是 list（多模态），只保留文字部分
        if isinstance(content, list):
            text_parts: list[str] = []
            image_count = 0
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        image_count += 1
            display = "".join(text_parts)
            if image_count:
                display = f"[图片×{image_count}]\n{display}"
        else:
            display = str(content)

        lines.append(f"── [{i}] {role} ({'─'*40})")
        lines.append("提示词:")
        lines.append(display)

    lines.append("══════════════════════════════════════════════════════════════")
    _prompt_logger.debug("\n".join(lines))


def _evict_oldest_conv_logger() -> None:
    """淘汰 OrderedDict 中最久未使用的 logger，并释放其文件描述符。

    必须 close 掉 RotatingFileHandler，否则 logger 对象虽然被 GC 回收，
    但底层文件句柄仍由 logging 框架的弱引用持有，长跑下会耗尽 ulimit -n。
    """
    if not _conv_loggers:
        return
    _, victim = _conv_loggers.popitem(last=False)  # popitem(last=False) = FIFO 头
    for handler in list(victim.handlers):
        try:
            handler.close()
        except Exception as exc:
            # spec 铁律 #9：handler.close 失败不致命但要落日志
            logging.getLogger("logging_config").warning(
                "淘汰 conv logger 时 close handler 失败: %s", exc,
            )
        victim.removeHandler(handler)


def get_conv_logger(client_id: str, conv_id: str) -> logging.Logger:
    """
    获取对话级日志记录器（LRU 缓存，cap=_CONV_LOGGER_CAP）。

    日志写入 {LOG_DIR}/{client_id}/{conv_id}.log，同时传播到根日志。
    访问已存在的 logger 会把它 move_to_end，刷新 LRU 顺序；新 logger 加入
    前若已达上限会淘汰最久未使用的并 close 其 file handler。
    """
    if _log_dir is None:
        return logging.getLogger(f"conv.{conv_id}")

    key = f"{client_id}:{conv_id}"

    # ── LRU 命中：刷新顺序后直接返回 ────────────────────────────────────────
    if key in _conv_loggers:
        _conv_loggers.move_to_end(key)
        return _conv_loggers[key]

    # ── LRU 未命中：先淘汰再插入 ────────────────────────────────────────────
    while len(_conv_loggers) >= _CONV_LOGGER_CAP:
        _evict_oldest_conv_logger()

    cid = (client_id or "anonymous")[:8]
    client_dir = _log_dir / cid
    client_dir.mkdir(parents=True, exist_ok=True)

    name = f"conv.{cid}.{conv_id}"
    logger = logging.getLogger(name)

    if not logger.handlers:
        fh = RotatingFileHandler(
            client_dir / f"{conv_id}.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)
        logger.propagate = True  # 同时写全局日志

    _conv_loggers[key] = logger
    return logger