import os
import json
import time
import asyncio
import socketio
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# ── 加载 .env 环境变量（最优先执行，覆盖 os.environ）──
from dotenv import load_dotenv
load_dotenv(override=False)  # override=False: 若系统已有同名变量则不覆盖

# ── 日志器（支持 trace_id 链路追踪） ──
from utils import logger

# ── NLU 薄封装客户端（直接 import，非 HTTP 调用） ──
from client.nlu import request_nlu_async
from workflow.cardle_graph import cardle_app
from function_call.chatnlu_infer import ALL_SCHEMAS
from client.nlg import request_nlg_async

# ── API 路由与后台任务 ──
import api.routes
from db.tasks import post_request_tasks

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

# 挂载 HTTP 接口路由
app.include_router(api.routes.router)

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
            begin = time.time()
            if client and client.get_current_trace_id():
                # 必须使用 OTEL 兼容的 32 字符 16 进制 Trace ID
                langfuse_trace_id = client.get_current_trace_id()
            else:
                langfuse_trace_id = client_trace_id
                
            # 设置 trace_id，后续所有 logger 和微服务调用自动携带
            logger.session.trace_id = langfuse_trace_id
            
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

        # ── 终极端云协同：LangGraph 全局接管 ──
        history_dicts = [turn.model_dump() if hasattr(turn, 'model_dump') else (turn.dict() if hasattr(turn, 'dict') else turn) for turn in history_turns] if history_turns else []
        
        async def emit_to_client(response_dict):
            await sio.emit("request_nlu", json.dumps(response_dict, ensure_ascii=False), to=sid)
            
        initial_state = {
            "query": query,
            "history": history_dicts,
            "emit_callback": emit_to_client,
            "trace_id": langfuse_trace_id,
            "begin_time": begin
        }
        
        # 图自动接管一切（包括流式下发）
        final_state = await cardle_app.ainvoke(initial_state)

        cost_total = time.time() - begin
        logger.info(f"Done cost={cost_total:.4f}s")

        # ── 异步写入对话历史 & 审计日志（不阻塞主流程）──
        final_nlg = final_state.get("final_nlg", "")
        final_intent = final_state.get("intent", "")
        final_function = final_state.get("intent", "")
        final_slots = final_state.get("slots", {})
        final_nlu_result = final_state.get("nlu_result", {})

        client = get_client()
        if client:
            try:
                client.update_current_span(
                    output={"nlg_output": final_nlg, "func": final_function},
                    metadata={"branch": "graph"}
                )
                client.flush()  # 确保网关层的 trace 能即时上报
            except Exception as e:
                logger.error(f"[Langfuse] flush error: {e}")

        asyncio.create_task(post_request_tasks(
            device_id=device_id,
            query=query,
            nlg_text=final_nlg,
            trace_id=langfuse_trace_id,
            intent=final_intent,
            function=final_function,
            slots=final_slots,
            nlu_result=final_nlu_result,
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
