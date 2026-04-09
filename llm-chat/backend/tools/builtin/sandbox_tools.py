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
    # ── Python ──
    r"python[23]?\s+(-m\s+)?http\.server",
    r"python[23]?\s+(-m\s+)?flask\s+run",
    r"python[23]?\s+(-m\s+)?uvicorn",
    r"python[23]?\s+(-m\s+)?gunicorn",
    r"python[23]?\s+(-m\s+)?streamlit\s+run",
    r"python[23]?\s+(-m\s+)?gradio",
    r"python[23]?\s+(-m\s+)?tornado",
    r"python[23]?\s+(-m\s+)?django\s+runserver",
    r"python[23]?\s+.*\.run\(",                    # app.run() / server.run()
    r"uvicorn\s+",                                  # 直接调 uvicorn（无 python 前缀）
    r"gunicorn\s+",
    r"celery\s+worker",
    r"daphne\s+",
    # ── Node.js / Deno / Bun ──
    r"node\s+\S+\.\w+",                              # node app.js / node index.js（排除 node -v 等）
    r"npm\s+(start|run\s+\w+)",                     # npm start / npm run dev|serve|build|watch
    r"npx\s+(serve|next|nuxt|vite|ts-node|tsx)",
    r"yarn\s+(start|dev|serve)",
    r"pnpm\s+(start|dev|serve)",
    r"deno\s+run",
    r"bun\s+run",
    r"ts-node\s+",
    r"tsx\s+",
    r"next\s+(dev|start)",
    r"nuxt\s+(dev|start)",
    r"vite\s+(dev|preview)",
    # ── Java / JVM ──
    r"java\s+.*-jar",
    r"java\s+.*\.(Main|Application|Server|Boot)",
    r"mvn\s+spring-boot:run",
    r"gradle\s+bootRun",
    r"gradlew\s+bootRun",
    r"\./gradlew\s+bootRun",
    r"mvnw\s+spring-boot:run",
    r"\./mvnw\s+spring-boot:run",
    r"java\s+.*-cp\s+",                             # java -cp xxx MainClass
    r"kotlin\s+.*server",
    # ── Go ──
    r"go\s+run\s+",
    r"\./\w+.*server",                               # ./myserver
    # ── Rust ──
    r"cargo\s+run",
    # ── Ruby ──
    r"ruby\s+.*server",
    r"rails\s+server",
    r"rails\s+s\b",
    r"rackup",
    r"puma\s+",
    r"thin\s+start",
    # ── PHP ──
    r"php\s+-S",
    r"php\s+artisan\s+serve",
    r"php\s+.*-S\s+",
    # ── .NET ──
    r"dotnet\s+run",
    r"dotnet\s+watch",
    # ── 通用服务 / 中间件 ──
    r"nginx",
    r"httpd",
    r"apache2",
    r"redis-server",
    r"mongod",
    r"mysqld",
    r"postgres",
    r"docker\s+run\s+.*-p\s+",                      # docker run -p 映射端口
    r"docker-compose\s+up",
    r"docker\s+compose\s+up",
    # ── 已经后台化的（不重复处理） ──
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
    r"server\.port\s*[=:]\s*(\d{2,5})",            # Spring Boot application.properties
    r"PORT\s*[=:]\s*(\d{2,5})",                     # env PORT=3000
    r"-Dserver\.port=(\d{2,5})",                     # Java -D 参数
    r"--listen\s+\S*:(\d{2,5})",                     # 通用 --listen
    r"EXPOSE\s+(\d{2,5})",                           # Dockerfile
    r"runserver\s+(?:\S+:)?(\d{2,5})",              # django runserver 8000 / 0.0.0.0:8000
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

    ⚠️ 沙箱有 120 秒执行超时限制，必须遵守以下规则：

    【禁止前台启动任何服务或长时间进程】
    包括但不限于：uvicorn/flask/gunicorn/django、node/npm start/next dev、
    java -jar/mvn spring-boot:run/gradle bootRun、go run、cargo run、
    rails server、php artisan serve、dotnet run 等。

    正确模式（适用于所有语言）：
    1. 后台启动 + 日志重定向：
       nohup <启动命令> > /tmp/server.log 2>&1 &
       sleep 2
    2. 验证：
       ss -tlnp | grep <端口>
       curl -s http://localhost:<端口>/
    3. 查日志：tail -20 /tmp/server.log
    4. 验证完清理：pkill -f <进程关键词>

    同理，任何可能超过 10 秒的命令都应后台化：
       <command> > /tmp/output.log 2>&1 &
       然后 tail / head 读取日志。

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

    # shell 脚本中包含服务命令时，转给 run_shell 的服务模式处理（防止超时阻塞）
    if language.lower().strip() in ("shell", "bash", "sh") and _is_service_command(code):
        logger.info("execute_code → 检测到服务命令，转入后台模式 | conv=%s", conv_id)
        return await _run_service_command(conv_id, code, sandbox_manager, adispatch_custom_event)

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

    系统会自动检测服务类命令（uvicorn、flask、http.server 等），
    自动后台运行并验证服务状态。

    ⚠️ 沙箱有 120 秒超时限制。对于可能长时间运行的命令，请：
    - 后台化：command > /tmp/output.log 2>&1 &
    - 然后用 tail -n 20 /tmp/output.log 查看结果

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
    from sandbox.context import current_message_id
    msg_id = current_message_id.get() or ""
    logger.info("sandbox_write | conv=%s | path=%s | len=%d", conv_id, path, len(content))
    result = await sandbox_manager.write_file(conv_id, path, content)

    # 写入完成后，保存为文件产物并通知前端
    try:
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        await save_artifact(conv_id, name, path, content, message_id=msg_id, size=len(content))
        await adispatch_custom_event(
            "file_artifact",
            {"name": name, "path": path, "content": content, "language": detect_language(path), "message_id": msg_id},
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
