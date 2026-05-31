"""
CARdle NLU 薄封装客户端（非 FastAPI 服务，被 server.py 直接 import 调用）

核心设计：
  - 本身不包含任何业务逻辑
  - 只负责将 query/trace_id 透传给 chatnlu_infer 推理服务
  - 原封不动地返回 NLU 服务的 JSON 响应
"""

import os
import sys
import httpx

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import logger

try:
    from langfuse import observe
except ImportError:
    def observe(*args, **kwargs):
        return lambda f: f

NLU_URL = os.getenv("CHATNLU_INFER_URL", "http://127.0.0.1:8015/chatnlu/v1")


from typing import List, Dict, Any

@observe(as_type="span", name="Local_NLU_Infer")
async def request_nlu_async(query: str, trace_id: str = "", enable_dm: bool = True, history: List[Dict[str, Any]] = None) -> dict:
    """
    向 chatnlu_infer 推理服务（默认端口 8015）发起 NLU 解析请求。
    返回结构化的意图识别与槽位提取结果。
    """
    payload = {
        "query": query,
        "trace_id": trace_id,
        "enable_dm": enable_dm,
        "history": history or []
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(NLU_URL, json=payload)
            res = response.json()
            logger.info(f"[NLU] result: {res}")
            return res
    except Exception as e:
        err_msg = str(e)
        if 'response' in locals() and hasattr(response, 'text'):
            err_msg += f" | 原始响应: {response.text}"
        logger.error(f"[NLU] 调用失败: {err_msg}")
        return {
            "intent": "Unknown",
            "intent_id": "440",
            "function": "Unknown",
            "slots": {}
        }


if __name__ == '__main__':
    import asyncio

    async def _test():
        while True:
            q = input("Input: ")
            res = await request_nlu_async(q, "test_123")
            print(res)

    asyncio.run(_test())
