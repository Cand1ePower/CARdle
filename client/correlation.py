import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="CARdle 多轮关联性判定桩服务", version="1.0.0")

class CorrelationRequest(BaseModel):
    query: str

@app.post("/chatnlu-server/v1")
async def correlate(req: CorrelationRequest):
    print(f"[Correlation Stub] 收到多轮关联性判定请求: '{req.query}'")
    query = req.query.strip()
    
    # 模拟关联判定：如果包含指代词或程度词，判定为“有关联”
    context_words = ["一点", "这个", "那个", "再", "它", "不要了", "换一首", "继续"]
    is_correlated = any(word in query for word in context_words)
    
    return {"is_correlated": is_correlated, "degraded": False}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8009)
