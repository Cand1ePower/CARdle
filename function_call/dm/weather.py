import json
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from sinan import Sinan
except ImportError:
    Sinan = None

from mcp_core.tool_dispatcher import dispatch_tool
from client.nlg import request_nlg_async
from utils import logger

async def process(func_name: str, query: str, slots: dict):
    """
    天气业务领域 DM 对话管理处理器
    """
    logger.info(f"[DM Weather] 开始处理天气业务 func={func_name} slots={slots}")
    
    # 1. 槽位清洗与时间自然语言解析规整 (Sinan)
    date_str = slots.get("date", "")
    if date_str and Sinan:
        try:
            date_parsed = Sinan(date_str).parse()
            if "datetime" in date_parsed:
                # 转换为标准 YYYY-MM-DD
                slots["date"] = date_parsed["datetime"][0].split(" ")[0]
                logger.info(f"[DM Weather] Sinan 成功解析时间 '{date_str}' -> '{slots['date']}'")
        except Exception as e:
            logger.warn(f"[DM Weather] Sinan 解析时间异常: {e}")
            
    if not slots.get("date"):
        slots["date"] = datetime.now().strftime("%Y-%m-%d")
        
    # 补全默认城市
    if not slots.get("location") and not slots.get("city"):
        slots["location"] = "北京"
        slots["city"] = "北京"
        
    # 2. 调用地图 MCP 服务 (通过别名路由至 maps_weather)
    tool_response_str = await dispatch_tool(func_name, slots)
    tool_response = json.loads(tool_response_str) if tool_response_str else {}
    
    # 3. 大模型 NLG 个性化润色
    nlg_text = await request_nlg_async(query, tool_response_str)
    
    return tool_response, nlg_text
