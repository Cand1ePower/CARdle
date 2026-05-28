"""
CARdle 阶段 4 测试用例：LLM 大模型集成 & 车机 NLU 意图与槽位解析联调
==================================================================
架构变更（本次）：
  - client/stream_chat.py 已改为直接 import 模块，不再是独立的 FastAPI 服务（端口 8010 释放）
  - client/nlg.py 已改为 LLM NLG 润色模块，不再是独立服务
  - 仲裁服务内部改为 stream=True 读取第一个 token（极速分类）
  - 闲聊分支现在推送三帧（开始帧/中间帧×N/结束帧）

测试目标：
  1. 自动化拉起 5 个 LLM 驱动的微服务（8006/8007/8008/8009/8015）
  2. 验证与网关（127.0.0.1:8000）端到端真实联调是否正常
  3. 验证任务型 NLU：空调控制 -> set_ac_temperature + temperature 槽位
  4. 验证多轮改写 + NLU："调高一点" -> 改写后空调指令 + slots
  5. 验证闲聊三帧推送：收到 status=0/1/2 三种帧，拼接内容含目标字符串
  6. 验证安全拒识：branch=reject + 默认 NLG 文本

运行前提：
  uvicorn server:combined_app --host 127.0.0.1 --port 8000 --reload
"""

import sys
import os
import time
import subprocess
import asyncio
import json
import httpx
import socketio
from collections import defaultdict

# ── 服务清单（stream_chat 已改为模块，端口 8010 不再需要启动） ──
SERVICES = {
    "rewrite":       ("client/rewrite.py",               8006),
    "reject":        ("client/reject.py",                8007),
    "arbitration":   ("client/arbitration.py",           8008),
    "correlation":   ("client/correlation.py",           8009),
    "chatnlu_infer": ("function_call/chatnlu_infer.py",  8015),
}


