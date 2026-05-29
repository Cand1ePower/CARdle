"""
CARdle MCP 工具统一分发中心
根据 NLU 返回的 function 名称，自动路由到对应的工具函数执行。
"""

import os
import sys
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import logger

from mcp_core.amap_tools import maps_weather, maps_text_search, maps_geo, maps_direction_driving
from mcp_core.vehicle_tools import set_ac_temperature, open_window, close_window, set_volume, get_vehicle_status

# 工具注册表：function 名称 → (异步函数, 槽位参数映射说明)
TOOL_REGISTRY = {
    # 高德地图工具
    "maps_weather":           maps_weather,
    "maps_text_search":       maps_text_search,
    "maps_geo":               maps_geo,
    "maps_direction_driving": maps_direction_driving,

    # 车辆本地控制
    "set_ac_temperature":     set_ac_temperature,
    "open_window":            open_window,
    "close_window":           close_window,
    "set_volume":             set_volume,
    "get_vehicle_status":     get_vehicle_status,

    # 导航（NLU 可能返回 navigate_to，映射为驾车路线规划）
    "navigate_to":            maps_direction_driving,
}

# 槽位字段名映射：NLU 输出的 slot 名 → 工具函数的参数名
SLOT_MAPPINGS = {
    "navigate_to": {"destination": "destination", "origin": "origin"},
    "maps_weather": {"city": "city", "date": "date"},
    "maps_text_search": {"keywords": "keywords", "city": "city"},
    "maps_direction_driving": {"origin": "origin", "destination": "destination"},
    "set_ac_temperature": {"temperature": "temperature", "adjust": "adjust"},
    "set_volume": {"level": "level"},
}


async def dispatch_tool(function: str, slots: dict) -> str:
    """
    根据 NLU 解析出的 function 名称和 slots 参数，路由到对应的工具函数执行。

    Args:
        function: NLU 返回的 function 名称（如 "maps_weather"、"set_ac_temperature"）
        slots:    NLU 提取的槽位字典（如 {"city": "北京", "date": "2026-05-29"}）

    Returns:
        工具执行结果的文本描述（JSON 字符串），供 NLG 润色使用
    """
    if function not in TOOL_REGISTRY:
        logger.info(f"[Dispatcher] 未注册的工具: {function}")
        return ""

    tool_func = TOOL_REGISTRY[function]

    # 根据映射表转换 slot 参数名
    mapping = SLOT_MAPPINGS.get(function, {})
    kwargs = {}
    for slot_key, slot_val in slots.items():
        param_name = mapping.get(slot_key, slot_key)
        kwargs[param_name] = slot_val

    # 特殊处理：navigate_to 需要默认起点
    if function == "navigate_to" and "origin" not in kwargs:
        kwargs["origin"] = "当前位置"

    logger.info(f"[Dispatcher] 调用工具 {function}({kwargs})")

    try:
        result = await tool_func(**kwargs)
        result_str = json.dumps(result, ensure_ascii=False)
        logger.info(f"[Dispatcher] 工具返回: {result_str[:200]}")
        return result_str
    except Exception as e:
        logger.error(f"[Dispatcher] 工具执行异常: {e}")
        return json.dumps({"error": f"工具执行失败: {str(e)}"}, ensure_ascii=False)
