from datetime import datetime, timezone
from utils import logger
from db.redis_client import redis_client
from db.sqlite_client import sqlite_client
from db.models import AuditLog

async def post_request_tasks(
    device_id: str,
    query: str,
    nlg_text: str,
    trace_id: str,
    intent: str = "",
    function: str = "",
    slots: dict = None,
    nlu_result: dict = None,
    cost_ms: float = 0.0,
) -> None:
    """
    请求完成后的后台异步任务（fire-and-forget，不阻塞主流程）：
    1. 将本轮用户 query 和车机 NLG 回复写入 Redis 对话历史
    2. 将本次请求的完整信息写入 SQLite 审计日志
    """
    slots = slots or {}
    nlu_result = nlu_result or {}
    now = datetime.now(timezone.utc).isoformat()
    rewritten_query = nlu_result.get("rewritten_query", query)
    domain = nlu_result.get("domain", "")

    # 1. 写入 Redis 对话历史（用户轮 + 助手轮各一条）
    if query:
        await redis_client.push_history(device_id, "user", query)
    if nlg_text:
        await redis_client.push_history(
            device_id,
            "assistant",
            nlg_text,
            metadata={
                "intent": intent,
                "function": function,
                "slots": slots,
                "domain": domain,
                "is_safe": nlu_result.get("is_safe", True),
                "rewritten_query": rewritten_query,
                "candidate_intents": nlu_result.get("candidate_intents", []),
            },
        )
        # 同步更新车辆状态寄存器中的 last_answer
        await redis_client.update_vehicle_state(
            device_id,
            last_domain=domain,
            last_query=rewritten_query[:100],
            last_answer=nlg_text[:200],
        )

    # 2. 异步写入 SQLite 审计日志
    audit = AuditLog(
        trace_id=trace_id,
        device_id=device_id,
        intent=intent,
        function=function,
        slots=slots,
        nlg_output=nlg_text,
        cost_ms=round(cost_ms, 2),
        created_at=now,
    )
    await sqlite_client.write_audit(audit)
    logger.info(f"[PostTask] history+audit 写入完成 device={device_id} trace={trace_id[:12]}")
