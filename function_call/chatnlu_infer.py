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
1. `set_ac_temperature` (调温): 参数 `temperature` (如 24度)
2. `open_window` (开窗): 无参数
3. `close_window` (关窗): 无参数
4. `navigate_to` (导航): 参数 `destination` (如 天安门)
5. `play_music` (放歌): 参数 `song` (歌名), `singer` (歌手名)
6. `Unknown` (未知或未指明具体部件): 无参数

请仅以 JSON 格式输出，不要包含 markdown 标记或任何解释。格式如下：
{{
  "intent": "意图名称",
  "intent_id": "意图编号(1001-1005，Unknown为440)",
  "function": "函数名(如 set_ac_temperature, Unknown)",
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
                intent = "set_ac_temperature"
                intent_id = "1001"
                function = "set_ac_temperature"
                if "24" in query:
                    slots["temperature"] = "24度"
                elif "高" in query:
                    slots["adjust"] = "up"
            elif "窗" in query:
                if "关" in query:
                    intent = "close_window"
                    intent_id = "1003"
                    function = "close_window"
                else:
                    intent = "open_window"
                    intent_id = "1002"
                    function = "open_window"
            elif "导航" in query or "去" in query:
                intent = "navigate_to"
                intent_id = "1004"
                function = "navigate_to"
                if "天安门" in query:
                    slots["destination"] = "天安门"
            
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
