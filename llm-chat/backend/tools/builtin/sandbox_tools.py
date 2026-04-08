"""
沙箱代码执行工具（流式输出 + 智能后台进程版）

核心改进：
  1. 代码执行过程中，stdout/stderr 实时通过 adispatch_custom_event 推送给前端
  2. 长驻服务（http.server、flask、node server 等）自动后台启动，不阻塞
  3. 服务启动后自动验证（检查进程、端口、日志）

命令分类策略：
  - 服务类命令：自动 nohup 后台化 + 端口验证 + 日志查看
  - 普通命令：正常流式执行 + 输出重定向 + 退出码检查
"""
import json
import logging
import re

from langchain_core.tools import tool

logger = logging.getLogger("tools.sandbox")

# ── 服务类命令检测模式 ──────────────────────────────────────────────────────
_SERVICE_PATTERNS = [
    # Python HTTP servers
    r"python[23]?\s+(-m\s+)?http\.server",
    r"python[23]?\s+(-m\s+)?flask\s+run",
    r"python[23]?\s+(-m\s+)?uvicorn",
    r"python[23]?\s+(-m\s+)?gunicorn",
    r"python[23]?\s+(-m\s+)?streamlit\s+run",
    r"python[23]?\s+(-m\s+)?gradio",
    r"python[23]?\s+.*app\.run\(",
    # Node.js servers
    r"node\s+.*server",
    r"npm\s+(start|run\s+(dev|start|serve))",
    r"npx\s+serve",
    r"yarn\s+(start|dev|serve)",
    # General server commands
    r"nginx",
    r"httpd",
    r"php\s+-S",
    r"ruby\s+.*server",
    r"java\s+.*-jar",
    # Already backgrounded
    r"nohup\s+",
]
_SERVICE_RE = re.compile("|".join(f"({p})" for p in _SERVICE_PATTERNS), re.IGNORECASE)

# ── 端口提取模式 ────────────────────────────────────────────────────────────
_PORT_PATTERNS = [
    r"(?:--port|:|-p|--bind\s+\S+:)\s*(\d{2,5})",
    r"http\.server\s+(\d{2,5})",
    r"localhost:(\d{2,5})",
    r"0\.0\.0\.0:(\d{2,5})",
    r"127\.0\.0\.1:(\d{2,5})",
    r"port\s*[=:]\s*(\d{2,5})",
]
_PORT_RE = re.compile("|".join(_PORT_PATTERNS), re.IGNORECASE)


def _is_service_command(cmd: str) -> bool:
    """检测命令是否为长驻服务类命令。"""
    return bool(_SERVICE_RE.search(cmd))


def _extract_port(cmd: str) -> int | None:
    """从命令中提取端口号。"""
    m = _PORT_RE.search(cmd)
    if m:
        for g in m.groups():
            if g and g.isdigit():
                port = int(g)
                if 1 <= port <= 65535:
                    return port
    return None


def _get_conv_id() -> str:
    from sandbox.context import current_conv_id
    return current_conv_id.get() or "default"


@tool
async def execute_code(language: str, code: str) -> str:
    """
    在安全沙箱环境中执行代码。支持 Python、JavaScript、Java、Shell。
    每个对话有独立的工作目录，可以读写文件、安装包。
    执行过程中输出会实时显示在终端中。

    Args:
        language: 编程语言，可选值: python, javascript, java, shell
        code: 要执行的代码内容

    Returns:
        执行结果，包含完整终端回显
    """
    from langchain_core.callbacks.manager import adispatch_custom_event
    from sandbox.manager import sandbox_manager

    conv_id = _get_conv_id()
    logger.info("execute_code | conv=%s | lang=%s | code_len=%d", conv_id, language, len(code))

    result = await sandbox_manager.execute_code_streaming(
        conv_id, language, code,
        on_output=lambda stream, text: adispatch_custom_event(
            "sandbox_output",
            {"stream": stream, "text": text, "tool_name": "execute_code"},
        ),
    )
    return result.to_display()


