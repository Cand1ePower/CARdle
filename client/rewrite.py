import uvicorn
import os
import sys
from fastapi import FastAPI, Request
from pydantic import BaseModel

# 确保能导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm_async
from prompts import REWRITE_SYSTEM_PROMPT
from utils.logger import session

app = FastAPI(title="CARdle 多轮改写服务", version="2.0.0")

class RewriteRequest(BaseModel):
    query: str
    last_answer: str = ""

@app.post("/rewrite-server/v1")
async def rewrite(req: RewriteRequest, request: Request):
    session.trace_id = request.headers.get("X-Trace-Id", "unknown")
    print(f"[Rewrite Service] 收到改写请求: '{req.query}' | 上轮回答: '{req.last_answer}' | TraceID: {session.trace_id}")
    
    # 构造历史对话格式传入提示词
    if req.last_answer:
        history_text = f"对话历史:\nB: {req.last_answer}\nA: {req.query}"
    else:
        history_text = f"对话历史:\nA: {req.query}"
        
    messages = [
        {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
        {"role": "user", "content": f"{history_text}\n请改写A角色的最后一句话。"}
    ]
    
    try:
        rewritten = await call_llm_async(messages, temperature=0.1)
        print(f"  [OK] 改写完成: '{rewritten}'")
        return {"rewrite_query": rewritten, "degraded": False}
    except Exception as e:
        print(f"  [ERR] 改写失败: {e}")
        return {"rewrite_query": req.query, "degraded": True}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8006)
