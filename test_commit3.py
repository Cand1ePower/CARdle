"""
CARdle 阶段 3 测试用例：5 路微服务桩模块联调与连通性验证
==================================================================
测试目标：
  1. 自动化拉起 5 个微服务桩服务（端口 8006 到 8010）
  2. 验证与网关（127.0.0.1:8000）端到端联调是否正常，降级路数是否降为 0/5
  3. 验证多轮改写与关联性修正（“调高一点” -> 改写为“帮我把空调温度调高一点”）
  4. 验证闲聊分支分流（“你是谁” -> 触发闲聊并返回定制 NLG）
  5. 验证安全拒识功能（含有“垃圾”等词汇 -> 触发安全拦截）
  6. 自动优雅清理所有后台桩服务进程

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

# 桩服务模块的绝对路径与端口映射
STUBS = {
    "rewrite":     ("client/rewrite.py",     8006),
    "reject":      ("client/reject.py",      8007),
    "arbitration": ("client/arbitration.py", 8008),
    "correlation": ("client/correlation.py", 8009),
    "nlg":         ("client/nlg.py",         8010),
}

async def wait_for_port(port, timeout=5):
    """等待本地端口启动成功"""
    start_time = time.time()
    while time.time() - start_time < timeout:
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
    
    print("[*] 阶段 3 联调启动...")
    print("=" * 60)
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. 自动化启动 5 个独立的后台微服务桩进程
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    python_exe = sys.executable
    print(f"[*] 正在使用当前 Python 环境拉起 5 路桩服务: {python_exe}")
    
    try:
        for name, (path, port) in STUBS.items():
            full_path = os.path.abspath(path)
            print(f"  [+] 启动 {name} 服务在端口 {port}... ({path})")
            
            # 使用 subprocess 启动，并将 stdout/stderr 丢弃防止终端阻塞
            p = subprocess.Popen(
                [python_exe, full_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            processes.append(p)
            
        print("[*] 正在等待所有桩服务就绪...")
        for name, (_, port) in STUBS.items():
            ready = await wait_for_port(port)
            if ready:
                print(f"  [PASS] {name} 服务端口 {port} 连通测试通过！")
            else:
                print(f"  [FAIL] {name} 服务端口 {port} 启动超时！")
                all_passed = False
                
        if not all_passed:
            print("[-] 部分桩服务拉起失败，中止测试！")
            return

        print("\n[+] 5 个微服务已全部上线！开始连接核心对话网关进行联调测试...")
        print("=" * 60)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 2. 建立与网关的 Socket.IO 连接
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        sio = socketio.AsyncClient()
        test_results = []

        @sio.event
        async def connect():
            print("[+] WebSocket 成功建立与网关的连接！")

        @sio.event
        async def request_nlu(data):
            test_results.append(json.loads(data))
            # 释放 wait()
            if len(test_results) == 4:
                await sio.disconnect()

        try:
            await sio.connect("http://127.0.0.1:8000")
        except Exception as e:
            print(f"[-] 连接网关 (127.0.0.1:8000) 失败，请确保 uvicorn server:combined_app 正在运行！错误: {e}")
            all_passed = False
            return

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 3. 发送多组测试用例，覆盖各种业务分支
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        test_cases = [
            # 用例 1：常规单轮车控任务
            {"query": "帮我把空调调到24度", "trace_id": "case_001", "last_answer": ""},
            # 用例 2：多轮上下文改写（触发 correlation 判定为关联，以及 rewrite 改写）
            {"query": "调高一点", "trace_id": "case_002", "last_answer": "已为您将温度设为24度"},
            # 用例 3：常规闲聊（触发 arbitration 为 chat，并且获取 nlg 桩服务答复）
            {"query": "你是谁呀", "trace_id": "case_003", "last_answer": ""},
            # 用例 4：安全拒识拦截（触发 reject 拒识评分 > 0.5，返回拦截提示）
            {"query": "这个坏车机太垃圾了", "trace_id": "case_004", "last_answer": ""}
        ]

        print(f"\n[*] 正在有序发送 {len(test_cases)} 组测试指令...")
        for case in test_cases:
            print(f"  [→] 发送: '{case['query']}'")
            await sio.emit("request_nlu", json.dumps(case, ensure_ascii=False))
            await asyncio.sleep(0.2)  # 轻微间隔

        # 等待所有用例的回包
        try:
            await asyncio.wait_for(sio.wait(), timeout=12)
        except asyncio.TimeoutError:
            print(f"[-] 等待网关返回数据超时！仅收到 {len(test_results)}/4 个回包。")
            all_passed = False

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 4. 分析与验证测试结果
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        print("\n[*] 正在验证端到端各分支决策与降级率...")
        print(f"DEBUG raw results: {json.dumps(test_results, indent=2, ensure_ascii=False)}")
        
        # 将结果按 trace_id 组织以便对比
        res_map = {r.get("trace_id"): r for r in test_results}
        
        # 验证用例 1
        r1 = res_map.get("case_001")
        if r1:
            check_r1 = (
                r1.get("branch") == "task" and
                r1.get("degraded_count") == 0 and
                "24度" in r1.get("rewrite_query", "")
            )
            status = "[+]" if check_r1 else "[-]"
            print(f"  {status} 用例 1 (常规车控): 分支={r1.get('branch')}, 降级数={r1.get('degraded_count')}/5")
            if not check_r1: all_passed = False
        else:
            print("  [-] 用例 1 未收到回包")
            all_passed = False

        # 验证用例 2
        r2 = res_map.get("case_002")
        if r2:
            check_r2 = (
                r2.get("branch") == "task" and
                r2.get("degraded_count") == 0 and
                "空调温度调高一点" in r2.get("rewrite_query", "")
            )
            status = "[+]" if check_r2 else "[-]"
            print(f"  {status} 用例 2 (多轮改写): 改写后='{r2.get('rewrite_query')}', 降级数={r2.get('degraded_count')}/5")
            if not check_r2: all_passed = False
        else:
            print("  [-] 用例 2 未收到回包")
            all_passed = False

        # 验证用例 3
        r3 = res_map.get("case_003")
        if r3:
            check_r3 = (
                r3.get("branch") == "chat" and
                r3.get("degraded_count") == 0 and
                "全能特斯拉风车机小管家" in r3.get("nlg", "")
            )
            status = "[+]" if check_r3 else "[-]"
            print(f"  {status} 用例 3 (闲聊分支): NLG='{r3.get('nlg')}', 降级数={r3.get('degraded_count')}/5")
            if not check_r3: all_passed = False
        else:
            print("  [-] 用例 3 未收到回包")
            all_passed = False

        # 验证用例 4
        r4 = res_map.get("case_004")
        if r4:
            check_r4 = (
                r4.get("branch") == "reject" and
                r4.get("degraded_count") == 0 and
                "暂时无法处理" in r4.get("nlg", "")
            )
            status = "[+]" if check_r4 else "[-]"
            print(f"  {status} 用例 4 (安全拒识): 分支={r4.get('branch')}, NLG='{r4.get('nlg')}', 降级数={r4.get('degraded_count')}/5")
            if not check_r4: all_passed = False
        else:
            print("  [-] 用例 4 未收到回包")
            all_passed = False

    finally:
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 5. 优雅清理后台桩服务进程
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        print("\n[*] 正在清理后台桩服务进程...")
        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=2)
                print(f"  [OK] 桩服务进程 {p.pid} 已安全关闭")
            except Exception as e:
                print(f"  [-] 关闭桩服务进程失败: {e}")
                
    # 最终汇总
    print(f"\n{'='*60}")
    if all_passed:
        print("[PASS] 阶段 3 全部测试通过! 5路微服务桩连通测试成功，降级数归零!")
    else:
        print("[FAIL] 阶段 3 联调存在不符合预期项，请检查日志。")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
