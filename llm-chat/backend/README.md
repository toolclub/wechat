# LLM Chat 后端

## 启动步骤

```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. 安装依赖
pip install -e .

# 4. 启动服务
python main.py
```

服务启动后访问 http://localhost:8000/docs 查看 API 文档。

## 前提条件

- 已安装并运行 Ollama（https://ollama.com/download）
- 已下载所需模型：
  ```bash
  ollama pull qwen2.5:14b
  ollama pull qwen2.5:1.5b
  ollama pull nomic-embed-text
  ```
