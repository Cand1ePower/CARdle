import os
import json
import time
import asyncio
import socketio
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# ── 加载 .env 环境变量（最优先执行，覆盖 os.environ）──
from dotenv import load_dotenv
load_dotenv(override=False)  # override=False: 若系统已有同名变量则不覆盖

# ── 日志器（支持 trace_id 链路追踪） ──
from utils import logger

# ── 流式闲聊模块（直接 import，非 HTTP 调用） ──
from client.stream_chat import request_chat_async, process_chat_frames

# ── NLU 薄封装客户端（直接 import，非 HTTP 调用） ──
from client.nlu import request_nlu_async

# ── NLG 润色模块（直接 import） ──
from client.nlg import request_nlg_async

# ── MCP 工具分发中心 ──
from mcp_core.tool_dispatcher import dispatch_tool

# ── 对话管理器 DM 工厂 ──
from function_call.dm.factory import DMFactory, get_domain_by_intent

# ── 持久化层：Redis + SQLite ──
from db.redis_client import redis_client
from db.sqlite_client import init_db, sqlite_client
from db.models import AuditLog

# 可观测性
try:
    from langfuse import Langfuse, propagate_attributes, observe, get_client
    langfuse_client = Langfuse()
    if not langfuse_client.auth_check():
        logger.warning("[Startup] Langfuse 配置有误或未配置，将不启用全链路追踪功能")
        langfuse_client = None
except Exception as e:
    langfuse_client = None
    logger.warning(f"[Startup] Langfuse 初始化失败，跳过: {e}")
    # 降级：哑装饰器和上下文管理器
    def observe(*args, **kwargs):
        def decorator(func): return func
        return decorator
    from contextlib import contextmanager
    @contextmanager
    def propagate_attributes(*args, **kwargs):
        yield
    def get_client(): return None

import prompts

# ============================================================
# 微服务地址与超时配置
# 注：stream_chat / nlu / nlg 已改为直接 import，不再需要端口
# ============================================================
REWRITE_URL  = os.getenv("REWRITE_URL",  "http://127.0.0.1:8006/rewrite-server/v1")
REJECT_URL   = os.getenv("REJECT_URL",   "http://127.0.0.1:8007/reject-server/v1")
INTENT_URL   = os.getenv("INTENT_URL",   "http://127.0.0.1:8008/intent-server/v1")
CORR_URL     = os.getenv("CORR_URL",     "http://127.0.0.1:8009/correlation-server/v1")

# 单路微服务最长等待时间 (秒)
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "3.0"))


