import os
import httpx
from utils import logger

try:
    from langfuse import observe
except ImportError:
    def observe(*args, **kwargs):
        return lambda f: f

INTENT_URL = os.getenv("ARBITRATION_URL", "http://127.0.0.1:8008/intent-server/v1")

@observe(as_type="generation", name="Arbitration_Step")
async def request_arbitration_async(query: str, history: list, candidates: list) -> dict:
    """第 3 路：云端意图仲裁（基于 Top-K 候选集）"""
    try:
        trace_id = logger.session.trace_id
        headers = {"X-Trace-Id": trace_id}
        payload = {
            "query": query,
            "history": [turn.model_dump() if hasattr(turn, 'model_dump') else (turn.dict() if hasattr(turn, 'dict') else turn) for turn in history],
            "candidates": candidates
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(INTENT_URL, json=payload, headers=headers)
            result = resp.json()
            logger.info(f"[Arbitration] picked intent='{result.get('intent', 'Unknown')}'")
            return result
    except Exception as e:
        logger.error(f"[Arbitration] 降级，返回首选意图兜底: {e}")
        # fallback to the first candidate if available
        fallback_intent = candidates[0] if candidates else {"intent": "Unknown", "slots": {}}
        if isinstance(fallback_intent, str):
            return {"intent": fallback_intent, "slots": {}, "degraded": True}
        return {"intent": fallback_intent.get("intent", "Unknown"), "slots": fallback_intent.get("slots", {}), "degraded": True}
