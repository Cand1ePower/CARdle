import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="CARdle 安全拒识桩服务", version="1.0.0")

class RejectRequest(BaseModel):
    query: str

@app.post("/reject-server/v1")
async def reject(req: RejectRequest):
    print(f"[Reject Stub] 收到拒识判定请求: '{req.query}'")
    # 模拟安全拒识逻辑：敏感词或超纲词触发拒识
    query = req.query.strip()
    is_reject = False
    reject_score = 0.0
    
    sensitive_words = ["垃圾", "笨蛋", "毁灭世界", "坏车机", "脏话"]
    if any(word in query for word in sensitive_words):
        is_reject = True
        reject_score = 0.95
    else:
        is_reject = False
        reject_score = 0.02

    return {"reject_score": reject_score, "is_reject": is_reject, "degraded": False}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8007)
