"""
内置工具：网络搜索（DuckDuckGo，无需 API Key）
依赖：pip install duckduckgo-search
"""
from langchain_core.tools import tool


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    使用 DuckDuckGo 搜索互联网获取最新信息。
    适用于：查询时事新闻、最新数据、不在训练集中的信息。

    Args:
        query:       搜索关键词或问题
        max_results: 返回结果数量（默认5，最多10）

    Returns:
        格式化的搜索结果摘要
    """
    try:
        from duckduckgo_search import DDGS
        max_results = min(max_results, 10)
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            return f"未找到关于「{query}」的搜索结果，请尝试换一种说法。"

        lines = [f"搜索关键词：{query}\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "(无标题)")
            body = r.get("body", "")
            href = r.get("href", "")
            lines.append(f"{i}. {title}")
            if body:
                lines.append(f"   {body[:200]}")
            if href:
                lines.append(f"   来源: {href}")
            lines.append("")

        return "\n".join(lines).strip()

    except ImportError:
        return (
            "网络搜索功能不可用，请安装依赖：\n"
            "pip install duckduckgo-search"
        )
    except Exception as exc:
        return f"搜索失败: {exc}"
