import subprocess
import sys
import os
import time

ASCII_ART = """
\033[92m  ██████╗ █████╗ ██████╗ ██████╗ ██╗     ███████╗\033[0m
\033[92m  ██╔════╝██╔══██╗██╔══██╗██╔══██╗██║     ██╔════╝\033[0m
\033[92m  ██║     ███████║██████╔╝██║  ██║██║     █████╗  \033[0m
\033[92m  ██║     ██╔══██║██╔══██╗██║  ██║██║     ██╔══╝  \033[0m
\033[92m  ╚██████╗██║  ██║██║  ██║██████╔╝███████╗███████╗\033[0m
\033[92m   ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝╚══════╝\033[0m
"""

print(ASCII_ART)
print("\033[96m  CARdle 智能座舱网关 - 统一集成启动器\033[0m")
print("  ================================================")
print("  [提示] 所有服务日志将整合输出到此窗口")
print("  [提示] 按 \033[93mCtrl+C\033[0m 可以一键安全退出所有服务")
print("  ================================================\n")

processes = []

def start_process(name, cmd):
    print(f"\033[94m[*] 正在启动 {name}...\033[0m")
    # 使用 Popen 后台执行，stdout 会自动继承并整合到当前控制台
    p = subprocess.Popen(cmd, shell=True, cwd=os.getcwd())
    processes.append((name, p))

try:
    # 1. 启动 Redis
    start_process("Redis (6379)", r".\redis\redis-server.exe --port 6379 --loglevel warning")
    time.sleep(1) # 给 Redis 留点启动时间

    # 2. 启动周边微服务
    start_process("Arbitration (8008)", r".venv\Scripts\python.exe client\arbitration.py")
    start_process("Gemma NLU (8011)", r".venv\Scripts\python.exe function_call\gemma_nlu_server.py")
    
    print("\n\033[93m[INFO] 等待微服务就绪 (3秒)...\033[0m\n")
    time.sleep(3)

    # 3. 启动主网关
    start_process("Gateway (8000)", r".venv\Scripts\uvicorn server:combined_app --host 127.0.0.1 --port 8000 --reload")
    
    print("\n\033[92m[SUCCESS] 所有微服务已成功唤起！\033[0m\n")
    
    # 挂起主线程，等待进程结束（或者等待 Ctrl+C）
    for _, p in processes:
        p.wait()

except KeyboardInterrupt:
    print("\n\n\033[91m[SHUTDOWN] 接收到退出信号，正在关闭所有微服务...\033[0m")
    for name, p in processes:
        try:
            # 尝试优雅终止进程树（Windows 下使用 taskkill）
            subprocess.run(f"taskkill /F /T /PID {p.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"  - 已关闭 {name}")
        except Exception:
            pass
    print("\n\033[92m拜拜！\033[0m")
    sys.exit(0)
