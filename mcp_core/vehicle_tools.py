"""
CARdle 车辆本地控制工具集（Mock 模式）
模拟空调、车窗、音量等车辆硬件控制指令的执行与回执。
在真实车机环境中，这些函数将对接 CAN 总线或车辆 ECU 接口。
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import logger


# 模拟的车辆状态寄存器
_vehicle_state = {
    "ac_on": False,
    "ac_temperature": 24,
    "window_open": False,
    "volume": 50,
}


async def set_ac_temperature(temperature: str = "", adjust: str = "") -> dict:
    """
    设置空调温度或调节温度。

    Args:
        temperature: 目标温度值（如 "24度"、"26"）
        adjust: 调节方向（"up" 或 "down"）
    """
    current = _vehicle_state["ac_temperature"]

    if adjust == "up":
        _vehicle_state["ac_temperature"] = min(current + 2, 32)
        _vehicle_state["ac_on"] = True
        msg = f"已为您将空调温度从{current}度调高到{_vehicle_state['ac_temperature']}度"
    elif adjust == "down":
        _vehicle_state["ac_temperature"] = max(current - 2, 16)
        _vehicle_state["ac_on"] = True
        msg = f"已为您将空调温度从{current}度调低到{_vehicle_state['ac_temperature']}度"
    elif temperature:
        # 提取数字
        temp_val = "".join(c for c in str(temperature) if c.isdigit())
        if temp_val:
            temp_int = max(16, min(32, int(temp_val)))
            _vehicle_state["ac_temperature"] = temp_int
            _vehicle_state["ac_on"] = True
            msg = f"已为您将空调温度设置为{temp_int}度"
        else:
            msg = f"无法识别温度值 '{temperature}'，当前温度保持{current}度"
    else:
        # 仅打开空调
        _vehicle_state["ac_on"] = True
        msg = f"已为您打开空调，当前温度{current}度"

    logger.info(f"[Vehicle] AC: {msg}")
    return {"success": True, "message": msg, "当前温度": f"{_vehicle_state['ac_temperature']}度"}


async def open_window() -> dict:
    """打开车窗"""
    _vehicle_state["window_open"] = True
    msg = "已为您打开车窗"
    logger.info(f"[Vehicle] {msg}")
    return {"success": True, "message": msg}


async def close_window() -> dict:
    """关闭车窗"""
    _vehicle_state["window_open"] = False
    msg = "已为您关闭车窗"
    logger.info(f"[Vehicle] {msg}")
    return {"success": True, "message": msg}


async def set_volume(level: str = "") -> dict:
    """
    调节音量。

    Args:
        level: 目标音量（0-100）或调节方向 ("up"/"down")
    """
    current = _vehicle_state["volume"]

    if level in ("up", "大声", "调高"):
        _vehicle_state["volume"] = min(current + 10, 100)
        msg = f"音量已从{current}调高到{_vehicle_state['volume']}"
    elif level in ("down", "小声", "调低"):
        _vehicle_state["volume"] = max(current - 10, 0)
        msg = f"音量已从{current}调低到{_vehicle_state['volume']}"
    elif level:
        vol_val = "".join(c for c in str(level) if c.isdigit())
        if vol_val:
            _vehicle_state["volume"] = max(0, min(100, int(vol_val)))
            msg = f"音量已设置为{_vehicle_state['volume']}"
        else:
            msg = f"无法识别音量值 '{level}'，当前音量{current}"
    else:
        msg = f"当前音量{current}"

    logger.info(f"[Vehicle] Volume: {msg}")
    return {"success": True, "message": msg, "当前音量": _vehicle_state["volume"]}


async def get_vehicle_status() -> dict:
    """获取当前车辆状态摘要"""
    return {
        "空调状态": "开启" if _vehicle_state["ac_on"] else "关闭",
        "空调温度": f"{_vehicle_state['ac_temperature']}度",
        "车窗状态": "开启" if _vehicle_state["window_open"] else "关闭",
        "音量": _vehicle_state["volume"],
    }
