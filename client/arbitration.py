import uvicorn
import os
import sys
import json
import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List, Dict, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import API_KEY, BASE_URL, IS_MOCK
from prompts import ARBITRAION_SYSTEM_PROMPT
from utils import logger
from utils.logger import session

app = FastAPI(title="CARdle 云端意图仲裁服务", version="2.0.0")

MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT", "doubao-pro-4k")
TIMEOUT = 10.0  # 增加超时时间，因为要输出完整的 JSON


class CandidateIntent(BaseModel):
    intent: str
    slots: Dict[str, Any]

class ArbitrationRequest(BaseModel):
    query: str
    history: List[Dict[str, Any]] = []
    candidates: List[CandidateIntent]


@app.post("/intent-server/v1")
async def arbitrate(req: ArbitrationRequest, request: Request):
    session.trace_id = request.headers.get("X-Trace-Id", "unknown")
    logger.info(f"[Arbitration] query='{req.query}' | candidates_count={len(req.candidates)} | TraceID: {session.trace_id}")

    # ── Mock 模式 ──
    if IS_MOCK:
        if req.candidates:
            chosen = req.candidates[0].dict()
        else:
            chosen = {"intent": "Unknown", "slots": {}}
        logger.info(f"[Arbitration] Mock result={chosen}")
        return {"intent": chosen.get("intent"), "slots": chosen.get("slots"), "degraded": False}

    # ── 真实 API：让云端大模型从候选集中选一个最优的并输出 JSON ──
    headers = {
        "Content-Type": "application/json",
        "Authorization": API_KEY if API_KEY.startswith("Bearer") else f"Bearer {API_KEY}"
    }
    
    # 构造 Prompt 的上下文
    history_text = json.dumps(req.history, ensure_ascii=False)
    if req.candidates:
        candidates_text = json.dumps([c.model_dump() if hasattr(c, 'model_dump') else c.dict() for c in req.candidates], ensure_ascii=False)
    else:
        # 如果 NLU 没有给出候选（如 Unknown），给大模型一份所有意图的名称列表供其参考
        try:
            slot_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset", "slot_intent.json")
            with open(slot_file, "r", encoding="utf-8") as f:
                all_intents = list(json.load(f).keys())
            candidates_text = f"NLU未提供候选，请从以下标准函数名中推理(不要随意编造):\n{', '.join(all_intents)}"
        except:
            candidates_text = "[]"
            
    user_content = f"【对话历史】：\n{history_text}\n\n【最新指令】：\n{req.query}\n\n【候选意图集】：\n{candidates_text}"
    
    messages = [
        {"role": "system", "content": ARBITRAION_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]
    
    model_name = MODEL_ENDPOINT
    if "deepseek" in BASE_URL.lower() and "doubao" in model_name.lower():
        model_name = "deepseek-chat"

    body = {
        "model": model_name,
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.1,
        "stream": False,
        "response_format": {"type": "json_object"} if "deepseek" in model_name.lower() or "gpt" in model_name.lower() else None
    }
    
    # 清理不支持 response_format 的情况
    if body["response_format"] is None:
        del body["response_format"]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(BASE_URL, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            result_text = data["choices"][0]["message"]["content"]
            
            # 清理可能的 Markdown 标记
            result_text = result_text.strip()
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
                
            result_json = json.loads(result_text)
            logger.info(f"[Arbitration] LLM chose intent: {result_json}")
            
            return {
                "intent": result_json.get("intent", "Unknown"), 
                "slots": result_json.get("slots", {}), 
                "degraded": False
            }

    except Exception as e:
        logger.error(f"[Arbitration] API error: {e}")
        # 降级：直接取本地候选集里的第一个（置信度最高的）
        fallback_intent = req.candidates[0].dict() if req.candidates else {"intent": "Unknown", "slots": {}}
        return {"intent": fallback_intent.get("intent"), "slots": fallback_intent.get("slots"), "degraded": True}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8008)
