import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="CARdle 闲聊/NLG桩服务", version="1.0.0")

class NLGRequest(BaseModel):
    query: str

@app.post("/chat-server/v1")
async def chat_nlg(req: NLGRequest):
    print(f"[NLG Stub] 收到闲聊/NLG生成请求: '{req.query}'")
    query = req.query.strip()
    
    # 模拟 NLG 生成逻辑
    nlg = "您说得太有意思了！不过我的闲聊大模型模块正在升级中，很快就能和您畅聊啦~"
    if "你好" in query:
        nlg = "你好呀！我是您的智能车载助手，今天有什么可以帮您的？"
    elif "谁" in query:
        nlg = "我是 CARdle 语音智能控制网联中心，是您的全能特斯拉风车机小管家。"
    elif "笑话" in query:
        nlg = "为什么电脑不能喝水？因为会“蓝屏”呀！哈哈，这个笑话好笑吗？"
        
    return {"nlg": nlg, "degraded": False}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8010)