# ============================================================
# FastAPI 生命周期：服务启动时初始化数据库
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时执行初始化，关闭时执行清理"""
    # 初始化 SQLite（建表）
    await init_db()
    # 检查 Redis 连接
    redis_ok = await redis_client.ping()
    if redis_ok:
        logger.info("[Startup] Redis 连接正常 ✓")
    else:
        logger.warning("[Startup] Redis 不可用，将以降级模式运行（无多轮记忆）")
    yield
    logger.info("[Shutdown] CARdle 网关正常关闭")


# ============================================================
# ASGI 应用初始化
# ============================================================
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI(title="CARdle 语音智能控制网联中心", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一 ASGI 入口，暴露给 uvicorn 加载
combined_app = socketio.ASGIApp(sio, other_asgi_app=app)


@app.get("/health")
async def health_check():
    redis_ok = await redis_client.ping()
    return {
        "status": "healthy",
        "service": "CARdle",
        "version": "2.0.0",
        "redis": "connected" if redis_ok else "degraded",
    }


@app.get("/api/device/{device_id}")
async def get_device_info(device_id: str):
    """查询车辆档案（含实时状态）"""
    device = await sqlite_client.get_device(device_id)
    if not device:
        return {"error": f"设备 {device_id} 未注册"}
    state = await redis_client.get_vehicle_state(device_id)
    history = await redis_client.get_history(device_id)
    return {
        "device": device.model_dump(),
        "realtime_state": state.model_dump(),
        "recent_history_turns": len(history),
    }


@app.get("/api/device/{device_id}/audit")
async def get_device_audit(device_id: str, limit: int = 10):
    """查询车辆最近的操作审计日志"""
    logs = await sqlite_client.get_recent_audit(device_id, limit)
    return {"device_id": device_id, "count": len(logs), "logs": logs}


# ============================================================
# 五路并发协程函数
# 第 1-4 路：HTTP 调用独立 FastAPI 微服务
# 第 5 路：直接 import stream_chat 模块
# ============================================================

async def request_rewrite_async(query: str, last_answer: str = "") -> dict:
    """第 1 路：多轮指代消解改写"""
    try:
        headers = {"X-Trace-Id": logger.session.trace_id}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(REWRITE_URL, json={"query": query, "last_answer": last_answer}, headers=headers)
            result = resp.json()
            logger.info(f"[Rewrite] result='{result.get('rewrite_query', query)}'")
            return result
    except Exception as e:
        logger.error(f"[Rewrite] 降级，原语保全: {e}")
        return {"rewrite_query": query, "degraded": True}


async def request_reject_async(query: str) -> dict:
    """第 2 路：安全拒识判定"""
    try:
        headers = {"X-Trace-Id": logger.session.trace_id}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(REJECT_URL, json={"query": query}, headers=headers)
            result = resp.json()
            logger.info(f"[Reject] score={result.get('reject_score', 0)}")
            return result
    except Exception as e:
        logger.error(f"[Reject] 降级，默认放行: {e}")
        return {"reject_score": 0, "is_reject": False, "degraded": True}


async def request_arbitration_async(query: str) -> dict:
    """第 3 路：多路仲裁分流（stream 读第一 token，在 arbitration.py 侧实现）"""
    try:
        headers = {"X-Trace-Id": logger.session.trace_id}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(INTENT_URL, json={"query": query}, headers=headers)
            result = resp.json()
            logger.info(f"[Arbitration] branch='{result.get('branch', 'task')}'")
            return result
    except Exception as e:
        logger.error(f"[Arbitration] 降级，走任务兜底: {e}")
        return {"branch": "task", "degraded": True}


async def request_correlation_async(query: str) -> dict:
    """第 4 路：上下文关联判定"""
    try:
        headers = {"X-Trace-Id": logger.session.trace_id}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(CORR_URL, json={"query": query}, headers=headers)
            result = resp.json()
            logger.info(f"[Correlation] is_correlated={result.get('is_correlated', True)}")
            return result
    except Exception as e:
        logger.error(f"[Correlation] 降级，默认关联: {e}")
        return {"is_correlated": True, "degraded": True}


async def _prefetch_chat_async(query: str) -> dict:
    """
    第 5 路：闲聊上下文预热。
    直接调用 client.stream_chat 模块，在仲裁结果出来前提前准备好 LLM 上下文。
    若仲裁结果为 chat，process_chat_frames() 可立即开始流式推送。
    """
    try:
        ctx = await request_chat_async(query)
        return ctx
    except Exception as e:
        logger.error(f"[Chat Prefetch] 降级: {e}")
        return {"mode": "mock", "reply": "抱歉，网络开小差了，请您再说一遍呢~", "degraded": True}


# ============================================================
# WebSocket 事件监听
# ============================================================
@sio.event
async def connect(sid, environ):
    """
    车机接入时：
    1. 解析请求参数中的 device_id（未传则使用默认设备）
    2. 将 sid → device_id 写入 Redis 会话绑定
    3. 更新 SQLite 中的 last_seen_at
    """
    # 尝试从握手参数中获取 device_id
    query_string = environ.get("QUERY_STRING", "")
    device_id = "CARDLE_DEV_001"  # 默认设备（向后兼容）
    if "device_id=" in query_string:
        for part in query_string.split("&"):
            if part.startswith("device_id="):
                device_id = part.split("=", 1)[1]
                break

    await redis_client.bind_session(sid, device_id)
    await sqlite_client.touch_device(device_id)
    logger.info(f"[Connect] sid={sid[:8]}... device={device_id}")


@sio.event
async def disconnect(sid):
    """车机断连时：清理 Redis 会话绑定"""
    await redis_client.unbind_session(sid)
    logger.info(f"[Disconnect] sid={sid[:8]}...")


# ============================================================
# 核心对话网关入口
# ============================================================
@sio.event
@observe(as_type="generation", name="Gateway_Request")
async def request_nlu(sid, data_str):
    try:
        json_info = json.loads(data_str)
        query       = json_info.get("query", "")
        client_trace_id = json_info.get("trace_id", "unknown")
        last_answer = json_info.get("last_answer", "")  # 客户端传来的单轮兜底

        # ── 从 Redis 查询当前连接的 device_id ──
        device_id = await redis_client.get_device_id(sid) or "CARDLE_DEV_001"
        
        # Langfuse v4: 使用 propagate_attributes 关联设备和会话属性
        with propagate_attributes(user_id=device_id, session_id=sid):
            
            client = get_client()
            if client and client.get_current_trace_id():
                # 必须使用 OTEL 兼容的 32 字符 16 进制 Trace ID
                langfuse_trace_id = client.get_current_trace_id()
            else:
                langfuse_trace_id = client_trace_id
                
            # 设置 trace_id，后续所有 logger 和微服务调用自动携带
            logger.session.trace_id = langfuse_trace_id
            begin = time.time()
            
            logger.info(f"========== [REQUEST_NLU START] query='{query[:20]}' device='{device_id}' trace='{langfuse_trace_id}' ==========")

            if client:
                try:
                    client.update_current_span(
                        input={"query": query, "last_answer": last_answer}
                    )
                except Exception as e:
                    logger.error(f"[Langfuse] update span error: {e}")

        # ── 防抖检查：2 秒内相同 query 去重 ──
        if not await redis_client.try_dedup(device_id, query):
            logger.info(f"[Dedup] 拦截重复请求 device={device_id} query='{query[:20]}'")
            return  # 静默丢弃，不回包

        # ── 从 Redis 读取多轮对话历史（真实多轮，非单轮兜底）──
        history_turns = await redis_client.get_history(device_id)
        if history_turns:
            # 将历史格式化为改写服务可用的文本，覆盖客户端传来的 last_answer
            last_answer = history_turns[-1].content if history_turns[-1].role == "assistant" else last_answer
            logger.info(f"[History] device={device_id} 读取到 {len(history_turns)} 条历史")

        # ── 5 路并发 Fail-Safe 调度 ──
        results = await asyncio.gather(
            request_rewrite_async(query, last_answer),   # 1. 意图改写
            request_reject_async(query),                  # 2. 安全拒识
            request_arbitration_async(query),             # 3. 仲裁分流
            request_correlation_async(query),             # 4. 关联性判定
            _prefetch_chat_async(query),                  # 5. 闲聊预热
            return_exceptions=True
        )
        gather_cost = time.time() - begin

        # ── 二次兜底 ──
        rewrite_result     = results[0] if not isinstance(results[0], Exception) else {"rewrite_query": query, "degraded": True}
        reject_result      = results[1] if not isinstance(results[1], Exception) else {"reject_score": 0, "is_reject": False, "degraded": True}
        arbitration_result = results[2] if not isinstance(results[2], Exception) else {"branch": "task", "degraded": True}
        correlation_result = results[3] if not isinstance(results[3], Exception) else {"is_correlated": True, "degraded": True}
        chat_ctx           = results[4] if not isinstance(results[4], Exception) else {"mode": "mock", "reply": "抱歉，网络开小差了~", "degraded": True}

        degraded_count = sum(
            1 for r in [rewrite_result, reject_result, arbitration_result, correlation_result, chat_ctx]
            if isinstance(r, dict) and r.get("degraded")
        )
        logger.info(f"5 路并发完成 cost={gather_cost:.4f}s degraded={degraded_count}/5")

        # ── 决策变量 ──
        rewritten_query = rewrite_result.get("rewrite_query", query)
        is_reject = reject_result.get("is_reject", False) or reject_result.get("reject_score", 0) > 0.5
        branch    = arbitration_result.get("branch", "task")

        # ──────────────────────────────────────────
        # 分支 1：拒识
        # ──────────────────────────────────────────
        if is_reject:
            logger.info("Branch: REJECT")
            response = _build_base(query, client_trace_id, begin, degraded_count)
            response.update({
                "intent":    "拒识",
                "intent_id": "440",
                "func":      "REJECT",
                "frame":     prompts.DEFAULT_NLG,
                "seq":       1,
                "status":    -1,
                "branch":    "reject",
            })
            await sio.emit("request_nlu", json.dumps(response, ensure_ascii=False), to=sid)

        # ──────────────────────────────────────────
        # 分支 2：闲聊（三帧流式推送协议）
        # ──────────────────────────────────────────
        elif branch == "chat":
            logger.info("Branch: CHAT (three-frame streaming)")
            seq = 1
            full_answer = ""

            async for frame_content, status in process_chat_frames(chat_ctx):
                frame_resp = _build_base(query, client_trace_id, begin, degraded_count)
                frame_resp.update({
                    "intent":    "闲聊百科",
                    "intent_id": "439",
                    "func":      "CHAT",
                    "frame":     frame_content,
                    "seq":       seq,
                    "status":    status,
                    "branch":    "chat",
                })
                await sio.emit("request_nlu", json.dumps(frame_resp, ensure_ascii=False), to=sid)

                if status == 1:
                    full_answer += frame_content
                    seq += 1

            logger.info(f"Chat complete seq={seq} answer='{full_answer[:40]}'")

        # ──────────────────────────────────────────
        # 分支 3：任务型车控 / FAQ
        # ──────────────────────────────────────────
        else:
            logger.info(f"Branch: TASK/FAQ rewritten='{rewritten_query}'")

            # 调用 NLU 薄封装客户端进行意图识别
            nlu_response = await request_nlu_async(rewritten_query, langfuse_trace_id)
            function = nlu_response.get("function", "Unknown")

            if function not in ["Unknown", ""]:
                # ── 引入 DM 工厂决策模式 ──
                domain = get_domain_by_intent(function)
                dm_process = DMFactory.get(domain)
                if dm_process:
                    # 委托给领域 DM 统一处理 (槽位清洗、接口调度、NLG 润色一气呵成)
                    raw_response, nlg_text = await dm_process(function, rewritten_query, nlu_response.get("slots", {}))
                    tool_response = json.dumps(raw_response, ensure_ascii=False)
                else:
                    # 兜底旧有分发
                    tool_response = await dispatch_tool(function, nlu_response.get("slots", {}))
                    # 如果工具未注册或没有返回，提供一个默认成功状态，让 NLG 能生成自然语言回复
                    fallback_response = tool_response if tool_response else "指令下发成功"
                    nlg_text = await request_nlg_async(rewritten_query, fallback_response)

                response = _build_base(query, client_trace_id, begin, degraded_count)
                response.update({
                    "rewrite_query": rewritten_query,
                    "intent":        nlu_response.get("intent", "Unknown"),
                    "intent_id":     nlu_response.get("intent_id", "440"),
                    "func":          "SKILL",
                    "function":      function,
                    "slots":         nlu_response.get("slots", {}),
                    "frame":         nlg_text,
                    "seq":           1,
                    "status":        0,
                    "branch":        branch,
                })
            else:
                # ── Unknown：技能未识别，降级为拒识回包 ──
                logger.info(f"NLU returned Unknown, degrading to REJECT")
                response = _build_base(query, client_trace_id, begin, degraded_count)
                response.update({
                    "rewrite_query": rewritten_query,
                    "intent":        "拒识",
                    "intent_id":     "440",
                    "func":          "REJECT",
                    "frame":         prompts.DEFAULT_NLG,
                    "seq":           1,
                    "status":        -1,
                    "branch":        branch,
                })

            await sio.emit("request_nlu", json.dumps(response, ensure_ascii=False), to=sid)

        cost_total = time.time() - begin
        logger.info(f"Done cost={cost_total:.4f}s")

        # ── 异步写入对话历史 & 审计日志（不阻塞主流程）──
        final_nlg = ""
        final_intent = ""
        final_function = ""
        final_slots = {}
        if "response" in dir() and isinstance(response, dict):
            final_nlg      = response.get("frame", "")
            final_intent   = response.get("intent", "")
            final_function = response.get("function", "")
            final_slots    = response.get("slots", {})

            client = get_client()
            if client:
                try:
                    client.update_current_span(
                        output={"nlg_output": final_nlg, "func": final_function},
                        metadata={"branch": branch}
                    )
                    client.flush()  # 确保网关层的 trace 能即时上报
                except Exception as e:
                    logger.error(f"[Langfuse] flush error: {e}")

        asyncio.create_task(_post_request_tasks(
            device_id=device_id,
            query=query,
            nlg_text=final_nlg,
            trace_id=langfuse_trace_id,
            intent=final_intent,
            function=final_function,
            slots=final_slots,
            cost_ms=cost_total * 1000,
        ))

    except Exception as e:
        import traceback
        logger.error(f"Gateway fatal error: {e}")
        traceback.print_exc()
        error_response = {
            "query":     "",
            "trace_id":  "error",
            "func":      "ERROR",
            "frame":     "系统发生异常，请稍后再试。",
            "seq":       1,
            "status":    -1,
            "cost":      time.time() - begin,
        }
        await sio.emit("request_nlu", json.dumps(error_response, ensure_ascii=False), to=sid)


def _build_base(query: str, trace_id: str, begin: float, degraded_count: int) -> dict:
    """构建通用响应基底，避免重复字段定义"""
    return {
        "query":          query,
        "trace_id":       trace_id,
        "cost":           time.time() - begin,
        "degraded_count": degraded_count,
    }


async def _post_request_tasks(
    device_id: str,
    query: str,
    nlg_text: str,
    trace_id: str,
    intent: str = "",
    function: str = "",
    slots: dict = None,
    cost_ms: float = 0.0,
) -> None:
    """
    请求完成后的后台异步任务（fire-and-forget，不阻塞主流程）：
    1. 将本轮用户 query 和车机 NLG 回复写入 Redis 对话历史
    2. 将本次请求的完整信息写入 SQLite 审计日志
    """
    slots = slots or {}
    now = datetime.now(timezone.utc).isoformat()

    # 1. 写入 Redis 对话历史（用户轮 + 助手轮各一条）
    if query:
        await redis_client.push_history(device_id, "user", query)
    if nlg_text:
        await redis_client.push_history(device_id, "assistant", nlg_text)
        # 同步更新车辆状态寄存器中的 last_answer
        await redis_client.update_vehicle_state(
            device_id,
            last_query=query[:100],
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

