from fastapi import Depends, Request, HTTPException
from typing import Annotated, Optional
from .jwt_handler import verify_token
from db.user_store import get_user_by_id

async def get_current_user(request: Request) -> dict:
    """
    认证依赖注入，返回用户信息。
    
    优先级：
    1. Authorization: Bearer <jwt> → 验证 JWT
    2. X-Client-ID → 兼容匿名用户（过渡期）
    
    返回：
    - 已登录: {"id": "uuid", "name": "...", "is_anonymous": False}
    - 匿名: {"id": None, "client_id": "...", "is_anonymous": True}
    """
    # 1. 优先验证 Access Token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = verify_token(token)
        if payload and payload.get("type") == "access":
            user_id = payload["sub"]
            user = await get_user_by_id(user_id)
            if user and user["is_active"]:
                return {**user, "is_anonymous": False}

    # 2. 兼容模式：未登录时使用 client_id
    client_id = request.headers.get("X-Client-ID", "")
    if client_id:
        return {"id": None, "client_id": client_id, "is_anonymous": True}

    # 3. 实在没有信息，返回匿名但无 client_id (后续逻辑可能报错)
    return {"id": None, "client_id": None, "is_anonymous": True}

async def require_user(
    user: Annotated[dict, Depends(get_current_user)]
) -> dict:
    """强制登录要求"""
    if user["is_anonymous"]:
        raise HTTPException(status_code=401, detail="此操作需要登录")
    return user

# 类型别名
CurrentUser = Annotated[dict, Depends(get_current_user)]
RequiredUser = Annotated[dict, Depends(require_user)]
