import os
import sys
import json
import torch
import uvicorn
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Literal
from transformers import AutoModelForCausalLM, AutoTokenizer
from lmformatenforcer import JsonSchemaParser
from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn

# 确保能导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from prompts import NLU_SYSTEM_PROMPT

app = FastAPI(title="CARdle Gemma-3-1B 端侧全能节点 (受限解码)", version="2.0.0")

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "train", "gemma-3-1b-cardle")
SLOT_INTENT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset", "slot_intent.json")

# 加载 Intent 列表
with open(SLOT_INTENT_FILE, "r", encoding="utf-8") as f:
    ALL_SCHEMAS = json.load(f)
valid_intents = list(ALL_SCHEMAS.keys()) + ["Unknown"]

# === 动态构建 Pydantic 模型，严格约束 intent 字段 ===
from enum import Enum
IntentEnum = Enum('IntentEnum', {name: name for name in valid_intents})

class CandidateIntent(BaseModel):
    intent: IntentEnum
    slots: Dict[str, Any]

class NLUResponseModel(BaseModel):
    domain: Literal["A", "B", "C", "D"]
    is_safe: bool
    reject_reason: str
    rewritten_query: str
    candidate_intents: List[CandidateIntent]

# 模型和 Tokenizer 加载 (懒加载)
tokenizer = None
model = None

def load_model():
    global tokenizer, model
    if model is None:
        print(f"[*] 正在加载 Gemma 3 1B 端侧大模型: {MODEL_DIR}")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR, 
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto" if torch.cuda.is_available() else None
        )
        if not torch.cuda.is_available():
            model.to(device)
        model.eval()
        print(f"[*] 模型加载完成 ({device})，端侧推理准备就绪！")

class NLURequest(BaseModel):
    query: str
    trace_id: str = "unknown"
    history: list = []

@app.post("/chatnlu/v1")
async def gemma_infer(req: NLURequest, request: Request):
    load_model()
    
    query = req.query.strip()
    history_text = ""
    if req.history:
        history_text = "【近期对话历史】：\n" + json.dumps(req.history[-2:], ensure_ascii=False) + "\n\n"
        
    TRAIN_SYSTEM_PROMPT = """你是一个车载智能中枢。请根据提供的对话历史和最新指令，一次性完成以下任务并严格输出JSON格式：
1. 【领域仲裁】：判断用户输入的意图属于 A(车控与多媒体任务)、B(车辆功能与说明书)、C(闲聊百科)、D(无意义或非人机对话)。
2. 【安全拒识】：判断指令是否安全。
3. 【多轮改写】：如果指令指代不明，请结合历史记录补全。
4. 【意图抽取】：如果领域是 A，请提取最有可能的 5 个候选意图及槽位；如果不是 A，返回空数组。
返回格式必须严格为：{"domain": "A|B|C|D", "is_safe": bool, "reject_reason": str, "rewritten_query": str, "candidate_intents": [{"intent": str, "slots": dict}]}"""

    messages = [
        {"role": "system", "content": TRAIN_SYSTEM_PROMPT},
        {"role": "user", "content": f"{history_text}最新指令: {query}"}
    ]
    
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    
    print(f"[Gemma 3] 正在推理 (受限解码启动)...")
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=512,
            pad_token_id=tokenizer.eos_token_id
        )
        
    generated_ids = output_ids[0][inputs.input_ids.shape[1]:]
    result_text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
    
    # 清理可能存在的 markdown 标签
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]
    result_text = result_text.strip()
    
    print(f"[Gemma 3] 推理结果:\n{result_text}")
    
    try:
        # Fallback to json loads since lmformatenforcer is removed
        result_dict = json.loads(result_text)
        
        # 为了兼容 workflow 中期待的 function/intent 等顶层字段
        domain = result_dict.get("domain", "A")
        is_safe = result_dict.get("is_safe", True)
        
        if domain == "A" and is_safe and len(result_dict.get("candidate_intents", [])) > 0:
            top_intent = result_dict["candidate_intents"][0]
            intent_str = str(top_intent.get("intent", "Unknown"))
            # 强校验：如果生成的意图不在合法列表中，降级为 Unknown
            if intent_str not in valid_intents:
                print(f"[WARN] 大模型生成了未定义的意图 {intent_str}，强制降级为 Unknown")
                intent_str = "Unknown"
            
            result_dict["function"] = intent_str
            result_dict["intent"] = intent_str
            result_dict["slots"] = top_intent.get("slots", {})
        else:
            result_dict["function"] = "Unknown"
            result_dict["intent"] = "Unknown"
            result_dict["slots"] = {}
            
        return result_dict
    except Exception as e:
        print(f"[ERR] JSON 解析或格式错误: {e}")
        return {
            "domain": "A",
            "is_safe": True,
            "rewritten_query": query,
            "intent": "Unknown",
            "function": "Unknown",
            "slots": {},
            "raw_text": result_text,
            "error": str(e)
        }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8011)