@tool
async def run_shell(command: str) -> str:
    """
    在沙箱环境中执行 shell 命令。工作目录为当前对话的专属 session 目录。
    执行过程中输出会实时显示在终端中。

    对于启动服务的命令（如 python -m http.server），会自动后台运行并验证服务状态。

    Args:
        command: 要执行的 shell 命令

    Returns:
        命令输出结果
    """
    from langchain_core.callbacks.manager import adispatch_custom_event
    from sandbox.manager import sandbox_manager

    conv_id = _get_conv_id()
    logger.info("run_shell | conv=%s | cmd='%.100s'", conv_id, command)

    # ── 检测是否为服务类命令 ──
    if _is_service_command(command):
        return await _run_service_command(conv_id, command, sandbox_manager, adispatch_custom_event)

    # ── 普通命令：正常流式执行 ──
    result = await sandbox_manager.run_shell_streaming(
        conv_id, command,
        on_output=lambda stream, text: adispatch_custom_event(
            "sandbox_output",
            {"stream": stream, "text": text, "tool_name": "run_shell"},
        ),
    )
    return result.to_display()


async def _run_service_command(conv_id, command, manager, dispatch_event):
    """
    服务类命令：后台启动 + 自动验证。

    流程：
      1. 使用 nohup 后台启动，日志输出到 /tmp/service_<port>.log
      2. 等待 2 秒让服务初始化
      3. 验证：检查进程是否存活
      4. 验证：检查端口是否监听
      5. 可选：curl 功能验证
      6. 查看启动日志
    """
    import asyncio

    port = _extract_port(command)
    log_file = f"/tmp/service_{port or 'default'}.log"

    # 如果命令已经包含 nohup 或 &，直接执行
    if "nohup " in command or command.strip().endswith("&"):
        bg_cmd = command
    else:
        bg_cmd = f"nohup {command} > {log_file} 2>&1 &"

    # ── Step 1: 后台启动 ──
    await dispatch_event("sandbox_output", {
        "stream": "stdout",
        "text": f"🚀 正在后台启动服务...\n$ {bg_cmd}\n",
        "tool_name": "run_shell",
    })

    result = await manager.run_shell(conv_id, bg_cmd, timeout=5)

    # 等待服务初始化
    await asyncio.sleep(2)

    output_parts = [f"$ {bg_cmd}"]
    if result.stdout.strip():
        output_parts.append(result.stdout.strip())

    # ── Step 2: 检查进程 ──
    await dispatch_event("sandbox_output", {
        "stream": "stdout",
        "text": "🔍 正在检查进程...\n",
        "tool_name": "run_shell",
    })

    # 从命令中提取关键词用于 grep
    cmd_keyword = command.split()[0] if command.split() else "python"
    if "http.server" in command:
        cmd_keyword = "http.server"
    elif "flask" in command:
        cmd_keyword = "flask"
    elif "uvicorn" in command:
        cmd_keyword = "uvicorn"

    ps_result = await manager.run_shell(
        conv_id, f'ps aux | grep "{cmd_keyword}" | grep -v grep', timeout=5,
    )

    process_alive = ps_result.exit_code == 0 and ps_result.stdout.strip()
    if process_alive:
        output_parts.append(f"\n✅ 进程已启动:\n{ps_result.stdout.strip()}")
        await dispatch_event("sandbox_output", {
            "stream": "stdout",
            "text": f"✅ 进程已启动\n{ps_result.stdout.strip()}\n",
            "tool_name": "run_shell",
        })
    else:
        output_parts.append("\n❌ 进程未找到，服务可能启动失败")
        await dispatch_event("sandbox_output", {
            "stream": "stderr",
            "text": "❌ 进程未找到，服务可能启动失败\n",
            "tool_name": "run_shell",
        })

    # ── Step 3: 检查端口（如果能提取到端口号） ──
    if port:
        await dispatch_event("sandbox_output", {
            "stream": "stdout",
            "text": f"🔍 正在验证端口 {port}...\n",
            "tool_name": "run_shell",
        })

        port_result = await manager.run_shell(
            conv_id, f"ss -tlnp 2>/dev/null | grep :{port} || netstat -tlnp 2>/dev/null | grep :{port}", timeout=5,
        )

        port_listening = port_result.exit_code == 0 and port_result.stdout.strip()
        if port_listening:
            output_parts.append(f"\n✅ 端口 {port} 已监听:\n{port_result.stdout.strip()}")
            await dispatch_event("sandbox_output", {
                "stream": "stdout",
                "text": f"✅ 端口 {port} 已监听\n",
                "tool_name": "run_shell",
            })

            # ── Step 4: 可选功能验证 ──
            curl_result = await manager.run_shell(
                conv_id, f"curl -s --max-time 3 http://localhost:{port}/ 2>/dev/null | head -5", timeout=8,
            )
            if curl_result.exit_code == 0 and curl_result.stdout.strip():
                preview = curl_result.stdout.strip()[:200]
                output_parts.append(f"\n✅ HTTP 响应正常:\n{preview}")
                await dispatch_event("sandbox_output", {
                    "stream": "stdout",
                    "text": f"✅ HTTP 响应正常 (前 200 字符)\n{preview}\n",
                    "tool_name": "run_shell",
                })
        else:
            output_parts.append(f"\n⚠️ 端口 {port} 未监听（服务可能仍在初始化）")
            await dispatch_event("sandbox_output", {
                "stream": "stderr",
                "text": f"⚠️ 端口 {port} 未监听\n",
                "tool_name": "run_shell",
            })

    # ── Step 5: 查看启动日志 ──
    log_result = await manager.run_shell(
        conv_id, f"tail -20 {log_file} 2>/dev/null", timeout=5,
    )
    if log_result.stdout.strip():
        output_parts.append(f"\n📋 启动日志 ({log_file}):\n{log_result.stdout.strip()}")
        await dispatch_event("sandbox_output", {
            "stream": "stdout",
            "text": f"\n📋 启动日志:\n{log_result.stdout.strip()}\n",
            "tool_name": "run_shell",
        })

    # ── 构建最终结果 ──
    final_status = "✅ 服务启动成功" if process_alive else "❌ 服务启动失败"
    if port:
        final_status += f" | 端口: {port}"
    output_parts.insert(0, final_status)

    return "\n".join(output_parts)


