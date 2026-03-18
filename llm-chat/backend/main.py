import uuid
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from models import ChatRequest, CreateConversationRequest, UpdateConversationRequest
from memory_manager import memory
from ollama_client import chat_stream, list_models
from config import CHAT_MODEL, BACKEND_HOST, BACKEND_PORT

app = FastAPI(title="本地LLM对话服务")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 模型 ──

@app.get("/api/models")
async def get_models():
    models = await list_models()
    return {"models": models}


# ── 对话管理 ──

@app.get("/api/conversations")
async def get_conversations():
    return {"conversations": memory.list_conversations()}


@app.post("/api/conversations")
async def create_conversation(req: CreateConversationRequest):
    conv_id = str(uuid.uuid4())[:8]
    conv = memory.create_conversation(
        conv_id=conv_id,
        title=req.title or "新对话",
        system_prompt=req.system_prompt or "",
    )
    return {"id": conv.id, "title": conv.title}


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = memory.get_conversation(conv_id)
    if not conv:
        return {"error": "对话不存在"}
    return {
        "id": conv.id,
        "title": conv.title,
        "system_prompt": conv.system_prompt,
        "messages": [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in conv.short_term
        ],
        "mid_term_summary": conv.mid_term_summary,
    }


@app.patch("/api/conversations/{conv_id}")
async def update_conversation(conv_id: str, req: UpdateConversationRequest):
    conv = memory.get_conversation(conv_id)
    if not conv:
        return {"error": "对话不存在"}
    if req.title is not None:
        conv.title = req.title
    if req.system_prompt is not None:
        conv.system_prompt = req.system_prompt
    memory._save(conv)
    return {"ok": True}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    memory.delete_conversation(conv_id)
    return {"ok": True}


# ── 聊天（流式 SSE） ──

@app.post("/api/chat")
async def chat(req: ChatRequest):
    conv = memory.get_conversation(req.conversation_id)
    if not conv:
        conv = memory.create_conversation(req.conversation_id)

    # 记录用户消息
    memory.add_message(req.conversation_id, "user", req.message)

    # 构建 messages
    messages = memory.build_messages(conv)

    # 用对话主模型流式生成
    model = req.model or CHAT_MODEL

    async def generate():
        full_response = ""
        async for chunk in chat_stream(
            model=model,
            messages=messages,
            temperature=req.temperature,
        ):
            full_response += chunk
            yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

        # 记录 AI 回复
        memory.add_message(req.conversation_id, "assistant", full_response)

        # 尝试压缩（使用摘要小模型，不影响对话模型）
        compressed = await memory.maybe_compress(req.conversation_id)

        yield f"data: {json.dumps({'done': True, 'compressed': compressed})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 记忆调试 ──

@app.get("/api/conversations/{conv_id}/memory")
async def get_memory_debug(conv_id: str):
    conv = memory.get_conversation(conv_id)
    if not conv:
        return {"error": "对话不存在"}
    return {
        "short_term_count": len(conv.short_term),
        "mid_term_summary": conv.mid_term_summary or "(空)",
        "build_messages_preview": [
            {"role": m["role"], "content": m["content"][:80] + "..." if len(m["content"]) > 80 else m["content"]}
            for m in memory.build_messages(conv)
        ],
    }


# ── 预留：Embedding 测试接口 ──

@app.post("/api/embedding")
async def test_embedding(text: str = "测试文本"):
    from ollama_client import get_embedding
    from config import EMBEDDING_MODEL
    vec = await get_embedding(text, EMBEDDING_MODEL)
    return {
        "model": EMBEDDING_MODEL,
        "text": text,
        "dimensions": len(vec),
        "vector_preview": vec[:5],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT)
