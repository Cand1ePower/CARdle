"""
tools/interactive_client.py
=============================
CARdle 终端实时交互调试客户端
（原 tests/interactive_test.py，归类到 tools/ 作为开发工具）

功能描述：
  1. 纯净客户端模式：不自动拉起后台服务（请通过 start_dev.bat 或 python tools/runner.py 启动）
  2. 建立与 8000 网关的 WebSocket 联调，支持在控制台直接输入测试指令
  3. 支持模拟多个不同的车机设备（通过输入 device_id），验证 Redis 多用户隔离
  4. 支持流式打印：对于闲聊流式三帧协议，自动在终端逐字流式打字输出

用法：
  .venv\\Scripts\\python.exe tools/interactive_client.py
"""

import sys
import os
import time
import asyncio
import json
import socketio

# 确保能导入根模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    print("=" * 70)
    print("      CARdle 智能车机控制中心 - 终端实时交互调试客户端")
    print("=" * 70)
    print("\n[提示] 运行此客户端前，请确保已通过 start_dev.bat 或 python tools/runner.py 启动所有微服务。")

    # 1. 模拟设备身份绑定
    default_device = "CARDLE_DEV_001"
    device_id = input(f"\n请输入要模拟的车机 Device ID (直接回车默认使用 {default_device}): ").strip()
    if not device_id:
        device_id = default_device
    print(f"\n[+] 将模拟车辆设备: {device_id}")

    # 2. 初始化 Socket.IO 客户端
    sio = socketio.AsyncClient()
    last_answer = ""

    # 流式消息状态锁，用来阻止输入框在流式输出完之前插嘴
    stream_active = asyncio.Event()
    stream_active.set()  # 默认允许输入

    current_tid = ""
    accumulated_reply = ""
    send_timestamps = {}  # 记录每个 trace_id 请求发出的时刻

    @sio.event
    async def connect():
        print("[+] 成功建立与 CARdle 网关的 WebSocket 链接！")

    @sio.event
    async def request_nlu(data):
        nonlocal last_answer, accumulated_reply
        frame = json.loads(data)

        tid = frame.get("trace_id", "unknown")
        if tid != current_tid:
            return  # 过滤非当前会话的回包

        func = frame.get("func", "")
        status = frame.get("status", 0)
        branch = frame.get("branch", "unknown")

        def _print_metrics(tid, frame):
            cost_ms = (time.time() - send_timestamps[tid]) * 1000 if tid in send_timestamps else 0
            server_cost = frame.get("cost", 0) * 1000
            print(f"[时延统计] 核心服务端: {server_cost:.1f}ms | 客户端整链路: {cost_ms:.1f}ms")

        # ── 拒识拦截 ──
        if func == "REJECT":
            nlg_text = frame.get("frame", "")
            print(f"\n[拒识安全哨兵] 阻断命中 (branch={branch})")
            print(f"舱舱 答: {nlg_text}")
            _print_metrics(tid, frame)
            print("-" * 60)
            last_answer = nlg_text
            stream_active.set()

        # ── 流式闲聊 ──
        elif func == "CHAT":
            frame_content = frame.get("frame", "")
            if status == 0:
                accumulated_reply = ""
                sys.stdout.write("舱舱 (正在打字) >> ")
                sys.stdout.flush()
            elif status == 1:
                sys.stdout.write(frame_content)
                sys.stdout.flush()
                accumulated_reply += frame_content
            elif status == 2:
                sys.stdout.write("\n")
                sys.stdout.flush()
                _print_metrics(tid, frame)
                print("-" * 60)
                last_answer = accumulated_reply
                stream_active.set()

        # ── 车控任务/FAQ ──
        elif func == "SKILL":
            nlg_text = frame.get("frame", "")
            rewritten = frame.get("rewrite_query", "")
            intent = frame.get("intent", "Unknown")
            slots = frame.get("slots", {})
            function = frame.get("function", "Unknown")

            if rewritten and rewritten != frame.get("query", ""):
                print(f"\n[多轮改写] 改写后指令: '{rewritten}'")

            print(f"[意图识别] 命中功能: {function} (意图名: {intent})")
            if slots:
                print(f"[槽位提取] 提取参数: {slots}")

            nlg_display = nlg_text if nlg_text else f"收到车控指令，执行意图 {intent}。"
            print(f"舱舱 答: {nlg_display}")
            _print_metrics(tid, frame)
            print("-" * 60)
            last_answer = nlg_display
            stream_active.set()

        elif func == "ERROR":
            print(f"\n[ERROR] 服务网关内部异常: {frame.get('frame')}")
            _print_metrics(tid, frame)
            print("-" * 60)
            stream_active.set()

    # 3. 建立连接
    try:
        await sio.connect(f"http://127.0.0.1:8000?device_id={device_id}")
    except Exception as e:
        print(f"\n[-] 连接网关主服务 8000 端口失败！错误信息: {e}")
        return

    print("\n" + "=" * 70)
    print("  支持多轮改写消解测试。输入 'exit' 或 'quit' 可退出。")
    print("=" * 70)

    # 4. 实时循环输入
    loop_count = 1
    try:
        while True:
            await stream_active.wait()
            user_input = await asyncio.to_thread(input, "CARdle >> ")
            user_input = user_input.strip()

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("[*] 退出交互客户端...")
                break

            stream_active.clear()
            current_tid = f"tid_inter_{loop_count:03d}_{int(time.time())}"
            loop_count += 1

            payload = {"query": user_input, "trace_id": current_tid, "last_answer": last_answer}
            send_timestamps[current_tid] = time.time()
            await sio.emit("request_nlu", json.dumps(payload, ensure_ascii=False))

    finally:
        print("\n[*] 正在断开 WebSocket 链接...")
        try:
            await sio.disconnect()
        except Exception:
            pass
        print("=" * 70)
        print("  CARdle 交互终端已安全退出。")
        print("=" * 70)


if __name__ == "__main__":
    if sys.platform == "win32":
        os.system("color")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
