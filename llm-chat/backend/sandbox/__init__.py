"""
沙箱代码执行系统

通过 SSH 连接远程 Docker 容器（或物理机），为 AI Agent 提供安全的代码执行环境。
每个对话拥有独立的工作目录（session），支持 Python / Node.js / Java / Shell。

架构：
  SandboxManager (单例)
    └── SSHWorker (per worker)
          └── Session (per conversation, directory-level isolation)

配置：
  SANDBOX_ENABLED=true
  SANDBOX_WORKERS=[{"id":"w1","host":"192.168.1.100","port":22,"user":"sandbox","key_file":"~/.ssh/id_rsa"}]
  SANDBOX_TIMEOUT=120
  SANDBOX_CLEANUP_HOURS=12
"""
