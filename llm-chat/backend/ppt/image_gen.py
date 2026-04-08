"""
文生图模块 — 支持 MiniMax image-01 和 OpenAI DALL-E 两种接口

MiniMax 接口格式：
  POST https://api.minimaxi.com/v1/image_generation
  body: { model, prompt, aspect_ratio, response_format: "base64" }
  resp: { data: { image_base64: ["base64str", ...] } }

OpenAI 接口格式：
  POST /v1/images/generations
  body: { model, prompt, size, n, response_format: "b64_json" }
  resp: { data: [{ b64_json: "..." }] }

通过 IMAGE_GEN_BASE_URL 自动判断用哪个格式。
"""
import base64
import logging

import httpx

from config import IMAGE_GEN_ENABLED, IMAGE_GEN_BASE_URL, IMAGE_GEN_API_KEY, IMAGE_GEN_MODEL

logger = logging.getLogger("ppt.image_gen")


async def generate_image(
    prompt: str,
    aspect_ratio: str = "16:9",
    reference_image_url: str = "",
) -> bytes | None:
    """
    根据 prompt 生成图片，返回 JPEG/PNG bytes。
    支持可选的参考图（MiniMax subject_reference）。
    失败或未配置时返回 None。
    """
    if not IMAGE_GEN_ENABLED or not IMAGE_GEN_MODEL:
        logger.debug("文生图未启用")
        return None

    try:
        if "minimax" in IMAGE_GEN_BASE_URL.lower():
            return await _generate_minimax(prompt, aspect_ratio, reference_image_url)
        else:
            return await _generate_openai(prompt, aspect_ratio)
    except Exception as exc:
        logger.warning("文生图失败 | prompt=%.50s | error=%s", prompt, exc)
        return None


async def _generate_minimax(
    prompt: str,
    aspect_ratio: str = "16:9",
    reference_image_url: str = "",
) -> bytes | None:
    """MiniMax image-01 接口。"""
    url = IMAGE_GEN_BASE_URL.rstrip("/")
    if not url.endswith("/image_generation"):
        url += "/image_generation"

    payload: dict = {
        "model": IMAGE_GEN_MODEL,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "base64",
    }

    # 可选：参考图（角色一致性）
    if reference_image_url:
        payload["subject_reference"] = [{
            "type": "character",
            "image_file": reference_image_url,
        }]

    headers = {"Authorization": f"Bearer {IMAGE_GEN_API_KEY}"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    images = data.get("data", {}).get("image_base64", [])
    if images:
        return base64.b64decode(images[0])

    logger.warning("MiniMax 返回空图片 | resp=%s", str(data)[:200])
    return None


async def _generate_openai(
    prompt: str,
    aspect_ratio: str = "16:9",
) -> bytes | None:
    """OpenAI DALL-E 兼容接口。"""
    # aspect_ratio → size 映射
    size_map = {
        "1:1": "1024x1024",
        "16:9": "1792x1024",
        "9:16": "1024x1792",
        "4:3": "1024x768",
    }
    size = size_map.get(aspect_ratio, "1024x1024")

    url = IMAGE_GEN_BASE_URL.rstrip("/")
    if "/v1" not in url:
        url += "/v1"
    url += "/images/generations"

    payload = {
        "model": IMAGE_GEN_MODEL,
        "prompt": prompt,
        "size": size,
        "n": 1,
        "response_format": "b64_json",
    }

    headers = {
        "Authorization": f"Bearer {IMAGE_GEN_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("data", [])
    if items and items[0].get("b64_json"):
        return base64.b64decode(items[0]["b64_json"])

    logger.warning("OpenAI 返回空图片 | resp=%s", str(data)[:200])
    return None
