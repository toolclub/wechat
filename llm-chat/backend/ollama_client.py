import httpx
import json
from typing import AsyncGenerator
from config import OLLAMA_BASE_URL, CHAT_NUM_CTX, SUMMARY_NUM_CTX


async def chat_stream(
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    num_ctx: int = CHAT_NUM_CTX,
) -> AsyncGenerator[str, None]:
    """
    流式调用 Ollama /api/chat，用于对话主模型。
    逐 chunk 返回生成的文本。
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream(
            "POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload,
        ) as response:
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if "message" in data and "content" in data["message"]:
                    yield data["message"]["content"]
                if data.get("done", False):
                    break


async def chat_sync(
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    num_ctx: int = SUMMARY_NUM_CTX,
) -> str:
    """
    非流式调用，用于摘要压缩模型等内部任务。
    直接返回完整文本。
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat", json=payload,
        )
        data = resp.json()
        return data["message"]["content"]


async def get_embedding(text: str, model: str) -> list[float]:
    """
    获取文本的 Embedding 向量（预留，后续 RAG 用）。
    调用 Ollama /api/embeddings 接口。
    """
    payload = {
        "model": model,
        "prompt": text,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/embeddings", json=payload,
        )
        data = resp.json()
        return data.get("embedding", [])


async def list_models() -> list[str]:
    """获取 Ollama 中已下载的模型列表。"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
