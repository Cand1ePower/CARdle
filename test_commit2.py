"""
CARdle 阶段 2 测试用例：5 路协程并发网关 & Fail-Safe 容灾降级验证
==================================================================
测试目标：
  1. 验证 Health Check 接口是否返回 v2.0.0 版本标识
  2. 验证 5 路微服务全部未启动时，网关是否正确触发全降级（5/5 降级）
  3. 验证降级后仍能正常返回结构化回包（不崩溃）
  4. 验证回包中包含 branch、degraded_count 等新增字段

运行前提：
  uvicorn server:combined_app --host 127.0.0.1 --port 8000 --reload
"""

import asyncio
import json
import httpx
import socketio


async def main():
    all_passed = True

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 阶段 1: Health Check 版本升级验证
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("[*] 测试 1: 验证 Health Check 接口版本升级...")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get("http://127.0.0.1:8000/health")
            data = resp.json()
            version = data.get("version", "unknown")
            if resp.status_code == 200 and version == "2.0.0":
                print(f"[+] 通过！状态码: {resp.status_code}, 版本: {version}")
            else:
                print(f"[-] 失败！状态码: {resp.status_code}, 版本: {version}")
                all_passed = False
        except Exception as e:
            print(f"[-] Health Check 失败，服务可能未启动: {e}")
            return

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 阶段 2: 全降级场景验证（5 路微服务均未启动）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n[*] 测试 2: 验证 5 路全降级场景（所有微服务均未启动）...")
    sio = socketio.AsyncClient()
    test2_result = {}

    @sio.event
    async def connect():
        print("[+] WebSocket 握手成功！")

    @sio.event
    async def request_nlu(data):
        nonlocal test2_result
        test2_result = json.loads(data)
        await sio.disconnect()

    try:
        await sio.connect("http://127.0.0.1:8000")

        payload = {
            "query": "帮我把空调调到24度",
            "trace_id": "test_failsafe_001"
        }
        print(f"[*] 发送测试指令: '{payload['query']}'")
        await sio.emit("request_nlu", json.dumps(payload, ensure_ascii=False))

        # 等待回包（最长等 10 秒，因为 5 路超时各需约 3 秒）
        await asyncio.wait_for(sio.wait(), timeout=15)

    except asyncio.TimeoutError:
        print("[-] 等待回包超时！")
        all_passed = False
    except Exception as e:
        print(f"[-] 测试失败: {e}")
        all_passed = False

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 阶段 3: 回包结构化字段校验
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print("\n[*] 测试 3: 回包结构化字段校验...")
    if test2_result:
        checks = {
            "query 字段存在": "query" in test2_result,
            "trace_id 正确": test2_result.get("trace_id") == "test_failsafe_001",
            "branch 字段存在": "branch" in test2_result,
            "degraded_count 字段存在": "degraded_count" in test2_result,
            "降级路数为 5/5": test2_result.get("degraded_count") == 5,
            "默认走 task 分支": test2_result.get("branch") == "task",
            "cost 耗时合理 (< 15s)": test2_result.get("cost", 999) < 15,
            "nlg 非空": bool(test2_result.get("nlg")),
        }

        for desc, passed in checks.items():
            status = "[+]" if passed else "[-]"
            print(f"  {status} {desc}")
            if not passed:
                all_passed = False

        print(f"\n[*] 完整回包内容:")
        print(f"    - 原始指令: {test2_result.get('query')}")
        print(f"    - 改写结果: {test2_result.get('rewrite_query', 'N/A')}")
        print(f"    - 分支走向: {test2_result.get('branch')}")
        print(f"    - 降级路数: {test2_result.get('degraded_count')}/5")
        print(f"    - 总耗时:   {test2_result.get('cost', 0):.4f}s")
        print(f"    - 车机响应: {test2_result.get('nlg')}")
    else:
        print("[-] 未收到回包，无法校验！")
        all_passed = False

    # -----------------------------------------------------------------
    # 最终汇总
    # -----------------------------------------------------------------
    print(f"\n{'='*60}")
    if all_passed:
        print("[PASS] 阶段 2 全部测试通过! 5 路协程并发网关 + Fail-Safe 容灾机制验证成功!")
    else:
        print("[FAIL] 阶段 2 存在失败项，请检查日志。")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
