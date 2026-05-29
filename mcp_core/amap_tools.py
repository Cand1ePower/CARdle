"""
CARdle 高德地图异步工具集
提供天气查询、POI 搜索、地理编码、驾车路线规划等车载高频能力。
所有函数均为纯异步（httpx），可被 tool_dispatcher 直接调用。
"""

import os
import sys
import json
from typing import Any, Dict, Optional

import httpx

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import logger

# 优先从环境变量读取；兜底使用 config.ini 中加载的值
_cfg_key = os.getenv("AMAP_MAPS_API_KEY", "")
if not _cfg_key or _cfg_key == "xxxx":
    # 尝试从 config 加载
    from utils.llm_client import load_config
    load_config()
    _cfg_key = os.getenv("AMAP_MAPS_API_KEY", "")

AMAP_KEY = _cfg_key
AMAP_BASE = "https://restapi.amap.com"
TIMEOUT = 8.0

if not AMAP_KEY or AMAP_KEY == "xxxx":
    logger.info("[AMap] 高德 API Key 未配置，地图类工具将返回降级提示。请在 config/config.ini 中设置 AMAP_MAPS_API_KEY。")


async def maps_weather(city: str, date: str = "") -> Dict[str, Any]:
    """
    查询指定城市的天气预报。

    Args:
        city: 城市名称或 adcode（如 "北京" 或 "110000"）
        date: 可选，指定日期（格式 YYYY-MM-DD），为空则返回全部预报
    Returns:
        格式化的天气数据字典
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{AMAP_BASE}/v3/weather/weatherInfo",
                params={"key": AMAP_KEY, "city": city, "extensions": "all"}
            )
            data = resp.json()

        if data.get("status") != "1":
            return {"error": f"天气查询失败: {data.get('info', 'unknown')}"}

        forecasts = data.get("forecasts", [])
        if not forecasts:
            return {"error": "未获取到天气预报数据"}

        result = {"城市": forecasts[0]["city"]}

        # 如果指定了日期，只返回该日
        for cast in forecasts[0].get("casts", []):
            if date and cast["date"] != date:
                continue
            result.update({
                "日期": cast["date"],
                "天气": cast.get("dayweather", ""),
                "温度": f"{cast.get('nighttemp', '')}~{cast.get('daytemp', '')}度",
                "风向": cast.get("daywind", ""),
                "风力": cast.get("daypower", "") + "级",
            })
            if date:
                break

        # 如果没指定日期且未匹配到，取第一天
        if "日期" not in result and forecasts[0].get("casts"):
            cast = forecasts[0]["casts"][0]
            result.update({
                "日期": cast["date"],
                "天气": cast.get("dayweather", ""),
                "温度": f"{cast.get('nighttemp', '')}~{cast.get('daytemp', '')}度",
                "风向": cast.get("daywind", ""),
                "风力": cast.get("daypower", "") + "级",
            })

        logger.info(f"[AMap Weather] result={result}")
        return result

    except Exception as e:
        logger.error(f"[AMap Weather] error: {e}")
        return {"error": f"天气查询异常: {str(e)}"}


async def maps_text_search(keywords: str, city: str = "", top_k: int = 3) -> Dict[str, Any]:
    """
    POI 关键词搜索（如 "附近加油站"、"星巴克"）。

    Args:
        keywords: 搜索关键词
        city: 可选，限定城市
        top_k: 返回前几条结果
    Returns:
        包含 POI 列表的字典
    """
    try:
        params = {"key": AMAP_KEY, "keywords": keywords}
        if city:
            params["city"] = city
            params["citylimit"] = "true"

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{AMAP_BASE}/v3/place/text", params=params)
            data = resp.json()

        if data.get("status") != "1":
            return {"error": f"POI 搜索失败: {data.get('info', 'unknown')}"}

        pois = []
        for poi in data.get("pois", [])[:top_k]:
            pois.append({
                "名称": poi.get("name"),
                "地址": poi.get("address"),
                "电话": poi.get("tel", ""),
                "坐标": poi.get("location", ""),
            })

        logger.info(f"[AMap Search] keywords='{keywords}' found={len(pois)}")
        return {"搜索结果": pois} if pois else {"error": "未找到相关地点"}

    except Exception as e:
        logger.error(f"[AMap Search] error: {e}")
        return {"error": f"POI 搜索异常: {str(e)}"}


async def maps_geo(address: str, city: Optional[str] = None) -> Dict[str, Any]:
    """
    地理编码：将地址转换为经纬度坐标。

    Args:
        address: 结构化地址或地标名称
        city: 可选，辅助定位城市
    Returns:
        包含经纬度的字典
    """
    try:
        params = {"key": AMAP_KEY, "address": address}
        if city:
            params["city"] = city

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{AMAP_BASE}/v3/geocode/geo", params=params)
            data = resp.json()

        if data.get("status") != "1":
            return {"error": f"地理编码失败: {data.get('info', 'unknown')}"}

        geocodes = data.get("geocodes", [])
        if not geocodes:
            return {"error": f"未找到 '{address}' 的坐标信息"}

        geo = geocodes[0]
        result = {
            "地点": geo.get("formatted_address", address),
            "坐标": geo.get("location", ""),
            "省份": geo.get("province", ""),
            "城市": geo.get("city", ""),
            "区县": geo.get("district", ""),
        }
        logger.info(f"[AMap Geo] address='{address}' -> {result.get('坐标')}")
        return result

    except Exception as e:
        logger.error(f"[AMap Geo] error: {e}")
        return {"error": f"地理编码异常: {str(e)}"}


async def maps_direction_driving(origin: str, destination: str) -> Dict[str, Any]:
    """
    驾车路线规划（支持地址名称输入，内部自动地理编码）。

    Args:
        origin: 起点地址或名称（如 "天安门"）
        destination: 终点地址或名称
    Returns:
        路线摘要信息
    """
    try:
        # 先做地理编码
        origin_geo = await maps_geo(origin)
        if "error" in origin_geo:
            return {"error": f"起点解析失败: {origin_geo['error']}"}

        dest_geo = await maps_geo(destination)
        if "error" in dest_geo:
            return {"error": f"终点解析失败: {dest_geo['error']}"}

        origin_loc = origin_geo["坐标"]
        dest_loc = dest_geo["坐标"]

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{AMAP_BASE}/v3/direction/driving",
                params={"key": AMAP_KEY, "origin": origin_loc, "destination": dest_loc}
            )
            data = resp.json()

        if data.get("status") != "1":
            return {"error": f"路线规划失败: {data.get('info', 'unknown')}"}

        paths = data.get("route", {}).get("paths", [])
        if not paths:
            return {"error": "未规划出有效路线"}

        path = paths[0]
        distance_km = round(int(path.get("distance", 0)) / 1000, 1)
        duration_min = round(int(path.get("duration", 0)) / 60)

        # 提取关键导航步骤（前 5 步）
        steps_summary = []
        for step in path.get("steps", [])[:5]:
            steps_summary.append(step.get("instruction", ""))

        result = {
            "起点": origin,
            "终点": destination,
            "总距离": f"{distance_km}公里",
            "预计耗时": f"{duration_min}分钟",
            "导航提示": "；".join(steps_summary),
        }
        logger.info(f"[AMap Driving] {origin} -> {destination}: {distance_km}km, {duration_min}min")
        return result

    except Exception as e:
        logger.error(f"[AMap Driving] error: {e}")
        return {"error": f"路线规划异常: {str(e)}"}
