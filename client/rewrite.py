import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="CARdle 多轮改写桩服务", version="1.0.0")

class RewriteRequest(BaseModel):
    query: str
    last_answer: str = ""

@app.post("/rewrite-server/v1")
async def rewrite(req: RewriteRequest):
    print(f"[Rewrite Stub] 收到改写请求: '{req.query}' | 上轮回答: '{req.last_answer}'")
    # 模拟改写逻辑：如果是多轮省略（比如“调高一点”），桩服务进行模拟改写
    rewritten = req.query
    if "调高一点" in req.query:
        rewritten = "帮我把空调温度调高一点"
    elif "它" in req.query:
        rewritten = req.query.replace("它", "车载导航")
        
    return {"rewrite_query": rewritten, "degraded": False}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8006)
