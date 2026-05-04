# ChatFlow 用户登录系统设计文档

> **确认方案**:
> - 过渡期保留匿名访问（未登录仍可使用）
> - 记录用户使用统计（token消耗、操作次数）
> - 首次登录自动关联 client_id 数据到用户账号

---

## 一、概述

### 1.1 背景
当前 ChatFlow 没有用户登录功能，用户数据仅通过 `client_id`（浏览器 UUID）标识，存在以下问题：
- 数据无法跨设备同步
- 无法持久化用户偏好设置
- 无法提供个性化服务

### 1.2 目标
- 支持 Google OAuth 和 GitHub OAuth 登录（免费方案）
- 用户头像展示在左下角 Sidebar
- 用户 ID/名称使用 OAuth Provider 返回的信息
- 扩展性好的用户数据表结构
- 兼容现有数据（平滑迁移）

### 1.3 技术选型
| 组件 | 技术方案 | 理由 |
|------|----------|------|
| 认证方式 | JWT Token | 无状态、易扩展、适合前后端分离 |
| OAuth | Google OAuth 2.0 + GitHub OAuth | 免费、用户基数大 |
| Access Token 存储 | localStorage / 内存 | **15 分钟**短有效期，XSS 风险可控 |
| Access Token 传输 | **URL Fragment (#)** | 不发送到服务器日志，防泄露 |
| Refresh Token 存储 | **HttpOnly Cookie** | 防 XSS 攻击，前端脚本无法读取 |
| Refresh Token 传输 | Cookie (SameSite=Lax) | 防 CSRF，仅同站请求携带 |
| State 参数存储 | Redis（5分钟过期） | 防 CSRF 攻击，一次性使用 |
| CORS 配置 | 具体域名 + credentials | Cookie 跨域必须配置 |

---

## 二、数据库设计

### 2.1 新增表结构

#### 2.1.1 users（用户主表）
```sql
CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(36)     NOT NULL,           -- UUID 主键
    email           VARCHAR(255)    NOT NULL UNIQUE,    -- 邮箱（唯一）
    name            VARCHAR(100)    NOT NULL,           -- 显示名称
    avatar_url      VARCHAR(512)    DEFAULT '',         -- 头像 URL
    bio             TEXT            DEFAULT '',         -- 用户简介
    locale          VARCHAR(10)     DEFAULT 'zh-CN',    -- 语言偏好
    timezone        VARCHAR(50)     DEFAULT 'Asia/Shanghai',
    password_hash   VARCHAR(255)    DEFAULT '',         -- 未来密码登录预留
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    is_verified     BOOLEAN         NOT NULL DEFAULT FALSE,
    last_login_at   DOUBLE PRECISION DEFAULT 0,
    created_at      DOUBLE PRECISION NOT NULL,
    updated_at      DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_users PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
```

#### 2.1.2 oauth_accounts（OAuth 账号关联表）
支持一个用户绑定多个 OAuth Provider（如同时绑定 Google 和 GitHub）。

```sql
CREATE TABLE IF NOT EXISTS oauth_accounts (
    id              SERIAL          NOT NULL,
    user_id         VARCHAR(36)     NOT NULL,
    provider        VARCHAR(20)     NOT NULL,           -- 'google' | 'github' | 'apple' | ...
    provider_id     VARCHAR(255)    NOT NULL,           -- OAuth provider 的用户 ID
    provider_email  VARCHAR(255)    DEFAULT '',
    provider_name   VARCHAR(100)    DEFAULT '',
    provider_avatar VARCHAR(512)    DEFAULT '',
    access_token    TEXT            DEFAULT '',         -- OAuth access token（可选）
    refresh_token   TEXT            DEFAULT '',         -- OAuth refresh token（可选）
    token_expires_at DOUBLE PRECISION DEFAULT 0,
    raw_profile     JSONB           DEFAULT '{}',       -- 原始 profile 数据
    created_at      DOUBLE PRECISION NOT NULL,
    updated_at      DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_oauth_accounts PRIMARY KEY (id),
    CONSTRAINT fk_oauth_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_oauth_provider UNIQUE (provider, provider_id)
);
CREATE INDEX IF NOT EXISTS ix_oauth_user ON oauth_accounts(user_id);
```

#### 2.1.3 user_settings（用户设置表）
```sql
CREATE TABLE IF NOT EXISTS user_settings (
    id              SERIAL          NOT NULL,
    user_id         VARCHAR(36)     NOT NULL UNIQUE,
    theme           VARCHAR(20)     DEFAULT 'system',   -- 'light' | 'dark' | 'system'
    default_model   VARCHAR(100)    DEFAULT '',         -- 默认模型
    agent_mode_default BOOLEAN      DEFAULT TRUE,       -- 默认 Agent 模式
    language        VARCHAR(10)     DEFAULT 'zh-CN',
    notifications_enabled BOOLEAN   DEFAULT TRUE,
    sidebar_collapsed BOOLEAN       DEFAULT FALSE,
    custom_settings JSONB           DEFAULT '{}',       -- 扩展字段
    created_at      DOUBLE PRECISION NOT NULL,
    updated_at      DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_user_settings PRIMARY KEY (id),
    CONSTRAINT fk_settings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

#### 2.1.4 sessions（登录会话表）
存储 JWT refresh token，支持多设备登录管理。

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id              VARCHAR(36)     NOT NULL,           -- Session UUID
    user_id         VARCHAR(36)     NOT NULL,
    refresh_token_hash VARCHAR(255) NOT NULL UNIQUE,    -- Refresh Token 哈希（不存明文）
    device_info     VARCHAR(255)    DEFAULT '',         -- User-Agent 简化
    ip_address      VARCHAR(50)     DEFAULT '',
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    expires_at      DOUBLE PRECISION NOT NULL,
    created_at      DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_sessions PRIMARY KEY (id),
    CONSTRAINT fk_session_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
```

#### 2.1.5 oauth_states（OAuth state 参数临时存储）
防 CSRF 攻击，state 参数存 Redis 或数据库。

**方案 A：Redis 存储（推荐）**
```python
# 使用现有 Redis 连接，设置 5 分钟过期
await redis.set(f"oauth_state:{state}", provider, ex=300)
```

**方案 B：数据库表（无 Redis 时）**
```sql
CREATE TABLE IF NOT EXISTS oauth_states (
    id              SERIAL          NOT NULL,
    state           VARCHAR(64)     NOT NULL UNIQUE,    -- 随机生成的 state
    provider        VARCHAR(20)     NOT NULL,
    client_id       VARCHAR(36)     DEFAULT '',         -- 关联的 client_id（用于数据迁移）
    created_at      DOUBLE PRECISION NOT NULL,
    expires_at      DOUBLE PRECISION NOT NULL,          -- 5 分钟过期
    CONSTRAINT pk_oauth_states PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_oauth_states_state ON oauth_states(state);
```

#### 2.1.6 user_usage_logs（使用记录表）
记录用户行为统计，支持未来功能扩展（如用量限制、分析报表）。

```sql
CREATE TABLE IF NOT EXISTS user_usage_logs (
    id              SERIAL          NOT NULL,
    user_id         VARCHAR(36)     NOT NULL,
    action_type     VARCHAR(50)     NOT NULL,           -- 'chat' | 'tool_call' | 'upload' | ...
    resource_type   VARCHAR(50)     DEFAULT '',         -- 'conversation' | 'artifact' | ...
    resource_id     VARCHAR(36)     DEFAULT '',
    tokens_used     INTEGER         DEFAULT 0,          -- Token 消耗（可选）
    duration_ms     INTEGER         DEFAULT 0,          -- 耗时
    metadata        JSONB           DEFAULT '{}',
    created_at      DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_user_usage_logs PRIMARY KEY (id),
    CONSTRAINT fk_usage_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_usage_user_time ON user_usage_logs(user_id, created_at);
```

### 2.2 现有表改造

为现有业务表添加 `user_id` 字段（**注意：允许 NULL 或默认空值，不阻塞现有业务**）：

```sql
-- conversations 添加 user_id
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id VARCHAR(36) DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_conversations_user ON conversations(user_id);

-- quant_snapshots 添加 user_id
ALTER TABLE quant_snapshots ADD COLUMN IF NOT EXISTS user_id VARCHAR(36) DEFAULT '';
CREATE INDEX IF NOT EXISTS ix_quant_snapshots_user ON quant_snapshots(user_id);
```

### 2.3 数据关系图

```
┌──────────────┐     ┌─────────────────────┐
│    users     │────<│   oauth_accounts    │
│  (主表)      │     │  (OAuth账号关联)    │
└──────────────┘     └─────────────────────┘
       │
       │            ┌─────────────────────┐
       ├───────────<│    user_settings    │
       │            │    (用户设置)       │
       │            └─────────────────────┘
       │
       │            ┌─────────────────────┐
       ├───────────<│     sessions        │
       │            │   (登录会话)        │
       │            └─────────────────────┘
       │
       │            ┌─────────────────────┐
       ├───────────<│  user_usage_logs    │
       │            │   (使用记录)        │
       │            └─────────────────────┘
       │
       │            ┌─────────────────────┐
       ├───────────<│   conversations     │
       │            │   (对话，现有)      │
       │            └─────────────────────┘
       │
       │            ┌─────────────────────┐
       └───────────<│   quant_snapshots   │
                    │   (量化快照，现有)  │
                    └─────────────────────┘
```

---

## 三、后端 API 设计

### 3.1 文件结构（保持项目一致性）

```
llm-chat/backend/
├── routers/
│   └── auth_router.py      # 认证路由（新增）
├── services/
│   └── auth/               # 认证服务（新增）
│       ├── __init__.py
│       ├── jwt_handler.py  # JWT 生成/验证
│       ├── oauth_base.py   # OAuth Provider 抽象基类
│       ├── oauth_google.py # Google OAuth 实现
│       ├── oauth_github.py # GitHub OAuth 实现
│       └── dependencies.py # FastAPI 依赖注入
├── db/
│   ├── models.py           # 新增 UserModel 等 ORM
│   ├── migrate.py          # 新增迁移语句
│   ├── user_store.py       # 用户数据访问
│   └── session_store.py    # 会话数据访问
├── config.py               # 新增 JWT/OAuth 配置项
└── main.py                 # 注册 auth_router
```

### 3.2 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/oauth/{provider}/login` | 发起 OAuth 登录，重定向到 Provider |
| GET | `/api/auth/oauth/{provider}/callback` | **后端回调**，处理完重定向回前端 |
| POST | `/api/auth/token/refresh` | 刷新 access token（Cookie 中取 refresh token） |
| POST | `/api/auth/token/validate` | 验证 token 有效性 |
| GET | `/api/auth/me` | 获取当前用户信息 |
| PUT | `/api/auth/me` | 更新用户信息 |
| GET | `/api/auth/me/settings` | 获取用户设置 |
| PUT | `/api/auth/me/settings` | 更新用户设置 |
| GET | `/api/auth/me/sessions` | 获取登录设备列表 |
| POST | `/api/auth/logout` | 登出当前设备 |
| POST | `/api/auth/logout/all` | 登出所有设备 |
| POST | `/api/auth/oauth/{provider}/link` | 已登录用户关联新 OAuth |

### 3.3 OAuth 流程（改进版：后端回调）

```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  前端    │          │  后端    │          │  OAuth   │          │  用户    │
│          │          │          │          │ Provider │          │          │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ 1. 点击 [Google登录] │                     │                     │
     │                     │                     │                     │
     │ 2. GET /api/auth/oauth/google/login       │                     │
     │────────────────────>│                     │                     │
     │                     │                     │                     │
     │                     │ 生成 state, 存 Redis│                     │
     │                     │ (5分钟过期)         │                     │
     │                     │                     │                     │
     │ 3. 302 重定向到 Google 授权页              │                     │
     │<────────────────────│                     │                     │
     │ (Location: https://accounts.google.com/...)│                     │
     │                     │                     │                     │
     │ 4. 用户在 Google 页面授权                 │                     │
     │──────────────────────────────────────────>│                     │
     │                     │                     │                     │
     │                     │                     │ 5. 用户点击授权     │
     │                     │                     │<────────────────────│
     │                     │                     │                     │
     │ 6. Google 回调到后端（不是前端！）         │                     │
     │                     │ /api/auth/oauth/google/callback?code=xxx&state=yyy
     │                     │<──────────────────────────────────────────│
     │                     │                     │                     │
     │                     │ 7. 验证 state (Redis)                     │
     │                     │ 8. 用 code 换 token │                     │
     │                     │────────────────────>│                     │
     │                     │                     │                     │
     │                     │ 9. 返回 profile     │                     │
     │                     │<────────────────────│                     │
     │                     │                     │                     │
     │                     │ 10. 创建/查找用户   │                     │
     │                     │ 11. 关联 client_id 数据（如果有）         │
     │                     │ 12. 生成 JWT        │                     │
     │                     │ 13. Set-Cookie: refresh_token (HttpOnly)  │
     │                     │                     │                     │
     │ 14. 302 重定向回前端 │                     │                     │
     │<────────────────────│                     │                     │
     │ Location: /#auth_success=1&access_token=xxx│                     │
     │                     │                     │                     │
     │ 15. 前端从 hash 提取 access_token         │                     │
     │     存入 localStorage  │                     │                     │
     │     清理 hash (history.replaceState)      │                     │
```

**关键改进**：
- OAuth Provider 回调到**后端** `/api/auth/oauth/{provider}/callback`，不是前端
- 避免了 URL Fragment (#) 被 OAuth Provider 截断的问题
- **Access Token 通过 URL Fragment (#) 传输**，不会出现在服务器日志/Referer 中
- 后端处理完逻辑后，重定向回前端并携带 access_token

### 3.4 JWT 配置

新增配置项（`.env`）：
```env
# ── JWT 配置 ─────────────────────────────────────────────
JWT_SECRET_KEY=your-256-bit-secret-key-here  # >= 32 字节
JWT_ALGORITHM=HS256
JWT_ACCESS_EXPIRE_MINUTES=15                 # 缩短到 15 分钟
JWT_REFRESH_EXPIRE_DAYS=7

# ── OAuth 配置（JSON 格式）───────────────────────────────
# redirect_uri 必须是后端回调地址
OAUTH_PROVIDERS={"google":{"client_id":"xxx","client_secret":"yyy","redirect_uri":"http://localhost:8000/api/auth/oauth/google/callback"},"github":{"client_id":"xxx","client_secret":"yyy","redirect_uri":"http://localhost:8000/api/auth/oauth/github/callback"}}
```

### 3.5 认证依赖注入

```python
# services/auth/dependencies.py
from fastapi import Depends, Request, HTTPException, Response
from typing import Annotated

async def get_current_user(request: Request) -> dict:
    """
    认证依赖注入，返回用户信息。
    
    优先级：
    1. Authorization: Bearer <jwt> → 验证 JWT
    2. Cookie: refresh_token → 刷新后返回新用户
    3. X-Client-ID → 兼容匿名用户（过渡期）
    
    返回：
    - 已登录: {"id": "uuid", "name": "...", "is_anonymous": False}
    - 匿名: {"id": None, "client_id": "...", "is_anonymous": True}
    """
    from services.auth.jwt_handler import verify_token
    from db.user_store import get_user_by_id
    
    # 优先：Authorization header 的 Access Token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = verify_token(token)
        if payload and payload.get("type") == "access":
            user = await get_user_by_id(payload["sub"])
            if user and user["is_active"]:
                return {**user, "is_anonymous": False}
    
    # 兼容模式：未登录时使用 client_id
    client_id = request.headers.get("X-Client-ID", "")
    if client_id:
        return {"id": None, "client_id": client_id, "is_anonymous": True}
    
    # 未提供任何认证信息
    return {"id": None, "client_id": None, "is_anonymous": True}


async def require_user(
    user: Annotated[dict, Depends(get_current_user)]
) -> dict:
    """
    强制要求登录的依赖注入。
    用于需要登录才能执行的操作（如删除对话、修改设置）。
    """
    if user["is_anonymous"]:
        raise HTTPException(status_code=401, detail="此操作需要登录")
    return user


# 类型别名，方便使用
CurrentUser = Annotated[dict, Depends(get_current_user)]
RequiredUser = Annotated[dict, Depends(require_user)]
```

### 3.6 Token 刷新接口

```python
# routers/auth_router.py
from fastapi import Request, Response, HTTPException

@router.post("/token/refresh")
async def refresh_token(request: Request, response: Response):
    """
    刷新 Access Token。
    Refresh Token 从 HttpOnly Cookie 中读取。
    """
    from services.auth.jwt_handler import verify_token, create_access_token
    from db.session_store import validate_refresh_token, deactivate_session
    
    # 从 Cookie 获取 refresh_token
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="缺少 refresh token")
    
    # 验证 refresh token
    payload = verify_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="refresh token 无效")
    
    # 检查 session 是否有效
    session = await validate_refresh_token(payload["sub"], refresh_token)
    if not session:
        raise HTTPException(status_code=401, detail="session 已过期")
    
    # 生成新的 access token
    user = await get_user_by_id(payload["sub"])
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")
    
    new_access_token = create_access_token(user["id"])
    
    return {
        "access_token": new_access_token,
        "expires_in": 15 * 60,  # 15 分钟
    }
```

### 3.7 登出接口（彻底清理）

```python
# routers/auth_router.py

@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: RequiredUser
):
    """
    登出当前设备。
    
    清理步骤：
    1. 从 Cookie 获取 refresh_token
    2. 在 sessions 表标记 is_active = False
    3. 清除客户端 Cookie
    """
    from db.session_store import deactivate_session_by_token
    
    refresh_token = request.cookies.get("refresh_token")
    
    if refresh_token:
        # 标记 session 失效（服务器端注销）
        await deactivate_session_by_token(user["id"], refresh_token)
    
    # 清除 Cookie（客户端注销）
    response.delete_cookie(
        key="refresh_token",
        path="/",
        httponly=True,
        secure=True,  # 生产环境
        samesite="lax"
    )
    
    return {"success": True}


@router.post("/logout/all")
async def logout_all(
    response: Response,
    user: RequiredUser
):
    """
    登出所有设备。
    
    清理步骤：
    1. 在 sessions 表标记该用户所有 session 失效
    2. 清除当前设备 Cookie
    """
    from db.session_store import deactivate_all_sessions
    
    # 标记所有 session 失效
    await deactivate_all_sessions(user["id"])
    
    # 清除当前设备 Cookie
    response.delete_cookie(
        key="refresh_token",
        path="/",
        httponly=True,
        secure=True,
        samesite="lax"
    )
    
    return {"success": True, "message": "已登出所有设备"}
```

### 3.8 CORS 配置（Cookie 跨域必须）

```python
# layers/extension.py

def apply_cors(app: FastAPI) -> None:
    """
    CORS 配置。
    
    注意：使用 Cookie (credentials) 时，allow_origins 不能是 "*"，
    必须是具体的域名列表。
    """
    # 从环境变量读取允许的域名
    allowed_origins = settings.cors_allowed_origins  # ["http://localhost:5173", "https://www.chatflow-live.com"]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,  # 不能是 ["*"]
        allow_credentials=True,          # 必须：允许 Cookie 跨域
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Authorization"],  # 暴露 Authorization header
    )
```

**.env 配置示例**：
```env
# ── CORS 配置（Cookie 跨域必须配置具体域名）───────────────
# 开发环境
CORS_ALLOWED_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]

# 生产环境
CORS_ALLOWED_ORIGINS=["https://www.chatflow-live.com"]
```

---

## 四、前端设计

### 4.1 文件结构

```
llm-chat/frontend/src/
├── composables/
│   ├── useAuth.ts          # 新增：认证状态管理
│   └── useChat.ts          # 改造：添加 user_id 支持
├── components/
│   ├── Sidebar.vue         # 改造：添加用户头像区域
│   ├── LoginView.vue       # 新增：登录界面
│   ├── UserProfile.vue     # 新增：用户信息弹窗
│   └── UserAvatar.vue      # 新增：头像组件
├── api/
│   ├── index.ts            # 改造：添加拦截器处理 401
│   └── auth.ts             # 新增：认证 API
├── types/
│   └── index.ts            # 新增：User、UserSettings 类型
└── App.vue                 # 改造：登录状态判断
```

### 4.2 Token 存储策略

| Token | 存储位置 | 有效期 | 前端可访问 |
|-------|----------|--------|-----------|
| Access Token | localStorage / 内存 | **15 分钟** | Yes（需要发送给后端） |
| Refresh Token | **HttpOnly Cookie** | 7 天 | **No**（浏览器自动发送） |

### 4.3 API 拦截器（处理 401 自动刷新）

```typescript
// api/index.ts

const API_BASE = ''
let isRefreshing = false
let refreshPromise: Promise<string> | null = null

// ── Client ID 管理 ─────────────────────────────────────

/**
 * 确保 client_id 存在（首次访问时生成）
 * 永久存储，刷新页面不会丢失
 */
function ensureClientId(): string {
  let clientId = localStorage.getItem('cf_client_id')
  
  if (!clientId) {
    // 生成 UUID v4
    clientId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0
      const v = c === 'x' ? r : (r & 0x3 | 0x8)
      return v.toString(16)
    })
    localStorage.setItem('cf_client_id', clientId)
  }
  
  return clientId
}

// 应用启动时立即确保 client_id 存在
ensureClientId()

// ── Token 刷新 ─────────────────────────────────────────
async function refreshAccessToken(): Promise<string> {
  if (isRefreshing && refreshPromise) {
    return refreshPromise  // 并发请求时复用同一个刷新请求
  }
  
  isRefreshing = true
  refreshPromise = fetch(`${API_BASE}/api/auth/token/refresh`, {
    method: 'POST',
    credentials: 'include',  // 发送 Cookie（refresh_token）
  })
    .then(res => {
      if (!res.ok) throw new Error('刷新失败')
      return res.json()
    })
    .then(data => {
      localStorage.setItem('cf_access_token', data.access_token)
      return data.access_token
    })
    .finally(() => {
      isRefreshing = false
      refreshPromise = null
    })
  
  return refreshPromise
}

// 通用请求函数（带 401 自动刷新）
async function fetchWithAuth(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = localStorage.getItem('cf_access_token')
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...options.headers as Record<string, string>,
  }
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  
  // 兼容模式：发送 client_id
  const clientId = localStorage.getItem('cf_client_id')
  if (clientId) {
    headers['X-Client-ID'] = clientId
  }
  
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',  // 发送 Cookie
  })
  
  // 401 时尝试刷新 Token 并重试
  if (response.status === 401 && token) {
    try {
      const newToken = await refreshAccessToken()
      headers['Authorization'] = `Bearer ${newToken}`
      return fetch(url, { ...options, headers, credentials: 'include' })
    } catch {
      // 刷新失败，清除 token，跳转登录
      localStorage.removeItem('cf_access_token')
      window.location.reload()
    }
  }
  
  return response
}

// 导出封装后的请求函数
export async function get<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(`${API_BASE}${path}`)
  return res.json()
}

export async function post<T>(path: string, body: any): Promise<T> {
  const res = await fetchWithAuth(`${API_BASE}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return res.json()
}
```

### 4.4 useAuth Composable

```typescript
// composables/useAuth.ts
import { ref, computed, readonly } from 'vue'
import * as authApi from '../api/auth'
import { get } from '../api/index'

const user = ref<User | null>(null)
const settings = ref<UserSettings | null>(null)
const loading = ref(false)
const initialized = ref(false)

export function useAuth() {
  const isLoggedIn = computed(() => user.value !== null)
  const userName = computed(() => user.value?.name || '匿名用户')
  const userAvatar = computed(() => user.value?.avatar_url || '')
  
  // 初始化：验证本地 token
  async function init() {
    if (initialized.value) return
    
    loading.value = true
    const token = localStorage.getItem('cf_access_token')
    
    if (token) {
      try {
        const me = await get<{ user: User; settings: UserSettings }>('/api/auth/me')
        user.value = me.user
        settings.value = me.settings
      } catch {
        // Token 无效，尝试刷新（拦截器已处理）
        // 如果刷新失败，user 保持 null
      }
    }
    
    initialized.value = true
    loading.value = false
  }
  
  // OAuth 登录：直接跳转到后端接口
  async function loginWithOAuth(provider: 'google' | 'github') {
    // 直接跳转到后端，后端会重定向到 OAuth Provider
    window.location.href = `/api/auth/oauth/${provider}/login`
  }
  
  // 处理 OAuth 回调后的成功状态
  // 返回 true 表示需要刷新对话列表（多设备数据合并）
  async function handleAuthSuccess(accessToken: string): Promise<boolean> {
    localStorage.setItem('cf_access_token', accessToken)
    await init()
    return true  // 通知 App.vue 刷新对话列表
  }
  
  // 登出
  async function logout() {
    try {
      await authApi.logout()
    } catch {}
    localStorage.removeItem('cf_access_token')
    user.value = null
    settings.value = null
  }
  
  return {
    user: readonly(user),
    settings: readonly(settings),
    loading: readonly(loading),
    isLoggedIn,
    userName,
    userAvatar,
    init,
    loginWithOAuth,
    handleAuthSuccess,
    logout,
  }
}
```

### 4.5 LoginView 设计（带 Skip 按钮）

```vue
<!-- components/LoginView.vue -->
<template>
  <div class="login-view">
    <div class="login-card">
      <div class="login-logo">
        <svg><!-- Logo --></svg>
        <span>ChatFlow</span>
      </div>
      
      <h2 class="login-title">登录以继续</h2>
      <p class="login-subtitle">使用第三方账号快速登录</p>
      
      <div class="oauth-buttons">
        <button class="oauth-btn google-btn" @click="handleGoogleLogin">
          <svg><!-- Google icon --></svg>
          使用 Google 登录
        </button>
        
        <button class="oauth-btn github-btn" @click="handleGitHubLogin">
          <svg><!-- GitHub icon --></svg>
          使用 GitHub 登录
        </button>
      </div>
      
      <button class="skip-btn" @click="$emit('skip')">
        跳过，继续匿名使用
      </button>
      
      <p class="login-note">
        登录后，对话历史将永久保存
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useAuth } from '../composables/useAuth'

const emit = defineEmits(['skip'])
const auth = useAuth()

function handleGoogleLogin() {
  auth.loginWithOAuth('google')
}

function handleGitHubLogin() {
  auth.loginWithOAuth('github')
}
</script>
```

### 4.6 App.vue 改造

```vue
<!-- App.vue -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuth } from './composables/useAuth'
import { useChat } from './composables/useChat'
import LoginView from './components/LoginView.vue'

