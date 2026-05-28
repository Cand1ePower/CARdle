"""
CARdle NLG 自然语言生成模块（非 FastAPI 服务，被 server.py 直接 import 调用）

功能：
  MCP 工具（高德地图、天气查询、车辆控制等）执行完毕并返回原始 JSON/文本数据后，
  通过大模型将机器化结构数据润色为符合车载场景的自然语言播报文本。

核心设计：
  - 接受 (query, tool_response) 两个参数
  - 调用 LLM 生成人性化播报文本
  - tool_response 为空时直接跳过，返回空字符串

Phase 6 (MCP 工具接入) 后，此模块将被任务分支全面使用。
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm_async
from prompts import NLG_PROMPT
from utils import logger

MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT", "doubao-pro-4k")
TIMEOUT = 10.0


async def request_nlg_async(query: str, tool_response: str) -> str:
    """
    将工具返回数据润色为车载语音播报文本。

    Args:
        query:         用户原始指令，如 "今天天气怎么样"
        tool_response: 工具 API 原始返回，如 "城市：北京 天气：阴 温度：21度..."

    Returns:
        润色后的自然语言文本，如 "今天北京天气有点阴，气温21度，出门建议带件外套哦~"
        若 tool_response 为空则返回 ""（由调用方决定兜底逻辑）
    """
    if not tool_response:
        logger.info("[NLG] tool_response 为空，跳过润色")
        return ""

    try:
        messages = [
            {"role": "user", "content": NLG_PROMPT.format(query, tool_response)}
        ]
        answer = await call_llm_async(messages, temperature=0.3)
        logger.info(f"[NLG] result='{answer}'")
        return answer

    except Exception as e:
        logger.error(f"[NLG] 调用失败: {e}")
        return ""


if __name__ == "__main__":
    import asyncio

    async def _test():
        q = "今天天气怎么样"
        tool_resp = "城市：北京市\n天气：阴\n温度：21度\n风向：东北\n风力：1-3级"
        res = await request_nlg_async(q, tool_resp)
        print(res)

    asyncio.run(_test())
