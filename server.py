import os
import json
import time
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 1. 声明标准的 ASGI 高性能异步 Socket.IO 服务端
# async_mode='asgi' 代表它完美融入 FastAPI 异步事件循环
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI(title="CARdle 语音智能控制网联中心", version="1.0.0")

# 2. 挂载标准跨域中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. 使用 Socket.IO 的 ASGIApp 包装整个 FastAPI 应用实现融合，防止路由无限循环递归
# 统一的 ASGI 入口点暴露为 combined_app 供 uvicorn 直接加载
combined_app = socketio.ASGIApp(sio, other_asgi_app=app)

# 4. 一个高性能的异步运维监控健康接口 (秒响应)
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "CARdle"}

# 5. WebSocket 异步连接/断开事件监听
@sio.event
async def connect(sid, environ):
    print(f"[+] Client connected via WebSocket: {sid}")

@sio.event
async def disconnect(sid):
    print(f"[-] Client disconnected: {sid}")

# 6. 核心对话网关入口事件 (异步处理，秒级切回防阻塞)
@sio.event
async def request_nlu(sid, data_str):
    begin = time.time()
    try:
        json_info = json.loads(data_str)
        query = json_info.get("query")
        trace_id = json_info.get("trace_id", "123")
        
        print(f"[*] Recv query: {query} with trace_id: {trace_id}")
        
        # 临时占位，第二步再接入 5 路异步并发以及显式 Fail-Safe 容灾机制
        response = {
            "query": query,
            "tarce_id": trace_id,
            "intent": "Unknown",
            "intent_id": "440",
            "function": "Unknown",
            "slots": {},
            "cost": time.time() - begin,
            "nlg": "抱歉，CARdle 系统骨架初始化已完成，并发核心业务逻辑正在装载中..."
        }
        
        # 异步私发推送给指定客户端链接
        await sio.emit("request_nlu", json.dumps(response, ensure_ascii=False), to=sid)
        
    except Exception as e:
        print(f"[-] Error processing request: {e}")