const auth = useAuth()
const chat = useChat()
const showLogin = ref(false)

onMounted(async () => {
  // 处理 OAuth 回调成功（从 URL Fragment 提取 token）
  if (window.location.hash.includes('auth_success=1')) {
    const hash = window.location.hash.slice(1)  // 去掉 #
    const params = new URLSearchParams(hash)
    const accessToken = params.get('access_token')
    
    if (accessToken) {
      // 登录成功，可能合并了多设备数据
      const needRefresh = await auth.handleAuthSuccess(accessToken)
      
      // 清理 URL hash（防止 token 泄露）
      window.history.replaceState({}, '', window.location.pathname)
      
      // 如果是多设备数据合并，需要刷新对话列表
      if (needRefresh) {
        await chat.loadConversations()
      }
    }
  }
  
  // 正常初始化
  await auth.init()
  
  // 加载对话（登录/匿名都可以）
  if (!auth.isLoggedIn.value) {
    await chat.loadConversations()
  }
  await chat.restoreFromHash()
})

// 点击登录按钮
function handleShowLogin() {
  showLogin.value = true
}

// 跳过登录
function handleSkipLogin() {
  showLogin.value = false
}
</script>

<template>
  <div class="app">
    <!-- 登录弹窗（覆盖层） -->
    <LoginView 
      v-if="showLogin" 
      @skip="handleSkipLogin"
    />
    
    <!-- 主界面 -->
    <template v-else>
      <Sidebar
        :conversations="chat.conversations.value"
        :currentConvId="chat.currentConvId.value"
        @showLogin="handleShowLogin"
      />
      <!-- ... 其他内容 ... -->
    </template>
  </div>
