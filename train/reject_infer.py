"""
CARdle 安全拒识本地推理微服务 (Port 8007)
对于不属于车控、或者无意义的指令进行拒识判定。
二分类模型 (1: 安全指令，0: 拒识指令)
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import torch
import uvicorn
from fastapi import FastAPI, Request
from pydantic import BaseModel
from utils.logger import session

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pretrained/reject_model")
HAS_MODEL = os.path.exists(os.path.join(MODEL_DIR, "config.json"))

app = FastAPI(title="CARdle Reject Inference", version="2.0.0")

tokenizer = None
model = None
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def load_model():
    global tokenizer, model
    if HAS_MODEL and model is None:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        print(f"[*] 正在加载拒识分类模型: {MODEL_DIR}")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
        model.to(device)
        model.eval()
        print(f"[*] 模型加载完成 ({device})")

class RejectRequest(BaseModel):
    query: str

@app.post("/reject-server/v1")
async def infer_reject(req: RejectRequest, request: Request):
    session.trace_id = request.headers.get("X-Trace-Id", "unknown")
    query = req.query.strip()
    print(f"[Reject Service] 收到拒识请求: '{query}' | TraceID: {session.trace_id}")
    
    if not HAS_MODEL:
        # 如果还没训练，打底方案
        print("[WARN] 拒识分类模型尚未训练完成，进入打底模式。")
        # 简单规则：如果少于2个字或者是连续相同乱码，大概率拒识
        is_safe = True
        if len(query) < 2 or len(set(query)) == 1:
            is_safe = False
        return {
            "query": query,
            "is_safe": is_safe,
            "probability": 0.9 if is_safe else 0.1
        }

    load_model()
    
    inputs = tokenizer(query, return_tensors="pt", truncation=True, padding=True, max_length=64).to(device)
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        probs = torch.nn.functional.softmax(logits, dim=-1)[0]
    
    # 假设标签 1 为 safe，0 为 reject
    safe_prob = probs[1].item() if probs.shape[0] > 1 else probs[0].item()
    is_safe = safe_prob > 0.5
    
    print(f"[Reject] '{query}' -> is_safe: {is_safe} (P={safe_prob:.4f})")
    
    return {
        "query": query,
        "is_safe": is_safe,
        "probability": round(safe_prob, 4)
    }

if __name__ == "__main__":
    print("[*] Reject Infer Server starting on 127.0.0.1:8007...")
    uvicorn.run(app, host="127.0.0.1", port=8007, log_level="error")
