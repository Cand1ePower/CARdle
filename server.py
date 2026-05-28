import os
import json
import time
import asyncio
import socketio
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ============================================================
# 微服务地址与超时配置常量
# 各微服务独立端口，后续阶段逐步替换为真实业务逻辑
# ============================================================
REWRITE_URL   = os.getenv("REWRITE_URL",   "http://127.0.0.1:8006/rewrite-server/v1")
REJECT_URL    = os.getenv("REJECT_URL",     "http://127.0.0.1:8007/reject-server/v1")
INTENT_URL    = os.getenv("INTENT_URL",     "http://127.0.0.1:8008/intent-server/v1")
NLU_URL       = os.getenv("NLU_URL",        "http://127.0.0.1:8009/chatnlu-server/v1")
CHAT_URL      = os.getenv("CHAT_URL",       "http://127.0.0.1:8010/chat-server/v1")

# 全局超时阈值 (秒)：单路微服务最长等待时间
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "3.0"))

# ============================================================
# 1. 声明标准的 ASGI 高性能异步 Socket.IO 服务端
# async_mode='asgi' 代表它完美融入 FastAPI 异步事件循环
# ============================================================
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI(title="CARdle 语音智能控制网联中心", version="2.0.0")

# 2. 挂载标准跨域中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. 使用 Socket.IO 的 ASGIApp 包装整个 FastAPI 应用实现融合，防止路由无限循环递归
# 统一的 ASGI 入口点暴露为 combined_app 供 uvicorn 直接加载
combined_app = socketio.ASGIApp(sio, other_asgi_app=app)

# 4. 一个高性能的异步运维监控健康接口 (秒响应)
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "CARdle", "version": "2.0.0"}


# ============================================================
# 5. 五路协程异步请求函数
# 每路均配备独立的 try/except 异常隔离与超时降级兜底
# 任意一路崩溃绝不影响其他四路，实现 Fail-Safe 容灾
# ============================================================

async def request_rewrite_async(query: str, last_answer: str = "") -> dict:
    """
    第 1 路：多轮改写 —— 将指代消解后的完整语义文本返回。
    降级策略：大模型故障时，直接将原始 Query 作为改写结果（原语保全降级）。
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(REWRITE_URL, json={
                "query": query,
                "last_answer": last_answer
            })
            result = resp.json()
            print(f"  [✓] 改写服务返回: {result.get('rewrite_query', query)}")
            return result
    except Exception as e:
        print(f"  [✗] 改写服务异常，启用原语保全降级: {e}")
        return {"rewrite_query": query, "degraded": True}


async def request_reject_async(query: str) -> dict:
    """
    第 2 路：安全拒识判定 —— 判断用户指令是否属于车机无法处理的范畴。
    降级策略：拒识服务挂掉时，默认返回 0（非拒识/合法指令），防止误杀正常车控指令。
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(REJECT_URL, json={"query": query})
            result = resp.json()
            print(f"  [✓] 拒识服务返回: score={result.get('reject_score', 0)}")
            return result
    except Exception as e:
        print(f"  [✗] 拒识服务异常，默认放行（非拒识）: {e}")
        return {"reject_score": 0, "is_reject": False, "degraded": True}


async def request_arbitration_async(query: str) -> dict:
    """
    第 3 路：多路仲裁分流 —— 判定该走任务型车控分支还是闲聊分支。
    降级策略：仲裁故障时，默认走 task（任务型）分支，因为 task 有 Unknown 语义兜底。
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(INTENT_URL, json={"query": query})
            result = resp.json()
            print(f"  [✓] 仲裁服务返回: branch={result.get('branch', 'task')}")
            return result
    except Exception as e:
        print(f"  [✗] 仲裁服务异常，默认走 task 分支: {e}")
        return {"branch": "task", "degraded": True}


async def request_correlation_async(query: str) -> dict:
    """
    第 4 路：多轮关联性判定 —— 判断当前 Query 是否与上轮对话相关。
    降级策略：关联判定故障时，默认返回"相关"，确保多轮上下文通畅。
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(NLU_URL, json={"query": query})
            result = resp.json()
            print(f"  [✓] 关联性判定返回: is_correlated={result.get('is_correlated', True)}")
            return result
    except Exception as e:
        print(f"  [✗] 关联性服务异常，默认判定为多轮相关: {e}")
        return {"is_correlated": True, "degraded": True}