</template>
```

### 4.7 Sidebar 改造

```vue
<!-- Sidebar.vue 底部区域 -->
<template>
  <!-- ... 其他内容 ... -->
  
  <div class="sidebar-footer">
    <!-- 用户头像区域 -->
    <div v-if="auth.isLoggedIn.value" class="user-area" @click="showProfile = true">
      <img :src="auth.userAvatar.value" class="user-avatar" />
      <span class="user-name">{{ auth.userName.value }}</span>
    </div>
    
    <!-- 未登录：显示登录按钮 -->
    <button v-else class="login-btn" @click="$emit('showLogin')">
      <el-icon><User /></el-icon>
      <span>登录</span>
    </button>
    
    <!-- 暗色模式切换 -->
    <button class="dark-toggle" @click="toggleDark">
      <!-- ... -->
    </button>
  </div>
</template>
```

---

## 五、数据迁移策略

### 5.1 渐进式迁移

**Phase 1：过渡期（上线后 1 个月）**
- 新用户：JWT 认证，数据关联 `user_id`
- 老用户：继续使用 `client_id`，可正常使用
- 前端：登录后自动关联 `client_id` → `user_id`

**Phase 2：首次登录关联（幂等设计）**
用户首次登录时，后端自动将 `client_id` 的数据迁移到 `user_id`：

```python
# services/auth/oauth_handler.py
async def link_client_data_to_user(user_id: str, client_id: str) -> None:
    """
    将 client_id 的所有数据关联到 user_id。
    
    幂等设计：
    - 同一个 user_id 可以关联多个 client_id（多设备场景）
    - 已关联的数据不会重复处理
    """
    async with AsyncSessionLocal() as session:
        # 关联对话（只更新 user_id 为空的记录）
        result = await session.execute(
            update(ConversationModel)
            .where(ConversationModel.client_id == client_id)
            .where(ConversationModel.user_id == '')  # 只处理未关联的
            .values(user_id=user_id)
        )
        
        # 关联量化快照
        await session.execute(
            update(QuantSnapshotModel)
            .where(QuantSnapshotModel.client_id == client_id)
            .where(QuantSnapshotModel.user_id == '')
            .values(user_id=user_id)
        )
        
        await session.commit()
        
        logger.info(f"Linked client_id={client_id} to user_id={user_id}, "
                    f"updated {result.rowcount} conversations")
