"""
LLM 工厂：ChatOllama 实例管理
使用模块级缓存，避免每次请求都新建实例。
"""
from langchain_ollama import ChatOllama
from config import CHAT_MODEL, SUMMARY_MODEL, OLLAMA_BASE_URL

_cache: dict[str, ChatOllama] = {}


def get_chat_llm(model: str = CHAT_MODEL, temperature: float = 0.7) -> ChatOllama:
    """返回对话模型实例（按 model+temperature 缓存）。"""
    key = f"{model}:{temperature}"
    if key not in _cache:
        _cache[key] = ChatOllama(
            model=model,
            base_url=OLLAMA_BASE_URL,
            temperature=temperature,
        )
    return _cache[key]


def get_summary_llm() -> ChatOllama:
    """返回摘要专用模型实例（低温度，结果更稳定）。"""
    key = f"{SUMMARY_MODEL}:0.2"
    if key not in _cache:
        _cache[key] = ChatOllama(
            model=SUMMARY_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.2,
        )
    return _cache[key]
