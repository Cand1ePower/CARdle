import asyncio
import json
import httpx
import socketio

async def main():
    print("[*] 阶段 1: 验证 FastAPI 运维健康接口...")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get("http://127.0.0.1:8000/health")
            print(f"[+] Health Check 状态码: {resp.status_code}, 响应内容: {resp.json()}")
        except Exception as e:
            print(f"[-] Health Check 失败，服务可能未正常启动: {e}")
            return

    print("\n[*] 阶段 2: 验证 Socket.IO 全双工长连接与骨架回包...")
    # 实例化异步 WebSocket 客户端
    sio = socketio.AsyncClient()

    @sio.event
    async def connect():
        print("[+] 成功与 CARdle 异步控制网关建立 WebSocket 握手！")

    @sio.event
    async def request_nlu(data):
        res = json.loads(data)
        print(f"[+] 收到车机下行骨架回包！")
        print(f"    - 输入文本: {res.get('query')}")
        print(f"    - 耗时统计: {res.get('cost'):.4f} 秒")
        print(f"    - 车机响应: {res.get('nlg')}")
        # 收到回包后优雅断开
        await sio.disconnect()

    try:
        # 连接到 ASGI 8000 端口
        await sio.connect("http://127.0.0.1:8000")
        
        # 构造上行数据包
        payload = {
            "query": "你好，我是特斯拉车主",
            "trace_id": "test_trace_001"
        }
        print("[*] 发送语音指令: '你好，我是特斯拉车主'")
        await sio.emit("request_nlu", json.dumps(payload, ensure_ascii=False))
        
        # 异步等待回包断开
        await sio.wait()
    except Exception as e:
        print(f"[-] Socket.IO 连接或测试失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