```

**多设备场景处理**：
- 用户设备 A（client_id_1）先登录 → 关联成功
- 用户设备 B（client_id_2）后登录 → 也关联到同一个 user_id
- 两个设备的对话历史合并到同一账号

**Phase 3：清理期（6 个月后）**
- 清理超过 6 个月未登录的匿名数据
- 提供数据导出功能（可选）

---

## 六、安全考虑

### 6.1 Token 存储安全

| 攻击类型 | 防护措施 |
|----------|----------|
| **XSS** | Refresh Token 存 HttpOnly Cookie，前端无法读取 |
| **CSRF** | OAuth state 参数存 Redis，5 分钟过期，一次性使用 |
| **Token 泄露** | Access Token 仅 15 分钟有效，泄露后影响有限 |

### 6.2 JWT 安全配置
- 使用 HS256 算法
- Secret Key >= 256 bits（32 字节）
- Access Token **15 分钟**过期（缩短风险窗口）
- Refresh Token 7 天过期
- Refresh Token 在 sessions 表存储**哈希值**（不存明文）

### 6.3 OAuth 安全
- **state 参数**：生成随机字符串，存 Redis 设置 5 分钟过期
- 回调时验证 state，防止 CSRF
- Redirect URI 必须与注册的一致（后端回调地址）
- 不存储 OAuth access token（除非需要调用 Provider API）

### 6.4 Cookie 配置

```python
# 设置 HttpOnly Cookie
response.set_cookie(
    key="refresh_token",
    value=refresh_token,
    max_age=7 * 24 * 60 * 60,  # 7 天
    httponly=True,             # 前端无法读取
    secure=True,               # 仅 HTTPS（生产环境）
    samesite="lax",            # 防 CSRF
)
```

### 6.5 未来密码登录预留
如果未来加入账号密码登录：
- 使用 `bcrypt` 或 `argon2` 进行加盐哈希存储
- 密码字段预留：`users.password_hash`

---

## 七、前端交互流程（完整版）

### 场景 1：首次访问（未登录过）

```
用户访问网页
    ↓