@tool
async def sandbox_write(path: str, content: str) -> str:
    """
    在沙箱工作目录中创建或写入文件。路径相对于当前 session 目录。

    Args:
        path: 文件路径（相对于 session 目录）
        content: 文件内容

    Returns:
        写入结果
    """
    from langchain_core.callbacks.manager import adispatch_custom_event
    from sandbox.manager import sandbox_manager
    from db.artifact_store import save_artifact, detect_language

    conv_id = _get_conv_id()
    logger.info("sandbox_write | conv=%s | path=%s | len=%d", conv_id, path, len(content))
    result = await sandbox_manager.write_file(conv_id, path, content)

    # 写入完成后，保存为文件产物并通知前端
    try:
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        await save_artifact(conv_id, name, path, content)
        await adispatch_custom_event(
            "file_artifact",
            {"name": name, "path": path, "content": content, "language": detect_language(path)},
        )
    except Exception:
        logger.warning("file_artifact 事件发送失败 | conv=%s path=%s", conv_id, path, exc_info=True)

    return result.to_display()


@tool
async def sandbox_read(path: str) -> str:
    """
    读取沙箱工作目录中的文件内容。路径相对于当前 session 目录。

    Args:
        path: 文件路径（相对于 session 目录）

    Returns:
        文件内容
    """
    from sandbox.manager import sandbox_manager
    conv_id = _get_conv_id()
    logger.info("sandbox_read | conv=%s | path=%s", conv_id, path)
    result = await sandbox_manager.read_file(conv_id, path)
    return result.to_display()
