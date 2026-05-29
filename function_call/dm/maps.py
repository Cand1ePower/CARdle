import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_core.tool_dispatcher import dispatch_tool
from client.nlg import request_nlg_async
from utils import logger

async def process(func_name: str, query: str, slots: dict):
    """
    地图与高德导航业务领域 DM 对话管理处理器
    """
    logger.info(f"[DM Maps] 开始处理地图导航业务 func={func_name} slots={slots}")
    
    # 调用底层高德地图服务 (通过 tool_dispatcher 自动完成槽位适配与 API 请求)
    tool_response_str = await dispatch_tool(func_name, slots)
    tool_response = json.loads(tool_response_str) if tool_response_str else {}
    
    # 大模型 NLG 话术润色
    nlg_text = await request_nlg_async(query, tool_response_str)
    
    return tool_response, nlg_text