App.vue onMounted
    ↓
┌─────────────────────────────────────────────┐
│ 检查 localStorage: cf_client_id             │
│   - 不存在 → 生成 UUID，存入 localStorage   │
│   - 存在 → 直接使用                          │
└─────────────────────────────────────────────┘
    ↓
检查 localStorage: cf_access_token (不存在)
    ↓
直接显示主界面（匿名模式）—— 不弹出登录界面！
    ↓
Sidebar 左下角显示 [登录] 按钮
    ↓
用户可正常使用，数据用 client_id 标识
    ↓
后端记录：conversations.user_id = ''，client_id = xxx
```

**关键点**：首次访问**不会**弹出登录界面，直接进入主界面。

### 场景 2：匿名用户刷新页面

```
匿名用户刷新网页 / 再次访问
    ↓
App.vue onMounted
    ↓
检查 localStorage: cf_client_id (存在) → 使用现有 ID
    ↓
检查 localStorage: cf_access_token (不存在)
    ↓
直接显示主界面（匿名模式）—— 不弹出登录界面！
    ↓
调用 API（带 X-Client-ID header）加载对话历史
    ↓
Sidebar 显示 [登录] 按钮
```

**关键点**：匿名用户的 `cf_client_id` 持久化在 localStorage，刷新页面**不会**丢失，也**不会**弹出登录界面。

### 场景 3：点击登录按钮

```
用户主动点击 Sidebar 的 [登录] 按钮
    ↓
