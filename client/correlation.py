import uvicorn
import os
import sys
from fastapi import FastAPI, Request
from pydantic import BaseModel

# 确保能导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm_async
from prompts import CORRELATION_SYSTEM, CORRELATION_PROMPT
from utils.logger import session

app = FastAPI(title="CARdle 多轮关联性判定服务", version="2.0.0")

class CorrelationRequest(BaseModel):
    query: str

@app.post("/chatnlu-server/v1")
async def correlate(req: CorrelationRequest, request: Request):
    session.trace_id = request.headers.get("X-Trace-Id", "unknown")
    print(f"[Correlation Service] 收到多轮关联性判定请求: '{req.query}' | TraceID: {session.trace_id}")
    query = req.query.strip()
    
    # 模拟关联判定（后续阶段引入 Redis 后将真正比对上一轮句子）：
    # 目前通过 LLM 判定当前单句是否为依赖上下文的“片段性追问/动作指令”
    prompt = f"""你是一个语言分析专家。请判断以下用户指令是否属于“依赖上下文的多轮追问或程度控制”（例如含有“调高点”、“不要了”、“换一个”、“它”等，或者是一个不完整的动作片段）。
如果是依赖上下文的追问，请输出'是'；如果是结构完整、开启全新话题的独立指令，请输出'否'。

用户指令：'{query}'
请仅输出'是'或'否'，不要解释原因。"""

    messages = [
        {"role": "system", "content": CORRELATION_SYSTEM},
        {"role": "user", "content": prompt}
    ]
    
    try:
        ans = await call_llm_async(messages, temperature=0.1)
        ans = ans.strip()
        print(f"  [OK] 关联性判定结果: '{ans}'")
        is_correlated = "是" in ans
        return {"is_correlated": is_correlated, "degraded": False}
    except Exception as e:
        print(f"  [ERR] 关联性服务异常: {e}")
        return {"is_correlated": True, "degraded": True}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8009)
