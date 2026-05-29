import sys
import os
from typing import Text

# 保证能够导入当前包下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from function_call.dm import weather
from function_call.dm import maps
from function_call.dm import vehicle
from function_call.dm import music

PARSER_MAPPING = {
    "weather": weather,
    "maps": maps,
    "vehicle": vehicle,
    "music": music
}

class DMFactory:
    """
    智能座舱对话管理器工厂模式核心路由器
    """
    @staticmethod
    def get(name: Text):
        if name in PARSER_MAPPING:
            return PARSER_MAPPING[name].process
        return None

def get_domain_by_intent(intent_name: str) -> str:
    """
    根据 NLU 识别出的意图函数名称，自动归类并划分其所属的垂直业务领域
    """
    intent = intent_name.lower()
    if "weather" in intent:
        return "weather"
    elif any(x in intent for x in [
        "poi", "maps", "geo", "direction", "navigation", "dining", "restaurants", 
        "fast_food", "hotpot", "barbecue", "teahouses", "bars", "drink", "snack", 
        "night_markets", "bakeries", "parks", "arcades", "board_game", "larp", 
        "chess", "bookstores", "shopping", "cinemas", "ktv", "diy", "amusement", 
        "zoos", "botanical", "aquariums", "museums", "art_galleries", "tourist", 
        "agritainment", "spa", "sports"
    ]):
        return "maps"
    elif any(x in intent for x in ["music", "song", "radio", "audio", "timbre"]):
        return "music"
    else:
        # 默认归入车载车控域（如车窗、音量、空调）
        return "vehicle"