显示 LoginView 登录界面（覆盖层）
    ↓
用户有两个选择：
  ┌─────────────────────────────────────────┐
  │ A. 点击 [Google登录]                    │ → 跳转到后端 → OAuth → 回调 → 登录成功
  │ B. 点击 [跳过，继续匿名使用]            │ → 关闭登录界面，继续匿名使用
  └─────────────────────────────────────────┘

选择 B（跳过）后的状态：
    ↓
关闭 LoginView 覆盖层
    ↓
继续匿名使用（client_id 不变）
    ↓
下次刷新页面 → 仍然是匿名模式（不弹出登录界面）
```

**关键点**：登录界面只在用户**主动点击登录按钮**时才显示，刷新页面不会弹出。

### 场景 4：OAuth 登录成功

```
用户选择 Google 登录
    ↓
window.location.href = '/api/auth/oauth/google/login'
    ↓
后端生成 state，存 Redis（5分钟过期）
    ↓
302 重定向到 Google 授权页
    ↓
用户在 Google 页面授权（Chrome 已登录 Google 会显示账号列表）
    ↓
Google 回调到后端 /api/auth/oauth/google/callback?code=xxx&state=yyy
    ↓
后端验证 state，用 code 换 token，获取 profile
    ↓
后端创建/查找用户，关联 client_id 数据
    ↓
