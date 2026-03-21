"""
集中管理所有配置，方便后续调整。
author: leizihao
email: lzh19162600626@gmail.com
"""

# ── LLM 服务（OpenAI 兼容格式） ──
API_BASE_URL = "http://localhost:11434/v1"
API_KEY = "ollama"  # Ollama 不验证 key，随便填

# ── 模型配置 ──
CHAT_MODEL = "qwen3-coder:30b"           # 对话主模型
SUMMARY_MODEL = "qwen2.5-coder:14b"       # 摘要压缩模型
EMBEDDING_MODEL = "bge-m3"            # Embedding 模型（长期记忆用）

# ── 上下文窗口 ──
CHAT_NUM_CTX = 4096                   # 对话模型上下文大小
SUMMARY_NUM_CTX = 2048                # 摘要模型上下文大小

# ── 记忆参数 ──
SHORT_TERM_MAX_TURNS = 10             # 短期记忆保留的最大轮数
COMPRESS_TRIGGER = 8                  # 触发压缩的轮数阈值
MAX_SUMMARY_LENGTH = 500              # 摘要最大字数

# ── 长期记忆（Qdrant 向量库） ──
# 设为 False 可在未部署 Qdrant 的环境下完全跳过长期记忆（RAG），不影响其他功能
LONGTERM_MEMORY_ENABLED = True
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_COLLECTION = "llm_chat_memories"
EMBEDDING_DIM = 1024              # bge-m3 输出维度
LONGTERM_TOP_K = 3                # 每次检索返回的最相关记忆数
LONGTERM_SCORE_THRESHOLD = 0.5   # 最低余弦相似度阈值
SUMMARY_RELEVANCE_THRESHOLD = 0.4  # query与摘要余弦相似度低于此值视为不相关
SHORT_TERM_FORGET_TURNS = 2       # 忘记模式下只保留最近N轮

# ── 服务端口 ──
BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000

# ── System Prompt ──
DEFAULT_SYSTEM_PROMPT = "你是一个有用的AI助手，请用中文回答用户的问题。回答要准确、清晰、有条理。"

SUMMARY_SYSTEM_PROMPT = (
    "你是一个专业的摘要助手。你的任务是把对话历史压缩成简洁的摘要。"
    "要求：保留关键信息、用户偏好、重要结论和待办事项。用中文输出。"
    "不要遗漏任何重要的事实或数字。"
)
