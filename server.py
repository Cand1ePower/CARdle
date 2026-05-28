import os
import json
import time
import asyncio
import socketio
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── 日志器（支持 trace_id 链路追踪） ──
from utils import logger

# ── 流式闲聊模块（直接 import，非 HTTP 调用） ──
from client.stream_chat import request_chat_async, process_chat_frames

# ── NLU 薄封装客户端（直接 import，非 HTTP 调用） ──
from client.nlu import request_nlu_async

# ── NLG 润色模块（直接 import，Phase 6 MCP 接入后全面使用） ──
from client.nlg import request_nlg_async

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
# ASGI 应用初始化
# ============================================================
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI(title="CARdle 语音智能控制网联中心", version="2.0.0")

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
    return {"status": "healthy", "service": "CARdle", "version": "2.0.0"}


# ============================================================
# 五路并发协程函数
# 第 1-4 路：HTTP 调用独立 FastAPI 微服务
# 第 5 路：直接 import stream_chat 模块
# ============================================================

async def request_rewrite_async(query: str, last_answer: str = "") -> dict:
    """第 1 路：多轮指代消解改写"""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(REWRITE_URL, json={"query": query, "last_answer": last_answer})
            result = resp.json()
            logger.info(f"[Rewrite] result='{result.get('rewrite_query', query)}'")
            return result
    except Exception as e:
        logger.error(f"[Rewrite] 降级，原语保全: {e}")
        return {"rewrite_query": query, "degraded": True}


async def request_reject_async(query: str) -> dict:
    """第 2 路：安全拒识判定"""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(REJECT_URL, json={"query": query})
            result = resp.json()
            logger.info(f"[Reject] score={result.get('reject_score', 0)}")
            return result
    except Exception as e:
        logger.error(f"[Reject] 降级，默认放行: {e}")
        return {"reject_score": 0, "is_reject": False, "degraded": True}


async def request_arbitration_async(query: str) -> dict:
    """第 3 路：多路仲裁分流（stream 读第一 token，在 arbitration.py 侧实现）"""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(INTENT_URL, json={"query": query})
            result = resp.json()
            logger.info(f"[Arbitration] branch={result.get('branch', 'task')}")
            return result
    except Exception as e:
        logger.error(f"[Arbitration] 降级，默认走 task: {e}")
        return {"branch": "task", "degraded": True}


async def request_correlation_async(query: str) -> dict:
    """第 4 路：多轮关联性判定"""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(CORR_URL, json={"query": query})
            result = resp.json()
            logger.info(f"[Correlation] is_correlated={result.get('is_correlated', True)}")
            return result
    except Exception as e:
        logger.error(f"[Correlation] 降级，默认判定为相关: {e}")
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
    logger.info(f"Client connected: {sid}")


@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")


# ============================================================
# 核心对话网关入口
# ============================================================
@sio.event
async def request_nlu(sid, data_str):
    begin = time.time()
    try:
        json_info = json.loads(data_str)
        query       = json_info.get("query", "")
        trace_id    = json_info.get("trace_id", "unknown")
        last_answer = json_info.get("last_answer", "")

        # 设置 trace_id，后续所有 logger 调用自动携带
        logger.session.trace_id = trace_id
        logger.info(f"Request: query='{query}'")

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
            response = _build_base(query, trace_id, begin, degraded_count)
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
                frame_resp = _build_base(query, trace_id, begin, degraded_count)
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
            nlu_response = await request_nlu_async(rewritten_query, trace_id)
            function = nlu_response.get("function", "Unknown")

            if function not in ["Unknown", ""]:
                # ── 已识别技能：Phase 6 接入 MCP 工具后，这里将加入工具执行 + NLG 润色 ──
                # tool_response = await execute_mcp_tool(function, nlu_response.get("slots", {}))
                # nlg_text = await request_nlg_async(rewritten_query, tool_response)
                nlg_text = ""  # Phase 6 占位

                response = _build_base(query, trace_id, begin, degraded_count)
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
                response = _build_base(query, trace_id, begin, degraded_count)
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

        logger.info(f"Done cost={time.time() - begin:.4f}s")

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