后端生成 JWT：
  - Access Token: 存在重定向 URL Fragment (#) 中
  - Refresh Token: 存在 HttpOnly Cookie 中
    ↓
302 重定向回前端: /#auth_success=1&access_token=xxx
    ↓
前端从 URL hash 提取 access_token，存 localStorage
    ↓
清理 hash (history.replaceState) 防止泄露
    ↓
前端调用 /api/auth/me 获取用户信息
    ↓
显示用户头像 + 名字
```

### 场景 5：已登录用户刷新页面

```
用户再次访问网页
    ↓
App.vue onMounted → auth.init()
    ↓
检查 localStorage: cf_access_token (存在)
    ↓
调用 GET /api/auth/me（带 Authorization header）
    ↓
┌─────────────────────────────────────┐
│ Access Token 有效（15分钟内）        │
│   → 直接登录成功                    │
│   → 显示用户头像                    │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Access Token 过期（超过15分钟）      │
│   → 后端返回 401                    │
│   → 前端拦截器自动调用 refresh       │
│   → Cookie 中的 refresh_token 发送给后端│
│   → 获取新的 access_token           │
│   → 重试原请求                       │
│   → 登录成功                         │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Refresh Token 也过期（超过7天）      │
│   → 刷新失败                         │
│   → 清除 access_token               │
│   → 显示登录按钮（匿名模式）          │
└─────────────────────────────────────┘
```

### Token 有效期总结

| Token/ID | 存储位置 | 有效期 | 刷新机制 |
|-------|----------|--------|----------|
| **client_id** | localStorage | **永久**（除非手动清除） | 不需要刷新 |
| Access Token | localStorage | **15 分钟** | 过期后自动刷新 |
| Refresh Token | HttpOnly Cookie | **7 天** | 过期后需重新登录 |

### localStorage 存储内容

```typescript
// localStorage 键值
{
  "cf_client_id": "uuid-xxx",      // 访客 ID（永久，匿名/登录都有）
  "cf_access_token": "eyJ...",     // JWT（仅登录后有）
  "cf_dark": "true",               // 暗色模式偏好
  "cf_agent_mode": "true"          // Agent 模式偏好
}
```

**关键设计**：
- `cf_client_id` 在**首次访问时生成**，永久存储
- 匿名用户刷新页面 → 使用现有 client_id → **不弹出登录界面**
- 登录界面只在用户**主动点击登录按钮**时才显示

### 完整交互流程图

```
                    ┌─────────────────────┐
                    │   用户访问网页       │
                    └─────────────┬───────┘
                                  ↓
              ┌───────────────────────────────────┐
              │ 检查 localStorage: cf_client_id   │
              └───────────────┬───────────────────┘
                     ↓ No              ↓ Yes
              ┌─────────────┐   ┌─────────────┐
              │ 生成 UUID   │   │ 使用现有 ID │
              │ 存 localStorage│   └─────────────┘
              └─────────────┘         │
                      │               │
                      └───────────────┘
                                  ↓
              ┌───────────────────────────────────┐
              │ 检查 localStorage: cf_access_token│
              └───────────────┬───────────────────┘
                     ↓ No              ↓ Yes
              ┌─────────────┐   ┌─────────────┐
              │ 匿名模式     │   │ 验证 Token  │
              │ 显示主界面   │   └──────┬──────┘
              │ [登录] 按钮  │          │
              └─────────────┘    ↓ Valid   ↓ Invalid
                                 ┌─────┐   ┌─────────┐
                                 │登录 │   │自动刷新 │
                                 │成功 │   │Token    │
                                 └─────┘   └─────┬───┘
                                           ↓ Success  ↓ Fail
                                           ┌─────┐   ┌─────────┐
                                           │登录 │   │匿名模式 │
                                           │成功 │   │[登录]按钮│
                                           └─────┘   └─────────┘
                      
                      │
                      ↓ 用户点击 [登录] 按钮
              ┌───────────────────────────────────┐
              │     显示 LoginView（覆盖层）      │
              └───────────────┬───────────────────┘
                     ↓                   ↓
          ┌─────────────────┐   ┌─────────────────┐
          │ 点击 [Google登录]│   │ 点击 [跳过]     │
          │ 跳转 OAuth      │   │ 关闭覆盖层      │
          │ ...             │   │ 继续匿名使用    │
          │ 登录成功        │   │ (client_id不变) │
          └─────────────────┘   └─────────────────┘
```

---

## 八、实施计划

### 8.1 Phase 1：后端基础（预计 3 天）
- 新增数据库表和 ORM 模型
- 实现 JWT handler（生成/验证）
- 实现 auth dependencies（get_current_user, require_user）
- 添加配置项

### 8.2 Phase 2：OAuth 集成（预计 2 天）
- 实现 OAuth base 抽象类
- 实现 Google OAuth provider
- 实现 GitHub OAuth provider
- 实现 state 参数 Redis 存储/验证
- 测试 OAuth 流程

### 8.3 Phase 3：前端改造（预计 3 天）
- 实现 API 拦截器（401 自动刷新）
- 实现 useAuth composable
- 实现 LoginView（带 Skip 按钮）
- 改造 Sidebar（用户头像区域）
- 改造 App.vue（OAuth 回调处理）

### 8.4 Phase 4：数据迁移（预计 2 天）
- 实现 client_id → user_id 关联逻辑（幂等）
- 测试多设备场景
- 清理脚本（可选，6 个月后）

---

## 九、关键文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/db/models.py` | 新增 | UserModel、OAuthAccountModel 等 ORM |
| `backend/db/migrate.py` | 新增 | 用户系统迁移语句 |
| `backend/config.py` | 新增 | JWT_SECRET_KEY、OAUTH_PROVIDERS 配置 |
| `backend/services/auth/*.py` | 新增 | JWT、OAuth、Dependencies |
| `backend/routers/auth_router.py` | 新增 | 认证路由 |
| `backend/main.py` | 改造 | 注册 auth_router |
| `frontend/src/api/index.ts` | 改造 | 401 自动刷新拦截器 |
| `frontend/src/composables/useAuth.ts` | 新增 | 认证状态管理 |
| `frontend/src/components/LoginView.vue` | 新增 | 登录界面（带 Skip） |
| `frontend/src/components/Sidebar.vue` | 改造 | 用户头像区域 |
| `frontend/src/App.vue` | 改造 | OAuth 回调处理 |

---

## 十、OAuth Provider 配置指南

### 10.1 Google OAuth
1. 访问 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建项目 → APIs & Services → Credentials
3. 创建 OAuth 2.0 Client ID（Web application）
4. **配置 Authorized redirect URIs**：
   - 开发环境：`http://localhost:8000/api/auth/oauth/google/callback`
   - 生产环境：`https://www.chatflow-live.com/api/auth/oauth/google/callback`
5. 获取 client_id 和 client_secret

### 10.2 GitHub OAuth
1. 访问 [GitHub Settings](https://github.com/settings/developers)
2. OAuth Apps → New OAuth App
3. **Authorization callback URL**：
   - 开发环境：`http://localhost:8000/api/auth/oauth/github/callback`
   - 生产环境：`https://www.chatflow-live.com/api/auth/oauth/github/callback`
4. 获取 client_id 和 client_secret

**注意**：Redirect URI 必须是**后端回调地址**，不是前端地址。

### 10.3 .env 配置示例

```env
# ── 开发环境 ─────────────────────────────────────────────
OAUTH_PROVIDERS={"google":{"client_id":"xxx","client_secret":"yyy","redirect_uri":"http://localhost:8000/api/auth/oauth/google/callback"},"github":{"client_id":"xxx","client_secret":"yyy","redirect_uri":"http://localhost:8000/api/auth/oauth/github/callback"}}
CORS_ALLOWED_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]

# ── 生产环境 ─────────────────────────────────────────────
OAUTH_PROVIDERS={"google":{"client_id":"xxx","client_secret":"yyy","redirect_uri":"https://www.chatflow-live.com/api/auth/oauth/google/callback"},"github":{"client_id":"xxx","client_secret":"yyy","redirect_uri":"https://www.chatflow-live.com/api/auth/oauth/github/callback"}}
CORS_ALLOWED_ORIGINS=["https://www.chatflow-live.com"]
```

---

## 十一、附录

### 11.1 User 类型定义
```typescript
interface User {
  id: string
  email: string
  name: string
  avatar_url: string
  bio?: string
  locale: string
  timezone: string
  is_active: boolean
  is_verified: boolean
  last_login_at: number
  created_at: number
}

interface UserSettings {
  theme: 'light' | 'dark' | 'system'
  default_model: string
  agent_mode_default: boolean
  language: string
  notifications_enabled: boolean
  sidebar_collapsed: boolean
  custom_settings: Record<string, any>
}
```

### 11.2 API 响应格式
```typescript
// GET /api/auth/me
{
  "user": User,
  "settings": UserSettings,
  "oauth_accounts": [
    { "provider": "google", "provider_name": "...", "provider_avatar": "..." },
    { "provider": "github", "provider_name": "...", "provider_avatar": "..." }
  ]
}

// OAuth 回调重定向 URL（使用 Fragment #，不发送到服务器）
/#auth_success=1&access_token=eyJ...

// POST /api/auth/token/refresh
{
  "access_token": "eyJ...",
  "expires_in": 900  // 15 分钟 = 900 秒
}
```