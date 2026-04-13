"""
artifacts 路由：文件产物（代码 / PPT / 压缩包 / 图片）元数据、详情与下载

═══════════════════════════════════════════════════════════════════════════════
路由一览
═══════════════════════════════════════════════════════════════════════════════

  GET /api/conversations/{conv_id}/artifacts —— 列出对话的所有 artifact 元数据
  GET /api/artifacts/{artifact_id}            —— 按需拉取单个 artifact 完整内容
  GET /api/artifacts/{artifact_id}/download   —— 浏览器触发的文件下载

═══════════════════════════════════════════════════════════════════════════════
设计要点：元数据 / 内容分离
═══════════════════════════════════════════════════════════════════════════════

数据库里的 artifact content 可能很大（pptx base64、tar.gz base64、长代码），
首屏加载只需要元数据就能画出卡片，点击打开才需要真正的内容。拆成两个接口：

  get_artifact_meta_list(conv_id) —— 只选 meta 列，加载快（列表场景）
  get_artifact_content(artifact_id) —— 惰性拉取完整内容（详情 / 下载）

下载场景对二进制 artifact 还要额外做 base64 解码 + MIME 映射 +
Content-Disposition 设置文件名（支持中文），逻辑集中在本模块内。
"""
from __future__ import annotations

import base64
import json as _json
import logging
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import Response

from db.artifact_store import get_artifact_content, get_artifact_meta_list

logger = logging.getLogger("api.artifacts")

router = APIRouter(tags=["artifacts"])


# 二进制类型到 MIME 的映射表
# 非二进制（code / html / text）走 text/plain 分支，不走这个表
_BINARY_MIME_MAP: dict[str, str] = {
    "archive": "application/gzip",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


# ── 元数据列表（供前端渲染文件卡片） ─────────────────────────────────────────

@router.get("/api/conversations/{conv_id}/artifacts")
async def list_conversation_artifacts(conv_id: str):
    """获取对话的文件产物元数据列表（不含 content，加载快）。"""
    artifacts = await get_artifact_meta_list(conv_id)
    return {"artifacts": artifacts}


# ── 单个产物详情（点击卡片时懒加载） ─────────────────────────────────────────

@router.get("/api/artifacts/{artifact_id}")
async def get_artifact_detail(artifact_id: int):
    """按需加载单个产物的完整内容（含二进制、slides_html 等）。前端点击时调用。"""
    data = await get_artifact_content(artifact_id)
    if not data:
        return {"error": "产物不存在"}
    return data


# ── 下载 ────────────────────────────────────────────────────────────────────

@router.get("/api/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: int):
    """
    下载文件产物（二进制流，浏览器直接触发下载）。

    支持所有 artifact 类型：
      - code / html / text : 源码原文下载
      - pptx / pdf         : 从 base64 解码后的二进制
      - archive            : tar.gz 二进制
    """
    data = await get_artifact_content(artifact_id)
    if not data:
        return {"error": "产物不存在"}

    name = data.get("name", "download")
    content = data.get("content", "")
    language = data.get("language", "text")

    # ── 二进制类型分支（pptx / archive / pdf） ─────────────────────────────
    if data.get("binary") or language in _BINARY_MIME_MAP:
        raw_bytes = _decode_binary_content(content)
        if raw_bytes is None:
            return {"error": "文件解码失败"}

        mime = _BINARY_MIME_MAP.get(language, "application/octet-stream")
        return Response(
            content=raw_bytes,
            media_type=mime,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            },
        )

    # ── 文本类型分支（直接作为 UTF-8 下载） ────────────────────────────────
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        },
    )


def _decode_binary_content(content: str) -> bytes | None:
    """
    把 artifact.content 解码成原始二进制字节。

    历史包袱：早期版本把 pptx 二进制包在 JSON（{"binary_b64": "..."}）里写进
    content 字段，后来直接写裸 base64。下载时两种格式都要兼容，先尝试作为
    JSON 解，失败回退到裸 base64 解码。

    失败时返回 None，由调用方生成错误响应（而不是抛异常中断请求）。
    """
    binary_b64 = content

    if content.startswith("{"):
        # 兼容旧数据：content 是 JSON 包装的 {"binary_b64": "..."}
        try:
            packed = _json.loads(content)
            binary_b64 = packed.get("binary_b64", content)
        except _json.JSONDecodeError:
            # 不是 JSON，就按裸 base64 处理
            pass

    try:
        return base64.b64decode(binary_b64)
    except Exception as exc:
        logger.warning("artifact 二进制解码失败: %s", exc)
        return None
