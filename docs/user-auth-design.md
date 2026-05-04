# ChatFlow 用户登录系统设计文档

> **确认方案**:
> - 过渡期保留匿名访问（未登录仍可使用）
> - 记录用户使用统计（token消耗、操作次数）
> - 首次登录自动关联 client_id 数据到用户账号

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
| Token 存储 | localStorage + 后端 Session 表 | 前端持久化 + 后端刷新令牌管理 |
| 数据迁移 | 渐进式关联 | 过渡期兼容 anonymous 用户 |

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
    refresh_token   VARCHAR(255)    NOT NULL UNIQUE,    -- JWT refresh token
    device_info     VARCHAR(255)    DEFAULT '',         -- User-Agent 简化
    ip_address      VARCHAR(50)     DEFAULT '',
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    expires_at      DOUBLE PRECISION NOT NULL,
    created_at      DOUBLE PRECISION NOT NULL,
    CONSTRAINT pk_sessions PRIMARY KEY (id),
    CONSTRAINT fk_session_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_refresh ON sessions(refresh_token);
```

#### 2.1.5 user_usage_logs（使用记录表）
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

为现有业务表添加 `user_id` 字段：

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

### 3.1 文件结构

```
llm-chat/backend/
├── auth/
│   ├── __init__.py
│   ├── models.py           # Pydantic 请求/响应模型
│   ├── jwt_handler.py      # JWT 生成/验证
│   ├── oauth_base.py       # OAuth Provider 抽象基类
│   ├── oauth_google.py     # Google OAuth 实现
│   ├── oauth_github.py     # GitHub OAuth 实现
│   ├── dependencies.py     # FastAPI 依赖注入（get_current_user）
│   └── router.py           # 认证路由
├── db/
│   ├── models.py           # 新增 UserModel 等 ORM
│   ├── migrate.py          # 新增迁移语句
│   ├── user_store.py       # 用户数据访问
│   ├── session_store.py    # 会话数据访问
│   └── usage_store.py      # 使用记录数据访问
├── config.py               # 新增 JWT/OAuth 配置项
└── main.py                 # 注册 auth_router
```

### 3.2 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/oauth/{provider}/login` | 发起 OAuth 登录，返回授权 URL |
| GET | `/api/auth/oauth/{provider}/callback` | OAuth 回调，完成登录返回 JWT |
| POST | `/api/auth/token/refresh` | 刷新 access token |
| POST | `/api/auth/token/validate` | 验证 token 有效性 |
| GET | `/api/auth/me` | 获取当前用户信息 |
| PUT | `/api/auth/me` | 更新用户信息 |
| GET | `/api/auth/me/settings` | 获取用户设置 |
| PUT | `/api/auth/me/settings` | 更新用户设置 |
| GET | `/api/auth/me/sessions` | 获取登录设备列表 |
| POST | `/api/auth/logout` | 登出当前设备 |
| POST | `/api/auth/logout/all` | 登出所有设备 |
| POST | `/api/auth/oauth/{provider}/link` | 已登录用户关联新 OAuth |

### 3.3 OAuth 流程

```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│  前端    │          │  后端    │          │  OAuth   │          │  用户    │
│          │          │          │          │ Provider │          │          │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │ 1. GET /api/auth/oauth/google/login       │                     │
     │────────────────────>│                     │                     │
     │                     │                     │                     │
     │ 2. 返回授权 URL + state                    │                     │
     │<────────────────────│                     │                     │
     │                     │                     │                     │
     │ 3. 重定向到 Google 授权页                  │                     │
     │──────────────────────────────────────────>│                     │
     │                     │                     │                     │
     │                     │                     │ 4. 用户授权         │
     │                     │                     │<────────────────────│
     │                     │                     │                     │
     │ 5. 回调: /api/auth/oauth/google/callback?code=xxx&state=yyy     │
     │────────────────────>│                     │                     │
     │                     │                     │                     │
     │                     │ 6. 用 code 换 token │                     │
     │                     │────────────────────>│                     │
     │                     │                     │                     │
     │                     │ 7. 返回 access_token + profile             │
     │                     │<────────────────────│                     │
     │                     │                     │                     │
     │ 8. 创建/查找用户，生成 JWT，返回           │                     │
     │<────────────────────│                     │                     │
     │                     │                     │                     │
```

