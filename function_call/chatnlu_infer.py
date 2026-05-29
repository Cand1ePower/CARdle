import uvicorn
import os
import sys
import json
from fastapi import FastAPI
from pydantic import BaseModel

# 确保能导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm_async, IS_MOCK
from prompts import NLU_SYSTEM_PROMPT

app = FastAPI(title="CARdle 车机 NLU 意图识别与槽位提取服务", version="2.0.0")

class NLURequest(BaseModel):
    query: str

@app.post("/chatnlu/v1")
async def chatnlu_infer(req: NLURequest):
    print(f"[NLU Service] 收到 NLU 解析请求: '{req.query}'")
    query = req.query.strip()
    
    # 意图识别与槽位提取提示词
    system_prompt = f"""{NLU_SYSTEM_PROMPT}
你是一个车载 NLU 意图提取专家。请从用户指令中提取车控意图和参数槽位。

目前支持的控制函数：
1. `set_ac_temperature` (空调温度控制): 参数 `temperature` (如 24度), `adjust` (up/down)
2. `open_window` (开窗): 无参数
3. `close_window` (关窗): 无参数
4. `set_volume` (音量调节): 参数 `level` (具体数值或 up/down)
5. `navigate_to` (导航到某地): 参数 `destination` (目的地名称)
6. `maps_weather` (天气查询): 参数 `city` (城市名), `date` (日期, 格式YYYY-MM-DD, 可选)
7. `maps_text_search` (地点搜索/附近搜索): 参数 `keywords` (搜索关键词), `city` (城市, 可选)
8. `maps_direction_driving` (驾车路线规划): 参数 `origin` (起点), `destination` (终点)
9. `Unknown` (未知或未指明具体部件): 无参数

请仅以 JSON 格式输出，不要包含 markdown 标记或任何解释。格式如下：
{{
  "intent": "意图名称",
  "intent_id": "意图编号(1001-1008，Unknown为440)",
  "function": "函数名(如 set_ac_temperature, maps_weather, Unknown)",
  "slots": {{}}
}}"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"用户指令: '{query}'"}
    ]
    
    try:
        if IS_MOCK:
            # 自动化 Mock 以提高响应速度并排除网络波动
            slots = {}
            intent = "Unknown"
            intent_id = "440"
            function = "Unknown"
            
            if "空调" in query or "温度" in query:
                function = "set_ac_temperature"
                intent = "set_ac_temperature"
                intent_id = "1001"
                if "24" in query:
                    slots["temperature"] = "24度"
                elif "高" in query:
                    slots["adjust"] = "up"
                elif "低" in query:
                    slots["adjust"] = "down"
                elif "打开" in query or "开" in query:
                    pass  # 仅开启空调，无额外 slot
            elif "窗" in query:
                if "关" in query:
                    intent = "close_window"
                    intent_id = "1003"
                    function = "close_window"
                else:
                    intent = "open_window"
                    intent_id = "1002"
                    function = "open_window"
            elif "音量" in query or "声音" in query:
                intent = "set_volume"
                intent_id = "1004"
                function = "set_volume"
                if "大" in query or "高" in query:
                    slots["level"] = "up"
                elif "小" in query or "低" in query:
                    slots["level"] = "down"
            elif "天气" in query:
                intent = "maps_weather"
                intent_id = "1005"
                function = "maps_weather"
                # 简单提取城市名
                for city_name in ["北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "重庆", "西安"]:
                    if city_name in query:
                        slots["city"] = city_name
                        break
                if "city" not in slots:
                    slots["city"] = "北京"  # 默认
            elif "导航" in query or "去" in query:
                intent = "navigate_to"
                intent_id = "1006"
                function = "navigate_to"
                # 提取目的地：去掉动词后的内容
                dest = query
                for prefix in ["导航到", "导航去", "我要去", "带我去", "去"]:
                    if prefix in dest:
                        dest = dest.split(prefix, 1)[-1].strip()
                        break
                if dest:
                    slots["destination"] = dest
            elif "搜" in query or "附近" in query or "找" in query or "哪里" in query:
                intent = "maps_text_search"
                intent_id = "1007"
                function = "maps_text_search"
                # 提取关键词
                kw = query
                for prefix in ["帮我搜", "搜索", "搜一下", "搜", "附近的", "附近有", "找一下", "哪里有"]:
                    if prefix in kw:
                        kw = kw.split(prefix, 1)[-1].strip()
                        break
                slots["keywords"] = kw if kw else query
            
            result_dict = {
                "intent": intent,
                "intent_id": intent_id,
                "function": function,
                "slots": slots
            }
        else:
            raw_reply = await call_llm_async(messages, temperature=0.1)
            # 提取 JSON 串
            raw_reply = raw_reply.strip()
            if raw_reply.startswith("```json"):
                raw_reply = raw_reply[7:]
            if raw_reply.endswith("```"):
                raw_reply = raw_reply[:-3]
            raw_reply = raw_reply.strip()
            result_dict = json.loads(raw_reply)
            
        print(f"  [OK] NLU 提取成功: {result_dict}")
        return result_dict
    except Exception as e:
        print(f"  [ERR] NLU 提取失败: {e}")
        return {
            "intent": "Unknown",
            "intent_id": "440",
            "function": "Unknown",
            "slots": {},
            "error": str(e)
        }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8015)
