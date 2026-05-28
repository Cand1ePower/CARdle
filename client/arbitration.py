import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="CARdle 多路仲裁桩服务", version="1.0.0")

class ArbitrationRequest(BaseModel):
    query: str

@app.post("/intent-server/v1")
async def arbitrate(req: ArbitrationRequest):
    print(f"[Arbitration Stub] 收到意图仲裁请求: '{req.query}'")
    query = req.query.strip()
    
    # 模拟仲裁分流：检测是否包含典型车控词
    task_keywords = [
        "空调", "导航", "播放", "打开", "关闭", "去", "地图", "温度", "音量",
        "调高", "调低", "一点", "高点", "低点", "大声", "小声", "调", "设为"
    ]
    is_task = any(word in query for word in task_keywords)
    
    branch = "task" if is_task else "chat"
    return {"branch": branch, "degraded": False}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8008)
