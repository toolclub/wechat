# LLM Chat — 本地大语言模型对话系统

## 目录结构

```
llm-chat/
├── backend/
│   ├── main.py              # FastAPI 主入口
│   ├── config.py            # 集中配置
│   ├── memory_manager.py    # 三层记忆管理
│   ├── ollama_client.py     # Ollama API 客户端
│   ├── models.py            # Pydantic 数据模型
│   ├── pyproject.toml       # Python 项目配置
│   └── conversations/       # 对话持久化存储（自动创建）
└── frontend/
    ├── src/
    │   ├── App.vue
    │   ├── main.ts
    │   ├── style.css
    │   ├── api/index.ts
    │   ├── components/
    │   │   ├── Sidebar.vue
    │   │   ├── ChatView.vue
    │   │   ├── MessageItem.vue
    │   │   └── InputBox.vue
    │   ├── composables/useChat.ts
    │   └── types/index.ts
    ├── package.json
    └── vite.config.ts
```

---

## 前提条件

1. 安装 [Ollama](https://ollama.com/download)（Windows 版双击安装，安装后自动后台运行）
2. 下载模型：
   ```bash
   ollama pull qwen2.5:14b
   ollama pull qwen2.5:1.5b
   ollama pull nomic-embed-text
   ```

---

## 启动后端

```bash
cd llm-chat/backend

# 创建虚拟环境
python -m venv venv

# 激活（Windows）
venv\Scripts\activate

# 安装依赖
pip install -e .

# 启动
python main.py
```

后端运行在 http://localhost:8000，API 文档：http://localhost:8000/docs

---

## 启动前端

```bash
cd llm-chat/frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端运行在 http://localhost:5173

---

## 每次使用

```bash
# 1. 确认 Ollama 已运行
ollama list

# 2. 启动后端（新终端）
cd llm-chat/backend
venv\Scripts\activate
python main.py

# 3. 启动前端（新终端）
cd llm-chat/frontend
npm run dev
```

浏览器打开 http://localhost:5173 即可使用。
