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

    # 别名映射：支持老版 439 意图 与 新版 102 意图
    "Query_Weather":          maps_weather,
    "Query_Timely_Weather":   maps_weather,
    "Go_POI":                 maps_direction_driving,
    "Navigation_Location_Query": maps_direction_driving,
    
    # 车辆硬件与控制
    "Vehicle_Hardware_Control": open_window,
    "Open_Window":            open_window,
    "Close_Window":           close_window,
    "Set_Air_Condition_Temperature": set_ac_temperature,
    "Set_Sound_Volume":       set_volume,
    "Check_Car_Condition":    get_vehicle_status,
    "Vehicle_Status_Query":   get_vehicle_status,

    # Group 3 各种 POI 场所别名映射 -> maps_text_search
    "Dining_Places":          maps_text_search,
    "Restaurants":            maps_text_search,
    "Chinese_Restaurants":    maps_text_search,
    "Fast_Food_Shops":        maps_text_search,
    "Hotpot_Shops":           maps_text_search,
    "Barbecue_Shops":         maps_text_search,
    "Teahouses":              maps_text_search,
    "Bars":                   maps_text_search,
    "Drink_Shops":            maps_text_search,
    "Snack_Streets":          maps_text_search,
    "Night_Markets":          maps_text_search,
    "Bakeries_Dessert_Shops": maps_text_search,
    "Parks":                  maps_text_search,
    "Arcades":                maps_text_search,
    "Board_Game_Shops":       maps_text_search,
    "LARP_Game_Shops":        maps_text_search,
    "Chess_Card_Rooms":       maps_text_search,
    "Bookstores":             maps_text_search,
    "Shopping_Malls":         maps_text_search,
    "Ice_Skating_Rinks":      maps_text_search,
    "Ski_Resorts":            maps_text_search,
    "Cinemas":                maps_text_search,
    "KTV":                    maps_text_search,
    "DIY_Workshops":          maps_text_search,
    "Amusement_Parks":        maps_text_search,
    "Zoos":                   maps_text_search,
    "Botanical_Gardens":      maps_text_search,
    "Aquariums":              maps_text_search,
    "Museums":                maps_text_search,
    "Art_Galleries":          maps_text_search,
    "Tourist_Attractions":    maps_text_search,
    "Agritainment_Resorts":   maps_text_search,
    "Hot_Springs_Spa_Centers":maps_text_search,
    "Sports_Stadiums":        maps_text_search,
}

# 槽位字段名映射：NLU 输出的 slot 名 → 工具函数的参数名
SLOT_MAPPINGS = {
    "navigate_to": {"destination": "destination", "origin": "origin"},
    "maps_weather": {"city": "city", "date": "date"},
    "Query_Weather": {"location": "city", "date": "date"},
    "Query_Timely_Weather": {"location": "city", "date": "date"},
    
    "maps_text_search": {"keywords": "keywords", "city": "city"},
    "maps_direction_driving": {"origin": "origin", "destination": "destination"},
    "Go_POI": {"POI": "destination", "City": "city"},
    "Navigation_Location_Query": {"POI": "destination", "City": "city"},

    "set_ac_temperature": {"temperature": "temperature", "adjust": "adjust"},
    "set_volume": {"level": "level"},
    
    # 各种 POI 槽位映射
    "Dining_Places": {"POI": "keywords", "City": "city"},
    "Restaurants": {"POI": "keywords", "City": "city"},
    "Chinese_Restaurants": {"POI": "keywords", "City": "city"},
    "Fast_Food_Shops": {"POI": "keywords", "City": "city"},
    "Hotpot_Shops": {"POI": "keywords", "City": "city"},
    "Barbecue_Shops": {"POI": "keywords", "City": "city"},
    "Teahouses": {"POI": "keywords", "City": "city"},
    "Bars": {"POI": "keywords", "City": "city"},
    "Drink_Shops": {"POI": "keywords", "City": "city"},
    "Snack_Streets": {"POI": "keywords", "City": "city"},
    "Night_Markets": {"POI": "keywords", "City": "city"},
    "Bakeries_Dessert_Shops": {"POI": "keywords", "City": "city"},
    "Parks": {"POI": "keywords", "City": "city"},
    "Arcades": {"POI": "keywords", "City": "city"},
    "Board_Game_Shops": {"POI": "keywords", "City": "city"},
    "LARP_Game_Shops": {"POI": "keywords", "City": "city"},
    "Chess_Card_Rooms": {"POI": "keywords", "City": "city"},
    "Bookstores": {"POI": "keywords", "City": "city"},
    "Shopping_Malls": {"POI": "keywords", "City": "city"},
    "Ice_Skating_Rinks": {"POI": "keywords", "City": "city"},
    "Ski_Resorts": {"POI": "keywords", "City": "city"},
    "Cinemas": {"POI": "keywords", "City": "city"},
    "KTV": {"POI": "keywords", "City": "city"},
    "DIY_Workshops": {"POI": "keywords", "City": "city"},
    "Amusement_Parks": {"POI": "keywords", "City": "city"},
    "Zoos": {"POI": "keywords", "City": "city"},
    "Botanical_Gardens": {"POI": "keywords", "City": "city"},
    "Aquariums": {"POI": "keywords", "City": "city"},
    "Museums": {"POI": "keywords", "City": "city"},
    "Art_Galleries": {"POI": "keywords", "City": "city"},
    "Tourist_Attractions": {"POI": "keywords", "City": "city"},
    "Agritainment_Resorts": {"POI": "keywords", "City": "city"},
    "Hot_Springs_Spa_Centers": {"POI": "keywords", "City": "city"},
    "Sports_Stadiums": {"POI": "keywords", "City": "city"},
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
