"""
tests/integration/test_concurrency.py
=======================================
高并发 + TTFT（首字延迟）+ TraceId 隔离测试
测试范围：
  - 10 路 WebSocket 并发连接，验证 trace_id 完全隔离，无串场
  - 统计 TTFT（Time To First Token）和总延迟
  - 覆盖四大分支：task / chat / reject / faq
前置条件：Gateway(8000) + 所有微服务已运行

运行方式：
    python -m pytest tests/integration/test_concurrency.py -v -s
"""

import asyncio
import json
import sys
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field

import httpx
import pytest
import socketio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.slow]

GATEWAY_URL = "http://127.0.0.1:8000"
CONCURRENCY_TIMEOUT = 30.0


def _gateway_available() -> bool:
    try:
        httpx.get(f"{GATEWAY_URL}/health", timeout=2.0)
        return True
    except Exception:
        return False


skip_if_no_gateway = pytest.mark.skipif(
    not _gateway_available(),
    reason="主网关 (8000) 未启动，跳过并发测试。请先运行 python tools/runner.py"
)


@dataclass
class ClientResult:
    trace_id: str
    query: str
    expected_branch: str
    frames: list[dict] = field(default_factory=list)
    ttft_ms: float | None = None    # Time To First Token（首内容帧延迟）
    total_ms: float | None = None   # 整链路耗时
    contaminated: bool = False      # 是否收到了错误的 trace_id（串场）


async def _run_single_client(
    gateway_url: str,
    trace_id: str,
    query: str,
    expected_branch: str,
    done_event: asyncio.Event,
) -> ClientResult:
    """单客户端：建立独立 WebSocket 连接，发送请求，收集所有帧。"""
    result = ClientResult(trace_id=trace_id, query=query, expected_branch=expected_branch)
    sio = socketio.AsyncClient(logger=False, engineio_logger=False, reconnection=False)
    started: float | None = None

    @sio.event
    async def connect():
        nonlocal started
        started = time.perf_counter()

    @sio.event
    async def request_nlu(data):
        now = time.perf_counter()
        frame = json.loads(data) if isinstance(data, str) else data
        recv_tid = frame.get("trace_id", "")

        # 串场检测
        if recv_tid and recv_tid != trace_id:
            result.contaminated = True

        result.frames.append(frame)
        func = frame.get("func", "")
        status = frame.get("status", 0)

        # TTFT：首个内容帧到达时间
        if result.ttft_ms is None and started is not None:
            is_first_content = (func == "CHAT" and status == 1) or (func in ("SKILL", "REJECT") and status in (0, -1))
            if is_first_content:
                result.ttft_ms = (now - started) * 1000

        # 结束条件
        is_done = (func == "CHAT" and status == 2) or (func in ("SKILL", "REJECT", "ERROR") and status in (0, -1))
        if is_done:
            if started is not None:
                result.total_ms = (now - started) * 1000
            done_event.set()
            await sio.disconnect()

    try:
        await sio.connect(gateway_url)
        payload = {"query": query, "trace_id": trace_id, "last_answer": ""}
        await sio.emit("request_nlu", json.dumps(payload, ensure_ascii=False))
        await asyncio.wait_for(done_event.wait(), timeout=CONCURRENCY_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    except Exception:
        done_event.set()
    finally:
        if sio.connected:
            try:
                await sio.disconnect()
            except Exception:
                pass

    return result


# 并发测试用例定义
CONCURRENT_CASES = [
    # FAQ 问答
    ("trace_faq_001", "特斯拉单踏板模式怎么开", "faq"),
    ("trace_faq_002", "什么是能量回收制动",     "faq"),
    # 闲聊
    ("trace_chat_003", "舱舱你今天心情怎么样",  "chat"),
    ("trace_chat_004", "讲一个冷笑话",           "chat"),
    # 车控任务
    ("trace_task_005", "帮我把空调打开",         "task"),
    ("trace_task_006", "去上海高架桥",           "task"),
    # 安全拒识
    ("trace_rej_007",  "这是一个垃圾废柴车机",  "reject"),
    ("trace_rej_008",  "你这个笨蛋车机",         "reject"),
    # 混合
    ("trace_chat_009", "再讲个笑话",             "chat"),
    ("trace_task_010", "导航到外滩",             "task"),
]


@skip_if_no_gateway
class TestConcurrency:

    async def test_no_trace_contamination(self):
        """
        核心安全测试：10 路并发连接，验证 trace_id 完全隔离，零串场。
        每个 WebSocket 客户端只应收到自己的 trace_id 对应的帧。
        """
        done_events = {tid: asyncio.Event() for tid, _, _ in CONCURRENT_CASES}
        tasks = [
            _run_single_client(GATEWAY_URL, tid, query, branch, done_events[tid])
            for tid, query, branch in CONCURRENT_CASES
        ]
        results = await asyncio.gather(*tasks)

        contaminated_cases = [r for r in results if r.contaminated]
        assert not contaminated_cases, (
            f"发生 trace_id 串场！受影响的 trace: {[r.trace_id for r in contaminated_cases]}"
        )

    async def test_branch_accuracy_concurrent(self):
        """
        并发场景下的分支准确性：各请求应路由到正确的处理分支。
        注意：faq 分支允许 fallback 到 task（兼容仲裁未识别 faq 的情况）。
        """
        done_events = {tid: asyncio.Event() for tid, _, _ in CONCURRENT_CASES}
        tasks = [
            _run_single_client(GATEWAY_URL, tid, query, branch, done_events[tid])
            for tid, query, branch in CONCURRENT_CASES
        ]
        results = await asyncio.gather(*tasks)

        failures = []
        for r in results:
            if not r.frames:
                failures.append(f"{r.trace_id}: 未收到任何帧")
                continue
            actual_branch = r.frames[-1].get("branch", "unknown")
            # faq 允许 fallback 到 task
            branch_ok = (actual_branch == r.expected_branch) or (
                r.expected_branch == "faq" and actual_branch == "task"
            )
            if not branch_ok:
                failures.append(
                    f"{r.trace_id}（'{r.query}'）: 期望 {r.expected_branch}，实际 {actual_branch}"
                )

        assert not failures, "以下用例分支不符合预期:\n" + "\n".join(failures)

    async def test_ttft_statistics(self):
        """
        TTFT 统计测试（非断言型）：打印延迟数据供分析。
        如果所有请求均超过 2000ms，则标记为警告。
        """
        done_events = {tid: asyncio.Event() for tid, _, _ in CONCURRENT_CASES}
        tasks = [
            _run_single_client(GATEWAY_URL, tid, query, branch, done_events[tid])
            for tid, query, branch in CONCURRENT_CASES
        ]
        results = await asyncio.gather(*tasks)

        ttfts = [r.ttft_ms for r in results if r.ttft_ms is not None]
        totals = [r.total_ms for r in results if r.total_ms is not None]

        if ttfts:
            avg_ttft = sum(ttfts) / len(ttfts)
            max_ttft = max(ttfts)
            print(f"\n[TTFT 统计] 平均={avg_ttft:.1f}ms | 最大={max_ttft:.1f}ms | 样本={len(ttfts)}")
            # 极端情况预警：平均 TTFT > 3 秒说明系统严重过载
            assert avg_ttft < 3000, f"并发场景下平均 TTFT={avg_ttft:.1f}ms 严重过高（> 3000ms）"

        if totals:
            avg_total = sum(totals) / len(totals)
            print(f"[总延迟统计] 平均={avg_total:.1f}ms | 最大={max(totals):.1f}ms")
