"""
Embedding 工厂：OllamaEmbeddings 单例
"""
from langchain_ollama import OllamaEmbeddings
from config import EMBEDDING_MODEL, OLLAMA_BASE_URL

_instance: OllamaEmbeddings | None = None


def get_embeddings() -> OllamaEmbeddings:
    """返回 OllamaEmbeddings 单例。"""
    global _instance
    if _instance is None:
        _instance = OllamaEmbeddings(
            model=EMBEDDING_MODEL,
            base_url=OLLAMA_BASE_URL,
        )
    return _instance


async def embed_text(text: str) -> list[float]:
    """对单条文本做向量化，返回 float 列表。"""
    return await get_embeddings().aembed_query(text)
