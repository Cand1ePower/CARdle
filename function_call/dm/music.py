import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from client.nlg import request_nlg_async
from utils import logger

async def process(func_name: str, query: str, slots: dict):
    """
    车载音乐与多媒体播放业务领域 DM 对话管理处理器
    """
    logger.info(f"[DM Music] 开始处理音乐业务 func={func_name} slots={slots}")
    
    # 模拟高保真座舱音乐检索及推送服务
    song = slots.get("Song", slots.get("Name", "推荐流行金曲"))
    singer = slots.get("Singer", slots.get("Person", "精选群星"))
    genre = slots.get("genre", "流行")
    
    tool_response = {
        "status": "播放成功",
        "歌曲": song,
        "歌手": singer,
        "流派": genre,
        "播放地址": f"https://music.cardle.com/play/stream/{abs(hash(song)) % 1000000}.mp3"
    }
    
    tool_response_str = json.dumps(tool_response, ensure_ascii=False)
    logger.info(f"[DM Music] 模拟音乐服务返回: {tool_response_str}")
    
    # 大模型 NLG 话术润色
    nlg_text = await request_nlg_async(query, tool_response_str)
    
    return tool_response, nlg_text
