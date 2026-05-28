import uvicorn
import os
import sys
import json
import httpx
from fastapi import FastAPI
from pydantic import BaseModel

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import API_KEY, BASE_URL, IS_MOCK
from prompts import ARBITRAION_SYSTEM_PROMPT
from utils import logger

app = FastAPI(title="CARdle 多路仲裁分流服务", version="2.0.0")

MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT", "doubao-pro-4k")
TIMEOUT = 2.0


class ArbitrationRequest(BaseModel):
    query: str


@app.post("/intent-server/v1")
async def arbitrate(req: ArbitrationRequest):
    logger.info(f"[Arbitration] query='{req.query}'")

    # ── Mock 模式：关键词快速分类 ──
    if IS_MOCK:
        task_keywords = [
            "空调", "导航", "播放", "打开", "关闭", "去", "地图", "温度", "音量",
            "调高", "调低", "一点", "高点", "低点", "大声", "小声", "调", "设为"
        ]
        faq_keywords = ["怎么", "如何", "什么是", "能量回收", "单踏板", "手册", "功能", "介绍"]
        
        if any(w in req.query for w in task_keywords):
            text = "A"
        elif any(w in req.query for w in faq_keywords):
            text = "B"
        else:
            text = "C"
            
        branch = _map_branch(text)
        logger.info(f"[Arbitration] Mock result={text} -> branch={branch}")
        return {"branch": branch, "degraded": False}

    # ── 真实 API：stream=True 只读第一个有效 token ──
    headers = {
        "Content-Type": "application/json",
        "Authorization": API_KEY if API_KEY.startswith("Bearer") else f"Bearer {API_KEY}"
    }
    messages = [
        {"role": "system", "content": ARBITRAION_SYSTEM_PROMPT},
        {"role": "user", "content": req.query}
    ]
    body = {
        "model": MODEL_ENDPOINT,
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0,
        "stream": True   # 核心：流式调用，极速拿到第一个字符即停止
    }

    try:
        text = "A"  # 默认兜底走 task
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", BASE_URL, headers=headers, json=body) as response:
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    line = line.lstrip("data: ")
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                        token = data["choices"][0]["delta"].get("content", "")
                        if not token:
                            continue
                        text = token.strip().upper()
                        break  # 只读第一个有效 token，立即停止，最低延迟
                    except Exception:
                        continue

        if text not in ["A", "B", "C", "D"]:
            text = "A"

        branch = _map_branch(text)
        logger.info(f"[Arbitration] stream first-token={text} -> branch={branch}")
        return {"branch": branch, "degraded": False}

    except Exception as e:
        logger.error(f"[Arbitration] API error: {e}")
        return {"branch": "task", "degraded": True}


def _map_branch(text: str) -> str:
    """
    A -> task (车控任务)
    B -> faq  (车辆手册/功能介绍)
    C/D -> chat (闲聊/百科/无效输入)
    """
    if text in ("C", "D"):
        return "chat"
    elif text == "B":
        return "faq"
    else:
        return "task"


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8008)
