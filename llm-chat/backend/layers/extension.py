"""
第 9 层 – Extension（扩展）
CORS 中间件、插件钩子，以及未来的网关 / 多渠道支持。.
author: leizihao
email: lzh19162600626@gmail.com
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings


def apply_cors(app: FastAPI, origins: list[str] = None) -> None:
    # 生产环境下 allow_credentials=True 时，origins 不允许为 ["*"]
    # 优先使用传入参数，否则从 settings 获取
    effective_origins = origins or settings.cors_allowed_origins
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=effective_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