### 3.4 JWT 配置

新增配置项（`.env`）：
```env
# ── JWT 配置 ─────────────────────────────────────────────
JWT_SECRET_KEY=your-256-bit-secret-key-here
JWT_ACCESS_EXPIRE_MINUTES=30
JWT_REFRESH_EXPIRE_DAYS=7

# ── OAuth 配置（JSON 格式）───────────────────────────────
OAUTH_PROVIDERS={"google":{"client_id":"xxx","client_secret":"yyy","redirect_uri":"http://localhost:5173/#/auth/callback"},"github":{"client_id":"xxx","client_secret":"yyy","redirect_uri":"http://localhost:5173/#/auth/callback"}}
```

### 3.5 认证中间件

```python
# auth/dependencies.py
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

    raise HTTPException(status_code=401, detail="未登录")
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
│   ├── index.ts            # 改造：添加 Authorization header
│   └── auth.ts             # 新增：认证 API
├── types/
│   └── index.ts            # 新增：User、UserSettings 类型
└── App.vue                 # 改造：登录状态判断
```

### 4.2 useAuth Composable

核心功能：
- `init()` - 初始化，检查本地 token 并验证
- `loginWithOAuth(provider)` - 发起 OAuth 登录
- `handleOAuthCallback()` - 处理 OAuth 回调
- `logout()` - 登出
- `isLoggedIn` / `user` / `userName` / `userAvatar` - 状态

Token 存储：
- `cf_access_token` - localStorage（JWT access token）
- `cf_refresh_token` - localStorage（JWT refresh token）

### 4.3 Sidebar 改造

在 `sidebar-footer` 区域上方添加用户区域：

```vue
<div class="sidebar-footer">
  <!-- 新增：用户头像区域 -->
  <div v-if="auth.isLoggedIn.value" class="user-area" @click="showProfile = true">
    <img :src="auth.userAvatar.value" class="user-avatar" />
    <span class="user-name">{{ auth.userName.value }}</span>
  </div>
  <button v-else class="login-btn" @click="$emit('showLogin')">
    <span>登录</span>
  </button>

  <!-- 现有：暗色模式切换 -->
  <button class="dark-toggle" @click="toggleDark">...</button>
</div>
```

样式：
- 用户头像：32px 圆形，使用 OAuth 返回的 avatar_url
- 未登录：显示"登录"按钮，点击跳转登录页

### 4.4 LoginView 设计

界面布局：
```
┌────────────────────────────────────┐
│                                    │
│         [ChatFlow Logo]            │
│                                    │
│         登录以继续                 │
│     使用第三方账号快速登录         │
│                                    │
│  ┌────────────────────────────┐   │
│  │  [G]  使用 Google 登录     │   │
│  └────────────────────────────┘   │
│                                    │
│  ┌────────────────────────────┐   │
│  │  [GitHub] 使用 GitHub 登录 │   │
│  └────────────────────────────┘   │
│                                    │
│     登录后，对话历史永久保存       │
│                                    │
└────────────────────────────────────┘
```

### 4.5 API 改造

修改 `api/index.ts` 的 `commonHeaders()`：

```typescript
function commonHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  // JWT Token
  const token = localStorage.getItem('cf_access_token')
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  // 兼容模式：过渡期保留 X-Client-ID
  const clientId = localStorage.getItem('cf_client_id')
  if (clientId) {
    headers['X-Client-ID'] = clientId
  }

  return headers
}
```

---

## 五、数据迁移策略

### 5.1 渐进式迁移

**Phase 1：过渡期（上线后 1 个月）**
- 新用户：JWT 认证，数据关联 `user_id`
- 老用户：继续使用 `client_id`，可正常使用
- 前端：登录后自动关联 `client_id` → `user_id`

