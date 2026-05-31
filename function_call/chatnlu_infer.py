import uvicorn
import os
import sys
import json
import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel

# 确保能导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm_async, IS_MOCK
from prompts import NLU_SYSTEM_PROMPT
from utils.logger import session

app = FastAPI(title="CARdle 车机 NLU 意图识别与槽位提取服务", version="2.0.0")

INTENT_URL = os.getenv("NLU_INTENT_URL", "http://127.0.0.1:8016/intent-server/v1")
SLOT_INTENT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset", "slot_intent.json")

# 预加载 Schema 配置
with open(SLOT_INTENT_FILE, "r", encoding="utf-8") as f:
    ALL_SCHEMAS = json.load(f)

class NLURequest(BaseModel):
    query: str
    trace_id: str = "unknown"
    history: list = []

async def get_top5_intents(query: str):
    """向本地意图小模型 (Port 8016) 发起召回请求"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(INTENT_URL, json={"query": query})
            return resp.json().get("intents", [])
    except Exception as e:
        print(f"[NLU Funnel] 召回模型请求失败, 退化为全量大模型精排模式 (牺牲 Token 换取准确率): {e}")
        # 直接把 JSON 里的所有意图都当成候选集丢给大模型
        fallback_list = []
        for intent_name in ALL_SCHEMAS.keys():
            fallback_list.append({"id": "0", "name": intent_name})
        return fallback_list

@app.post("/chatnlu/v1")
async def chatnlu_infer(req: NLURequest, request: Request):
    session.trace_id = req.trace_id if req.trace_id != "unknown" else request.headers.get("X-Trace-Id", "unknown")
    print(f"[NLU Service] 收到 NLU 解析请求: '{req.query}' | TraceID: {session.trace_id}")
    query = req.query.strip()
    
    # === 分层漏斗核心：1. 粗排召回 ===
    top5_list = await get_top5_intents(query)
    
    # === 2. 动态拼装 Schema ===
    schema_descriptions = []
    valid_intents = []
    
    for i, item in enumerate(top5_list):
        intent_name = item["name"]
        valid_intents.append(intent_name)
        schema = ALL_SCHEMAS.get(intent_name, {})
        
        desc = f"{i+1}. `{intent_name}`"
        if isinstance(schema, dict) and schema:
            slots_info = []
            for slot_name, slot_props in schema.items():
                slots_info.append(f"'{slot_name}'")
            if slots_info:
                desc += f" (需要提取参数: {', '.join(slots_info)})"
            else:
                desc += " (无参数)"
        else:
            desc += " (无参数)"
        schema_descriptions.append(desc)
    
    # 增加兜底 Unknown
    schema_descriptions.append(f"{len(top5_list)+1}. `Unknown` (如果上述意图都不符合，请输出此项。无参数)")
    valid_intents.append("Unknown")
    
    candidates_str = "\n".join(schema_descriptions)
    
    # 意图识别与槽位提取提示词
    system_prompt = f"""{NLU_SYSTEM_PROMPT}
你是一个车载 NLU 意图提取专家。请从用户指令中提取车控意图和参数槽位。

通过本地模型的初步筛选，我们为您提供了最有可能的候选意图。
请只在以下候选函数中选择：
{candidates_str}

请仅以 JSON 格式输出，不要包含 markdown 标记或任何解释。格式如下：
{{
  "intent": "这里填你选择的函数名",
  "intent_id": "这里留空或随意填",
  "function": "同intent字段",
  "slots": {{
      // 提取出的具体参数字典
  }}
}}"""
    
    history_text = ""
    if req.history:
        history_text = "【近期对话历史】：\n" + json.dumps(req.history[-2:], ensure_ascii=False) + "\n\n"
        
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{history_text}用户指令: '{query}'"}
    ]
    
    try:
        if IS_MOCK:
            print(f"[NLU Funnel] Mock 模式已开启，为了漏斗测试，这里强制调用真实LLM进行解析。")
        
        # === 3. LLM 精排与槽位提取 ===
        print(f"[NLU Funnel] 正在提交给大模型进行精排，候选集: {valid_intents}")
        llm_resp = await call_llm_async(messages, temperature=0.1)
        
        # 清理可能存在的 markdown 标签
        llm_resp = llm_resp.strip()
        if llm_resp.startswith("```json"):
            llm_resp = llm_resp[7:]
        if llm_resp.endswith("```"):
            llm_resp = llm_resp[:-3]
        llm_resp = llm_resp.strip()
            
        result_json = json.loads(llm_resp)
        
        # 兼容 function 字段
        if "function" not in result_json and "intent" in result_json:
            result_json["function"] = result_json["intent"]
            
        print(f"[NLU Funnel] 大模型解析结果: {result_json}")
        
        # 保障大模型没有胡乱编造函数名
        if result_json.get("function") not in valid_intents:
            print(f"[WARN] 大模型输出了不在候选集中的意图 {result_json.get('function')}，强制降级为 Unknown")
            result_json["function"] = "Unknown"
            result_json["intent"] = "Unknown"
            
        return result_json
        
    except Exception as e:
        print(f"[ERR] NLU 提取失败: {e}")
        return {
            "intent": "Unknown",
            "intent_id": "440",
            "function": "Unknown",
            "slots": {},
            "error": str(e)
        }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8015)
