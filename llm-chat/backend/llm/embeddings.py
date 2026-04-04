"""
Embedding 工具：直接用 httpx 调用 OpenAI-compatible /v1/embeddings 接口。

为何不用 langchain_openai.OpenAIEmbeddings：
  langchain-openai >= 0.3 默认以 encoding_format=base64 请求，Ollama 不支持该格式，
  返回 400 "invalid input type"。直接 httpx 调用可精确控制请求参数。

兼容矩阵（只要有 /v1/embeddings 接口均可用）：
  Ollama   → EMBEDDING_BASE_URL=http://localhost:11434/v1
  OpenAI   → EMBEDDING_BASE_URL=https://api.openai.com/v1
  GLM      → EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
  MiniMax  → EMBEDDING_BASE_URL=https://api.minimaxi.com/v1
"""
import httpx
from config import EMBEDDING_MODEL, EMBEDDING_BASE_URL, API_KEY

_client: httpx.AsyncClient | None = None

import logging as _logging
_embed_logger = _logging.getLogger("llm.embeddings")


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # 超时从 30s 缩短为 8s：
        # Ollama 如未启动会立即拒绝连接，8s 足够处理网络抖动，
        # 同时防止 Ollama/远程 embedding 服务不可用时把整个请求卡住。
        _client = httpx.AsyncClient(timeout=8.0)
    return _client


async def embed_text(text: str) -> list[float]:
    """对单条文本做向量化，返回 float 列表。
    
    若 embedding 服务不可达（Ollama 未启动、网络超时等），
    抛出异常由调用方捕获降级处理，不阻塞主流程。
    """
    url = EMBEDDING_BASE_URL.rstrip("/") + "/embeddings"
    try:
        resp = await _get_client().post(
            url,
            json={"model": EMBEDDING_MODEL, "input": text, "encoding_format": "float"},
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except httpx.ConnectError as e:
        _embed_logger.warning(
            "Embedding 服务连接失败（可能未启动）: %s url=%s", e, url
        )
        raise
    except httpx.TimeoutException as e:
        _embed_logger.warning(
            "Embedding 服务超时（8s）: %s url=%s", e, url
        )
        raise
