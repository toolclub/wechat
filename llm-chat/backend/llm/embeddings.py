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
  Gitee AI → EMBEDDING_BASE_URL=https://ai.gitee.com/v1  （需配置 EMBEDDING_API_KEY）

兜底机制：主模型失败后依次尝试兜底列表，全部失败则抛 EmbeddingError。
"""
import logging as _logging

import httpx

from config import EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_FALLBACK_MODELS

_client: httpx.AsyncClient | None = None
_embed_logger = _logging.getLogger("llm.embeddings")

# 兜底模型列表（从 .env 读取，均支持 1024 维度）
_FALLBACK_MODELS: list[str] = list(EMBEDDING_FALLBACK_MODELS)


class EmbeddingError(Exception):
    """所有 embedding 模型均不可用时抛出，调用方捕获后前端显示错误提示。"""
    pass


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # 远程云端 API（Gitee/OpenAI 等）首次请求可能较慢，给 20s；
        # Ollama 本地连接失败会立即报 ConnectError，不会真的等满超时。
        _client = httpx.AsyncClient(timeout=20.0)
    return _client


async def _try_embed(url: str, model: str, text: str) -> list[float] | None:
    """尝试用指定模型 embedding，返回向量或 None（失败）。"""
    try:
        resp = await _get_client().post(
            url,
            json={
                "model": model,
                "input": text,
                "encoding_format": "float",
                "dimensions": 1024,
            },
            headers={
                "Authorization": f"Bearer {EMBEDDING_API_KEY}",
                "X-Failover-Enabled": "true",
            },
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
        status = getattr(e.response, "status_code", None) if isinstance(e, httpx.HTTPStatusError) else None
        _embed_logger.warning(
            "Embedding 模型 %s 失败 [%s]: %s",
            model,
            status or type(e).__name__,
            str(e)[:120],
        )
        return None
    except Exception as e:
        _embed_logger.warning("Embedding 模型 %s 异常: %s", model, e)
        return None


async def embed_text(text: str) -> list[float]:
    """对单条文本做向量化，返回 float 列表。

    主模型失败后依次尝试兜底列表，全部失败才抛 EmbeddingError。
    """
    url = EMBEDDING_BASE_URL.rstrip("/") + "/embeddings"
    all_models = [EMBEDDING_MODEL] + _FALLBACK_MODELS

    for model in all_models:
        vec = await _try_embed(url, model, text)
        if vec is not None:
            if model != EMBEDDING_MODEL:
                _embed_logger.info(
                    "主模型 %s 不可用，已切换到兜底模型 %s",
                    EMBEDDING_MODEL, model,
                )
            return vec

    raise EmbeddingError(
        f"向量化失败，已尝试模型：{', '.join(all_models)}。"
        f"请检查 embedding 服务是否可用。"
    )