async def wait_for_port(port, timeout=8):
    """等待本地端口就绪"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://127.0.0.1:{port}/docs", timeout=1.0)
                if resp.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def main():
    processes = []
    all_passed = True

    print("[*] 阶段 4 联调启动（三帧协议版）...")
    print("=" * 60)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. 启动 5 个后台微服务（stream_chat 已内嵌，减少 1 个服务）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    python_exe = sys.executable
    print(f"[*] 正在拉起 {len(SERVICES)} 路微服务: {python_exe}")

    try:
        for name, (path, port) in SERVICES.items():
            full_path = os.path.abspath(path)
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
            os.makedirs(log_dir, exist_ok=True)
            log_file = open(os.path.join(log_dir, f"service_{name}.log"), "w", encoding="utf-8")
            p = subprocess.Popen(
                [python_exe, full_path],
                stdout=log_file,
                stderr=log_file,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            processes.append(p)

        print("[*] 正在等待所有服务就绪...")
        for name, (_, port) in SERVICES.items():
            ready = await wait_for_port(port)
            status = "[PASS]" if ready else "[FAIL]"
            print(f"  {status} {name} 端口 {port} {'就绪' if ready else '启动超时'}")
            if not ready:
                all_passed = False

        if not all_passed:
            print("[-] 部分服务拉起失败，中止测试！")
            return

        print(f"\n[+] {len(SERVICES)} 个微服务已全部就绪！开始端到端联调...")
        print("=" * 60)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 2. 建立 Socket.IO 连接
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        sio = socketio.AsyncClient()

        # 按 trace_id 分组收集所有帧（闲聊三帧场景会推多包）
        frames_by_trace: dict[str, list] = defaultdict(list)
        EXPECTED_CASES = 4
        completed_traces = set()

        @sio.event
        async def connect():
            print("[+] 成功建立与网关的 WebSocket 连接！")

        @sio.event
        async def request_nlu(data):
            frame = json.loads(data)
            tid = frame.get("trace_id", "unknown")
            frames_by_trace[tid].append(frame)

            # 判断该 trace 是否完成
            status = frame.get("status", 0)
            func   = frame.get("func", "")

            # 任务/拒识分支只有一帧（status=0 或 status=-1）
            # 闲聊分支最后一帧为 status=2
            if func == "CHAT" and status == 2:
                completed_traces.add(tid)
            elif func in ("SKILL", "REJECT", "ERROR") or (func == "CHAT" and status == 2):
                completed_traces.add(tid)
            elif status in (0, -1) and func != "CHAT":
                completed_traces.add(tid)

            if len(completed_traces) >= EXPECTED_CASES:
                await sio.disconnect()

        try:
            await sio.connect("http://127.0.0.1:8000")
        except Exception as e:
            print(f"[-] 连接网关失败: {e}")
            all_passed = False
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 3. 发送测试用例
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        test_cases = [
            {"query": "帮我把空调调到24度",   "trace_id": "case_001", "last_answer": ""},
            {"query": "调高一点",             "trace_id": "case_002", "last_answer": "已为您将温度设为24度"},
            {"query": "你是谁呀",             "trace_id": "case_003", "last_answer": ""},
            {"query": "这个坏车机太垃圾了",   "trace_id": "case_004", "last_answer": ""},
        ]

        print(f"\n[*] 发送 {len(test_cases)} 组测试指令...")
        for case in test_cases:
            print(f"  [->] '{case['query']}'")
            await sio.emit("request_nlu", json.dumps(case, ensure_ascii=False))
            await asyncio.sleep(0.3)

        # 等待所有回包（闲聊三帧可能需要更多时间）
        try:
            await asyncio.wait_for(sio.wait(), timeout=20)
        except asyncio.TimeoutError:
            print(f"[-] 等待超时！已完成 {len(completed_traces)}/{EXPECTED_CASES} 个用例")
            all_passed = False

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 4. 验证结果
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        print("\n[*] 验证端到端各分支结果...")
        print(f"DEBUG raw frames: {json.dumps(dict(frames_by_trace), indent=2, ensure_ascii=False)}")

        # 工具函数：取某 trace 最后一帧作为"主回包"
        def last(tid):
            return frames_by_trace.get(tid, [{}])[-1]

        def first(tid):
            return frames_by_trace.get(tid, [{}])[0]

        # ── 用例 1：空调控制 NLU ──
        r1 = last("case_001")
        frames1 = frames_by_trace.get("case_001", [])
        check_r1 = (
            r1.get("branch") == "task" and
            r1.get("intent") == "set_ac_temperature" and
            r1.get("slots", {}).get("temperature") == "24度" and
            r1.get("degraded_count", 99) == 0
        )
        tag = "[+]" if check_r1 else "[-]"
        print(f"  {tag} 用例1(车控NLU): intent={r1.get('intent')}, slots={r1.get('slots')}, degraded={r1.get('degraded_count')}/5")
        if not check_r1:
            all_passed = False

        # ── 用例 2：多轮改写 + NLU ──
        r2 = last("case_002")
        check_r2 = (
            r2.get("branch") == "task" and
            "空调" in r2.get("rewrite_query", "") and
            r2.get("degraded_count", 99) == 0
        )
        tag = "[+]" if check_r2 else "[-]"
        print(f"  {tag} 用例2(多轮改写+NLU): rewrite='{r2.get('rewrite_query')}', slots={r2.get('slots')}, degraded={r2.get('degraded_count')}/5")
        if not check_r2:
            all_passed = False

        # ── 用例 3：闲聊三帧推送 ──
        frames3 = frames_by_trace.get("case_003", [])
        statuses3 = [f.get("status") for f in frames3]
        # 拼接所有 status=1 的中间帧内容
        full_chat_text = "".join(f.get("frame", "") for f in frames3 if f.get("status") == 1)
        check_r3 = (
            0 in statuses3 and      # 有开始帧
            1 in statuses3 and      # 有中间帧（内容）
            2 in statuses3 and      # 有结束帧
            "全能特斯拉风车机小管家" in full_chat_text and
            frames3[-1].get("degraded_count", 99) == 0
        )
        tag = "[+]" if check_r3 else "[-]"
        print(f"  {tag} 用例3(闲聊三帧): 帧数={len(frames3)}, 状态序列={statuses3}, 内容='{full_chat_text[:40]}'")
        if not check_r3:
            all_passed = False

        # ── 用例 4：安全拒识 ──
        r4 = last("case_004")
        reject_frame = r4.get("frame", "")
        check_r4 = (
            r4.get("branch") == "reject" and
            reject_frame != "" and      # 有拒识提示文本（从 prompts.DEFAULT_NLG 取）
            r4.get("status") == -1 and
            r4.get("degraded_count", 99) == 0
        )
        tag = "[+]" if check_r4 else "[-]"
        print(f"  {tag} 用例4(安全拒识): branch={r4.get('branch')}, status={r4.get('status')}, frame='{reject_frame[:30]}'")
        if not check_r4:
            all_passed = False

    finally:
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 5. 清理后台服务进程
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        print("\n[*] 正在清理后台服务进程...")
        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=2)
                print(f"  [OK] 进程 {p.pid} 已关闭")
            except Exception as e:
                print(f"  [-] 关闭进程失败: {e}")

    print(f"\n{'='*60}")
    if all_passed:
        print("[PASS] 阶段 4 全部测试通过！三帧协议、NLU 意图解析、仲裁分流验证成功！")
    else:
        print("[FAIL] 阶段 4 存在不符合预期项，请检查 scratch/ 目录下的服务日志。")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
