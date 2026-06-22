"""
tests/integration/test_gateway_e2e.py
=======================================
网关四分支端到端集成测试
测试范围：task / chat（流式三帧）/ reject / 多轮改写 四个核心分支
前置条件：python tools/runner.py（需要 Gateway(8000) + 所有微服务运行）

运行方式：
    python -m pytest tests/integration/test_gateway_e2e.py -v -s
"""

import asyncio
import json
import sys
import os
from collections import defaultdict

import pytest
import socketio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

GATEWAY_URL = "http://127.0.0.1:8000"
RESPONSE_TIMEOUT = 20.0  # 秒


async def _collect_frames(
    queries: list[dict],
    response_timeout: float = RESPONSE_TIMEOUT,
) -> dict[str, list[dict]]:
    """
    通用帧收集器：建立单个 WebSocket 连接，发送多条查询，收集按 trace_id 分组的所有帧。
    """
    frames_by_trace: dict[str, list] = defaultdict(list)
    expected_count = len(queries)
    completed: set[str] = set()
    all_done = asyncio.Event()

    sio = socketio.AsyncClient(logger=False, engineio_logger=False)

    @sio.event
    async def request_nlu(data):
        frame = json.loads(data) if isinstance(data, str) else data
        tid = frame.get("trace_id", "unknown")
        frames_by_trace[tid].append(frame)

        func = frame.get("func", "")
        status = frame.get("status", 0)

        is_done = (
            (func == "CHAT" and status == 2) or
            (func in ("SKILL", "REJECT", "ERROR") and status in (0, -1))
        )
        if is_done:
            completed.add(tid)
            if len(completed) >= expected_count:
                all_done.set()

    try:
        await sio.connect(GATEWAY_URL)
        for q in queries:
            await sio.emit("request_nlu", json.dumps(q, ensure_ascii=False))
            await asyncio.sleep(0.2)
        await asyncio.wait_for(all_done.wait(), timeout=response_timeout)
    except asyncio.TimeoutError:
        pass  # 超时时返回已收集到的帧
    finally:
        if sio.connected:
            await sio.disconnect()

    return dict(frames_by_trace)


# ───────────────────────────────────────────────
# 跳过条件：网关未启动时整体 skip
# ───────────────────────────────────────────────

def _gateway_available() -> bool:
    import httpx
    try:
        resp = httpx.get(f"{GATEWAY_URL}/health", timeout=2.0)
        return resp.status_code in (200, 404)
    except Exception:
        return False


skip_if_no_gateway = pytest.mark.skipif(
    not _gateway_available(),
    reason="主网关 (8000) 未启动，跳过集成测试。请先运行 python tools/runner.py"
)


# ───────────────────────────────────────────────
# 测试用例
# ───────────────────────────────────────────────

@skip_if_no_gateway
class TestTaskBranch:
    """车控任务分支（SKILL）"""

    async def test_ac_control_single_turn(self):
        """单轮：空调温度设置"""
        frames = await _collect_frames([
            {"query": "帮我把空调调到24度", "trace_id": "intg_task_001", "last_answer": ""}
        ])
        result = frames.get("intg_task_001", [{}])[-1]
        assert result.get("branch") == "task", f"期望 task 分支，实际: {result.get('branch')}"
        assert result.get("degraded_count", 99) == 0, "有服务降级"

    async def test_multiturn_rewrite(self):
        """多轮：'调高一点' 需借助上文改写"""
        frames = await _collect_frames([
            {"query": "调高一点", "trace_id": "intg_task_002", "last_answer": "已为您将温度设为24度"}
        ])
        result = frames.get("intg_task_002", [{}])[-1]
        assert result.get("branch") == "task"
        rewrite = result.get("rewrite_query", "")
        assert "空调" in rewrite or "温度" in rewrite, f"改写不含预期关键词: '{rewrite}'"


@skip_if_no_gateway
class TestChatBranch:
    """闲聊分支（CHAT）三帧协议"""

    async def test_chat_three_frame_protocol(self):
        """闲聊必须返回三种帧：开始帧(0) + 内容帧(1+) + 结束帧(2)"""
        frames = await _collect_frames([
            {"query": "你是谁呀", "trace_id": "intg_chat_001", "last_answer": ""}
        ], response_timeout=25.0)
        frame_list = frames.get("intg_chat_001", [])
        statuses = [f.get("status") for f in frame_list]
        assert 0 in statuses, "缺少开始帧 (status=0)"
        assert 1 in statuses, "缺少内容帧 (status=1)"
        assert 2 in statuses, "缺少结束帧 (status=2)"

    async def test_chat_has_content(self):
        """闲聊内容帧拼接后不应为空"""
        frames = await _collect_frames([
            {"query": "讲个笑话", "trace_id": "intg_chat_002", "last_answer": ""}
        ], response_timeout=25.0)
        frame_list = frames.get("intg_chat_002", [])
        content = "".join(f.get("frame", "") for f in frame_list if f.get("status") == 1)
        assert len(content) > 0, "闲聊内容为空"


@skip_if_no_gateway
class TestRejectBranch:
    """安全拒识分支（REJECT）"""

    async def test_abusive_input_rejected(self):
        """辱骂性内容应触发拒识分支"""
        frames = await _collect_frames([
            {"query": "这个坏车机太垃圾了", "trace_id": "intg_rej_001", "last_answer": ""}
        ])
        result = frames.get("intg_rej_001", [{}])[-1]
        assert result.get("branch") == "reject", f"辱骂内容未被拒识，实际分支: {result.get('branch')}"
        assert result.get("status") == -1

    async def test_reject_has_nlg_text(self):
        """拒识响应必须包含提示文本"""
        frames = await _collect_frames([
            {"query": "你是傻逼", "trace_id": "intg_rej_002", "last_answer": ""}
        ])
        result = frames.get("intg_rej_002", [{}])[-1]
        frame_text = result.get("frame", "")
        assert len(frame_text) > 0, "拒识帧没有提示文本"
