"""
CARdle 意图识别本地推理微服务 (Port 8008)
加载基于 hf_train 训练出的 HuggingFace 意图分类模型。
接收 query，返回概率最高的 Top-5 意图。
"""

import os
import json
import torch
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

# 使用当前文件同级的 pretrained/intent_model
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pretrained/intent_model")
MAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../dataset/new_map.json")

# 检查模型是否已训练完成（是否存在 config.json）
HAS_MODEL = os.path.exists(os.path.join(MODEL_DIR, "config.json"))

app = FastAPI(title="CARdle Intent Inference (Top-5 Funnel)", version="2.0.0")

# 加载意图映射表
intent_map = {}
if os.path.exists(MAP_FILE):
    with open(MAP_FILE, "r", encoding="utf-8") as f:
        intent_map = json.load(f)

# 懒加载模型，避免在 import 时卡死
tokenizer = None
model = None
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def load_model():
    global tokenizer, model
    if HAS_MODEL and model is None:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        print(f"[*] 正在加载意图分类模型: {MODEL_DIR}")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
        model.to(device)
        model.eval()
        print(f"[*] 模型加载完成 ({device})")

class IntentRequest(BaseModel):
    query: str

@app.post("/intent-server/v1")
async def infer_intent(req: IntentRequest):
    query = req.query.strip()
    
    if not HAS_MODEL:
        # 如果还没训练，提供一个临时的强行兼容兜底方案，保证链路通
        print("[WARN] 意图分类模型尚未训练完成，进入打底模式。")
        return {
            "query": query,
            "intents": [
                {"id": "1", "name": "Go_POI", "probability": 0.99},
                {"id": "14", "name": "Open_Air_Condition", "probability": 0.01},
                {"id": "120", "name": "Query_Timely_Weather", "probability": 0.00},
                {"id": "35", "name": "Open_Window", "probability": 0.00},
                {"id": "62", "name": "Close_Window", "probability": 0.00},
            ]
        }

    load_model()
    
    # 进行真实模型推理
    inputs = tokenizer(query, return_tensors="pt", truncation=True, padding=True, max_length=64).to(device)
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        # Softmax 转为概率
        probs = torch.nn.functional.softmax(logits, dim=-1)[0]
    
    # 取 top-5
    top5_probs, top5_indices = torch.topk(probs, 5)
    
    results = []
    for prob, idx in zip(top5_probs, top5_indices):
        idx_str = str(idx.item())
        name = intent_map.get(idx_str, "Unknown")
        results.append({
            "id": idx_str,
            "name": name,
            "probability": round(prob.item(), 4)
        })
        
    print(f"[Intent Funnel] '{query}' -> Top 1: {results[0]['name']} (P={results[0]['probability']})")
    
    return {
        "query": query,
        "intents": results
    }

if __name__ == "__main__":
    print("[*] Intent Infer Server starting on 127.0.0.1:8016...")
    uvicorn.run(app, host="127.0.0.1", port=8016, log_level="error")