async def request_chat_async(query: str) -> dict:
    """
    第 5 路：闲聊预热 —— 预先调用闲聊大模型，以便仲裁走向闲聊时零延迟返回。
    降级策略：闲聊服务故障时，调用本地车机 NLG 温暖模板进行答复。
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(CHAT_URL, json={"query": query})
            result = resp.json()
            print(f"  [✓] 闲聊服务返回: nlg={result.get('nlg', '')[:30]}...")
            return result
    except Exception as e:
        print(f"  [✗] 闲聊服务异常，启用本地 NLG 温暖模板: {e}")
        return {
            "nlg": "抱歉，网络开小差了，请您再说一遍呢~",
            "degraded": True
        }


# ============================================================
# 6. WebSocket 异步连接/断开事件监听
# ============================================================
@sio.event
async def connect(sid, environ):
    print(f"[+] Client connected via WebSocket: {sid}")

@sio.event
async def disconnect(sid):
    print(f"[-] Client disconnected: {sid}")


# ============================================================
# 7. 核心对话网关入口事件
# 使用 asyncio.gather 实现 5 路协程并发调度
# return_exceptions=True 确保单路异常不会导致全局崩溃
# ============================================================
@sio.event
async def request_nlu(sid, data_str):
    begin = time.time()
    try:
        json_info = json.loads(data_str)
        query = json_info.get("query", "")
        trace_id = json_info.get("trace_id", "unknown")
        last_answer = json_info.get("last_answer", "")

        print(f"\n{'='*60}")
        print(f"[*] 收到语音指令: '{query}' | trace_id: {trace_id}")
        print(f"[*] 启动 5 路协程并发调度...")
        print(f"{'='*60}")

        # ── 核心：5 路协程并发 Fail-Safe 容灾调度 ──
        # asyncio.gather 将 5 个协程同时投入事件循环
        # return_exceptions=True 保证任意一路抛出异常时，
        # 其他四路不受影响，异常会作为返回值被安全捕获
        gather_begin = time.time()
        results = await asyncio.gather(
            request_rewrite_async(query, last_answer),      # 1. 意图改写
            request_reject_async(query),                     # 2. 安全拒识判定
            request_arbitration_async(query),                # 3. 多路仲裁分流
            request_correlation_async(query),                # 4. 关联性修正
            request_chat_async(query),                       # 5. 流式闲聊预热
            return_exceptions=True                           # 核心：异常隔离
        )
        gather_cost = time.time() - gather_begin

        # ── 解构 5 路返回值，对异常类型进行二次兜底 ──
        rewrite_result    = results[0] if not isinstance(results[0], Exception) else {"rewrite_query": query, "degraded": True}
        reject_result     = results[1] if not isinstance(results[1], Exception) else {"reject_score": 0, "is_reject": False, "degraded": True}
        arbitration_result = results[2] if not isinstance(results[2], Exception) else {"branch": "task", "degraded": True}
        correlation_result = results[3] if not isinstance(results[3], Exception) else {"is_correlated": True, "degraded": True}
        chat_result       = results[4] if not isinstance(results[4], Exception) else {"nlg": "抱歉，网络开小差了，请您再说一遍呢~", "degraded": True}

        # ── 统计降级情况 ──
        degraded_count = sum(1 for r in [rewrite_result, reject_result, arbitration_result, correlation_result, chat_result] if r.get("degraded"))
        print(f"\n[*] 5 路并发完成，耗时 {gather_cost:.4f}s，降级路数: {degraded_count}/5")

        # ── 分支决策：根据拒识 + 仲裁结果决定走向 ──
        rewritten_query = rewrite_result.get("rewrite_query", query)
        is_reject = reject_result.get("is_reject", False) or reject_result.get("reject_score", 0) > 0.5
        branch = arbitration_result.get("branch", "task")

        if is_reject:
            # 拒识命中：用户指令属于车机无法处理的范畴
            print(f"[!] 拒识命中，返回安全拦截提示")
            response = {
                "query": query,
                "trace_id": trace_id,
                "intent": "REJECT",
                "intent_id": "-1",
                "function": "REJECT",
                "slots": {},
                "cost": time.time() - begin,
                "nlg": "抱歉，这个指令我暂时无法处理，请尝试其他车控指令~",
                "branch": "reject",
                "degraded_count": degraded_count
            }
        elif branch == "chat":
            # 闲聊分支：直接使用预热好的闲聊回复
            print(f"[→] 仲裁走向: 闲聊分支")
            response = {
                "query": query,
                "trace_id": trace_id,
                "intent": "CHAT",
                "intent_id": "0",
                "function": "CHAT",
                "slots": {},
                "cost": time.time() - begin,
                "nlg": chat_result.get("nlg", "你好呀，有什么可以帮你的吗？"),
                "branch": "chat",
                "degraded_count": degraded_count
            }
        else:
            # 任务型分支：后续阶段接入真实的 NLU 意图识别与槽位提取
            print(f"[→] 仲裁走向: 任务型分支 (改写后: '{rewritten_query}')")
            response = {
                "query": query,
                "rewrite_query": rewritten_query,
                "trace_id": trace_id,
                "intent": "Unknown",
                "intent_id": "440",
                "function": "Unknown",
                "slots": {},
                "cost": time.time() - begin,
                "nlg": f"收到指令「{rewritten_query}」，NLU 业务逻辑将在后续阶段接入。",
                "branch": "task",
                "degraded_count": degraded_count
            }

        print(f"[*] 总耗时: {response['cost']:.4f}s")
        print(f"{'='*60}\n")

        # 异步私发推送给指定客户端链接
        await sio.emit("request_nlu", json.dumps(response, ensure_ascii=False), to=sid)

    except Exception as e:
        print(f"[-] 网关致命错误: {e}")
        # 终极安全线：即使网关主逻辑崩溃，也要给客户端返回一个兜底回包
        error_response = {
            "query": "",
            "trace_id": "error",
            "intent": "ERROR",
            "intent_id": "-999",
            "function": "ERROR",
            "slots": {},
            "cost": time.time() - begin,
            "nlg": "系统发生异常，请稍后再试。"
        }
        await sio.emit("request_nlu", json.dumps(error_response, ensure_ascii=False), to=sid)
