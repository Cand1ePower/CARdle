"""
Phase 7: 测试本地意图/拒识模型推理以及 NLU 漏斗的连通性
"""
import sys
import os
import asyncio
import json
import httpx

# 上移寻找根目录
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.nlu import request_nlu_async

async def test_funnel():
    print("="*60)
    print("1. 测试 NLU 分层漏斗解析")
    print("="*60)
    
    query = "把驾驶模式改成自动驾驶"
    print(f"[*] 测试指令: {query}")
    
    res = await request_nlu_async(query, "trace_test_7")
    print("\n[+] 最终解析结果:")
    print(json.dumps(res, ensure_ascii=False, indent=2))

async def test_reject():
    print("\n" + "="*60)
    print("2. 测试安全拒识微服务 (8007)")
    print("="*60)
    
    queries = ["帮我把空调打开", "傻逼东西", "asdfasdfasdf"]
    
    async with httpx.AsyncClient() as client:
        for q in queries:
            try:
                resp = await client.post("http://127.0.0.1:8007/reject-server/v1", json={"query": q})
                print(f"Query: '{q}' -> {resp.json()}")
            except Exception as e:
                print(f"Query: '{q}' -> ERR: {e}")

async def main():
    await test_funnel()
    await test_reject()

if __name__ == "__main__":
    asyncio.run(main())
