"""
CARdle 阶段 5 交互式联调终端：实时多轮交互与大模型流式输出测试工具
==================================================================
功能描述：
  1. 自动化检测并自适应拉起 5 个周边微服务。
  2. 建立与 8000 网关的 WebSocket 联调，支持在控制台终端直接输入测试指令。
  3. 支持多轮对话：自动记住上一轮的回复并带入下一轮请求，用以验证多轮指代改写。
  4. 支持流式打印：对于闲聊流式三帧协议，自动在终端逐字流式打字输出，体验流畅。
  5. 退出时优雅释放并自动清理所有相关的后台服务进程。

用法：
  .venv\\Scripts\\python.exe tests/interactive_test.py
"""

import sys
import os
import time
import subprocess
import asyncio
import json
import httpx
import socketio

# 上移寻找根目录
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 确保在 tests 下运行时，引用路径正确
SERVICES = {
    "rewrite":       ("client/rewrite.py",               8006),
    "reject":        ("train/reject_infer.py",           8007),
    "arbitration":   ("client/arbitration.py",           8008),
    "correlation":   ("client/correlation.py",           8009),
    "chatnlu_infer": ("function_call/chatnlu_infer.py",  8015),
    # "intent_infer":  ("train/intent_infer.py",           8016), # 注释掉以测试断联时的全量大模型降级
}

async def is_port_in_use(port):
    """检测本地端口是否已被占用"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:{port}/docs", timeout=0.5)
            if resp.status_code == 200:
                return True
    except Exception:
        pass
    return False

async def main():
    processes = []
    python_exe = sys.executable
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 70)
    print("      CARdle 智能车机控制中心 - 终端实时交互联调客户端")
    print("=" * 70)

    # 1. 检测并自适应拉起周边微服务
    print("[*] 正在检查后台微服务状态...")
    for name, (path, port) in SERVICES.items():
        in_use = await is_port_in_use(port)
        if in_use:
            print(f"  [INFO] 服务 {name} 已在端口 {port} 运行，无需重复拉起")
        else:
            print(f"  [START] 正在拉起后端 {name} 服务在端口 {port}...")
            full_path = os.path.join(root_dir, path)
            log_dir = os.path.join(root_dir, "scratch")
            os.makedirs(log_dir, exist_ok=True)
            log_file = open(os.path.join(log_dir, f"interactive_service_{name}.log"), "w", encoding="utf-8")
            p = subprocess.Popen(
                [python_exe, full_path],
                stdout=log_file,
                stderr=log_file,
                cwd=root_dir
            )
            processes.append(p)

    if processes:
        print("[*] 正在等待拉起的服务就绪...")
        for name, (_, port) in SERVICES.items():
            for _ in range(16):
                if await is_port_in_use(port):
                    break
                await asyncio.sleep(0.5)

    # 2. 初始化 Socket.IO 客户端
    sio = socketio.AsyncClient()
    last_answer = ""
    history_conversation = []

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
            # 过滤掉非当前交互会话的回包
            return

        func = frame.get("func", "")
        status = frame.get("status", 0)
        branch = frame.get("branch", "unknown")

        def _print_metrics(tid, frame):
            cost_ms = (time.time() - send_timestamps[tid]) * 1000 if tid in send_timestamps else 0
            server_cost = frame.get("cost", 0) * 1000
            print(f"[时延统计] 核心服务端: {server_cost:.1f}ms | 客户端整链路: {cost_ms:.1f}ms")

        # ── 拒识拦截处理 ──
        if func == "REJECT":
            nlg_text = frame.get("frame", "")
            print(f"\n[拒识安全哨兵] 阻断命中 (branch={branch})")
            print(f"舱舱 答: {nlg_text}")
            _print_metrics(tid, frame)
            print("-" * 60)
            last_answer = nlg_text
            stream_active.set()

        # ── 流式闲聊推送 ──
        elif func == "CHAT":
            frame_content = frame.get("frame", "")
            if status == 0:
                # 开始帧
                accumulated_reply = ""
                sys.stdout.write("舱舱 (正在打字) >> ")
                sys.stdout.flush()
            elif status == 1:
                # 中间内容帧
                sys.stdout.write(frame_content)
                sys.stdout.flush()
                accumulated_reply += frame_content
            elif status == 2:
                # 结束帧
                sys.stdout.write("\n")
                sys.stdout.flush()
                _print_metrics(tid, frame)
                print("-" * 60)
                last_answer = accumulated_reply
                stream_active.set()

        # ── 车控任务/FAQ 解析处理 ──
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
            
            # Phase 6 接入 MCP 时将展现润色后的 NLG，目前给出回执
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
        await sio.connect("http://127.0.0.1:8000")
    except Exception as e:
        print(f"[-] 连接网关主服务 8000 端口失败！请确保 server:combined_app 正在运行。{e}")
        # 清理自动拉起的微服务
        for p in processes:
            p.terminate()
        return

    print("\n" + "=" * 70)
    print("  CARdle 车机对话网关启动完毕！已无缝对接配置的大模型服务。")
    print("  支持多轮改写消解测试。输入 'exit' 或 'quit' 可退出当前交互。")
    print("=" * 70)

    # 4. 实时循环输入读取
    loop_count = 1
    try:
        while True:
            # 保证上一轮流式全部打印完，才释放下一次的输入
            await stream_active.wait()
            
            # 使用 asyncio.to_thread 保证 input() 的阻塞不会冻结 asyncio 的 WebSocket 消息轮询
            user_input = await asyncio.to_thread(input, "CARdle >> ")
            user_input = user_input.strip()

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit"):
                print("[*] 退出交互客户端...")
                break

            # 重置流式锁
            stream_active.clear()
            
            # 生成专属 trace_id
            current_tid = f"tid_inter_{loop_count:03d}_{int(time.time())}"
            loop_count += 1

            # 并发发送请求包
            payload = {
                "query": user_input,
                "trace_id": current_tid,
                "last_answer": last_answer
            }
            
            # 打印多轮背景
            if last_answer:
                print(f"  [DEBUG] 多轮参考回复: '{last_answer[:25]}...'")

            send_timestamps[current_tid] = time.time()
            await sio.emit("request_nlu", json.dumps(payload, ensure_ascii=False))

    finally:
        # 5. 释放后台进程和 WebSocket 资源
        print("\n[*] 正在断开 WebSocket 链接并清理微服务进程...")
        try:
            await sio.disconnect()
        except Exception:
            pass

        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=2)
                print(f"  [OK] 进程 {p.pid} 已释放")
            except Exception:
                pass
        print("=" * 70)
        print("  CARdle 交互终端已安全退出。")
        print("=" * 70)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