**Phase 2：首次登录关联**
用户首次登录时，后端自动将 `client_id` 的数据迁移到 `user_id`：
```python
async def link_client_data_to_user(user_id: str, client_id: str):
    # 关联对话
    await session.execute(
        update(ConversationModel)
        .where(ConversationModel.client_id == client_id)
        .values(user_id=user_id)
    )
    # 关联量化快照
    await session.execute(
        update(QuantSnapshotModel)
        .where(QuantSnapshotModel.client_id == client_id)
        .values(user_id=user_id)
    )
```

**Phase 3：清理期（6 个月后）**
- 清理超过 6 个月未登录的匿名数据
- 提供数据导出功能（可选）

### 5.2 匿名模式保留

过渡期保留匿名访问能力：
- 未登录用户仍可使用，数据用 `client_id` 标识
- 登录后提示"您的对话历史已保存到账号"

---

## 六、安全考虑

### 6.1 JWT 安全
- 使用 HS256 算法
- Secret Key >= 256 bits（32 字节）
- Access Token 30 分钟过期
- Refresh Token 7 天过期，存储在 sessions 表

### 6.2 OAuth 安全
- 使用 `state` 参数防 CSRF
- Redirect URI 必须与注册的一致
- 不存储 OAuth access token（除非需要调用 Provider API）

### 6.3 CORS
生产环境需配置具体域名：
```python
allow_origins=["https://your-domain.com"]
```

---

## 七、实施计划

### 7.1 Phase 1：后端基础（预计 3 天）
- 新增数据库表和 ORM 模型
- 实现 JWT handler
- 实现 auth router 和 dependencies
- 添加配置项

### 7.2 Phase 2：OAuth 集成（预计 2 天）
- 实现 Google OAuth provider
- 实现 GitHub OAuth provider
- 测试 OAuth 流程

### 7.3 Phase 3：前端改造（预计 3 天）
- 实现 useAuth composable
- 实现 LoginView
- 改造 Sidebar（用户头像）
- 改造 App.vue（登录判断）
- 改造 API headers

### 7.4 Phase 4：数据迁移（预计 2 天）
- 实现 client_id → user_id 关联逻辑
- 测试迁移流程
- 清理脚本（可选）

---

## 八、关键文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/db/models.py` | 新增 | UserModel、OAuthAccountModel 等 ORM |
| `backend/db/migrate.py` | 新增 | 用户系统迁移语句 |
| `backend/config.py` | 新增 | JWT_SECRET_KEY、OAUTH_PROVIDERS 配置 |
| `backend/auth/*.py` | 新增 | 认证模块（router、jwt、oauth） |
| `backend/db/user_store.py` | 新增 | 用户数据访问层 |
| `backend/main.py` | 改造 | 注册 auth_router |
| `frontend/src/composables/useAuth.ts` | 新增 | 认证状态管理 |
| `frontend/src/components/LoginView.vue` | 新增 | 登录界面 |
| `frontend/src/components/Sidebar.vue` | 改造 | 用户头像区域 |
| `frontend/src/api/index.ts` | 改造 | Authorization header |
| `frontend/src/App.vue` | 改造 | 登录状态判断 |

---

## 九、OAuth Provider 配置指南

### 9.1 Google OAuth
1. 访问 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建项目 → APIs & Services → Credentials
3. 创建 OAuth 2.0 Client ID（Web application）
4. 配置 Authorized redirect URIs：`http://localhost:5173/#/auth/callback`
5. 获取 client_id 和 client_secret

### 9.2 GitHub OAuth
1. 访问 [GitHub Settings](https://github.com/settings/developers)
2. OAuth Apps → New OAuth App
3. Authorization callback URL：`http://localhost:5173/#/auth/callback`
4. 获取 client_id 和 client_secret

---

## 十、附录

### 10.1 User 类型定义
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

### 10.2 API 响应格式
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

// GET /api/auth/oauth/{provider}/callback
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "user": User,
  "settings": UserSettings
}
```