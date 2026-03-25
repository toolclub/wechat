"""
集中管理所有配置，方便后续调整。
author: leizihao
"""

# ── LLM 服务（Ollama） ──
OLLAMA_BASE_URL = "http://localhost:11434"
API_KEY = "ollama"

# ── 向后兼容（原 API_BASE_URL） ──
API_BASE_URL = f"{OLLAMA_BASE_URL}/v1"

# ── 模型配置 ──
CHAT_MODEL = "qwen3-coder:30b"
SUMMARY_MODEL = "qwen2.5-coder:14b"
EMBEDDING_MODEL = "bge-m3"

# ── 上下文窗口 ──
CHAT_NUM_CTX = 4096
SUMMARY_NUM_CTX = 2048

# ── 记忆参数 ──
SHORT_TERM_MAX_TURNS = 10
COMPRESS_TRIGGER = 8
MAX_SUMMARY_LENGTH = 500
SHORT_TERM_FORGET_TURNS = 2

# ── 长期记忆（Qdrant 向量库） ──
# 设为 False 可在未部署 Qdrant 的环境下完全跳过长期记忆，不影响其他功能
LONGTERM_MEMORY_ENABLED = True
QDRANT_URL = "http://localhost:6333"
QDRANT_HOST = "localhost"         # 向后兼容
QDRANT_PORT = 6333                # 向后兼容
QDRANT_COLLECTION = "llm_chat_memories"
EMBEDDING_DIM = 1024
LONGTERM_TOP_K = 3
LONGTERM_SCORE_THRESHOLD = 0.5
SUMMARY_RELEVANCE_THRESHOLD = 0.4

# ── MCP 服务器配置 ──
# 格式 stdio: {"server_name": {"command": "npx", "args": [...], "transport": "stdio"}}
# 格式 SSE:   {"server_name": {"url": "http://...", "transport": "sse"}}
# 留空则不加载任何 MCP 工具
MCP_SERVERS: dict = {
    # 示例（取消注释以启用文件系统 MCP 服务器）：
    # "filesystem": {
    #     "command": "npx",
    #     "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"],
    #     "transport": "stdio",
    # },
    # 示例（SSE 传输）：
    # "my_sse_server": {
    #     "url": "http://localhost:8080/sse",
    #     "transport": "sse",
    # },
}

# ── 服务端口 ──
BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000

# ── 持久化目录 ──
CONVERSATIONS_DIR = "./conversations"

# ── 默认系统提示词 ──
DEFAULT_SYSTEM_PROMPT = (
    "你是一个有用的AI助手，请用中文回答用户的问题。回答要准确、清晰、有条理。"
)

SUMMARY_SYSTEM_PROMPT = (
    "你是一个专业的摘要助手。你的任务是把对话历史压缩成简洁的摘要。"
    "要求：保留关键信息、用户偏好、重要结论和待办事项。用中文输出。"
    "不要遗漏任何重要的事实或数字。"
)
