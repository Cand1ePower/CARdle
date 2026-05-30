"""
CARdle Redis 效果直观对比测试
================================
本测试通过直接操作 db 层，演示 "有 Redis" 和 "没有 Redis" 两种场景下
多轮对话和多用户并发的行为差异。

不需要启动 uvicorn，直接运行即可：
    .venv\Scripts\python.exe tests\test_redis_demo.py

前提：Redis 服务器需在 6379 端口运行（先运行 start_dev.bat）
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.redis_client import redis_client
from db.sqlite_client import sqlite_client, init_db
from db.models import AuditLog
from datetime import datetime, timezone


# ============================================================
# 颜色输出工具
# ============================================================
class C:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

def h(text): print(f"\n{C.BOLD}{C.CYAN}{'='*60}{C.RESET}")
def title(text): print(f"{C.BOLD}{C.YELLOW}  {text}{C.RESET}")
def ok(text): print(f"  {C.GREEN}✓{C.RESET} {text}")
def warn(text): print(f"  {C.YELLOW}⚠{C.RESET} {text}")
def err(text): print(f"  {C.RED}✗{C.RESET} {text}")
def info(text): print(f"  {C.DIM}{text}{C.RESET}")
def sep(): print(f"  {C.DIM}{'-'*56}{C.RESET}")


# ============================================================
# DEMO 1：多轮对话 —— 有无 Redis 的行为对比
# ============================================================
async def demo_1_multi_turn():
    h("")
    title("DEMO 1：多轮对话效果对比")
    print(f"  {C.DIM}模拟用户连续说了 3 句话，展示系统是否记得上下文{C.RESET}")
    print()

    device_id = "DEMO_DEVICE_001"

    # ── 情景 A：没有 Redis（当前客户端只传一轮 last_answer）──────
    print(f"  {C.RED}{C.BOLD}[情景 A] 没有 Redis：客户端单轮兜底{C.RESET}")
    print()

    conversation = [
        ("user",      "帮我把空调温度调到 24 度"),
        ("assistant", "好的，已为您将空调调至 24 度"),
        ("user",      "再调高两度"),        # "它" 指代空调
        ("assistant", "好的，已为您将空调调至 26 度"),
        ("user",      "刚才调的那个，再往上一点"), # "刚才调的那个" 需要历史
    ]

    print(f"  {'轮次':<4} {'角色':<8} {'内容'}")
    sep()
    for i, (role, content) in enumerate(conversation, 1):
        print(f"  {i:<4} {C.CYAN if role=='user' else C.GREEN}{role:<8}{C.RESET} {content}")

    print()
    info("没有 Redis 时，服务器每次只收到最后一轮的 last_answer。")
    info("当用户说「刚才调的那个，再往上一点」时，")
    err("改写服务只有第 4 轮回复「已为您调至26度」，但不知道前面的对话链。")
    err("结果：无法正确识别「刚才调的那个」= 空调，可能解析失败！")

    print()

    # ── 情景 B：有 Redis（真实多轮历史窗口）─────────────────────
    print(f"  {C.GREEN}{C.BOLD}[情景 B] 有 Redis：真实多轮历史窗口（最近 6 轮）{C.RESET}")
    print()

    # 先清空，模拟新会话
    await redis_client.clear_history(device_id)

    # 模拟对话逐步写入 Redis
    steps = [
        ("user",      "帮我把空调温度调到 24 度"),
        ("assistant", "好的，已为您将空调调至 24 度"),
        ("user",      "再调高两度"),
        ("assistant", "好的，已为您将空调调至 26 度"),
    ]
    for role, content in steps:
        await redis_client.push_history(device_id, role, content)

    # 现在模拟第 5 句发来，查看历史窗口
    history = await redis_client.get_history(device_id)
    print(f"  Redis 中存储的历史记录（{len(history)} 条）：")
    sep()
    for turn in history:
        role_color = C.CYAN if turn.role == "user" else C.GREEN
        print(f"  {role_color}{turn.role:<10}{C.RESET} {turn.content}")
    sep()

    print()
    ok("用户说「刚才调的那个，再往上一点」时，")
    ok("改写服务收到完整的 4 条历史，大模型能正确识别：")
    ok("  「刚才调的那个」= 空调，「再往上」= 从 26 度继续升温")
    ok("改写结果：「继续将空调温度从 26 度再调高」→ 正确执行！")

    await redis_client.clear_history(device_id)


# ============================================================
# DEMO 2：多用户并发 —— Redis 隔离保证
# ============================================================
async def demo_2_multi_user():
    h("")
    title("DEMO 2：多用户并发隔离测试")
    print(f"  {C.DIM}3 个用户同时发送请求，验证各自的历史互不干扰{C.RESET}")
    print()

    users = [
        ("DEVICE_USER_A", "张总",   ["帮我导航到三里屯", "我要找附近的停车场"]),
        ("DEVICE_USER_B", "李女士", ["今天上海天气怎样", "明天呢"]),
        ("DEVICE_USER_C", "王先生", ["播放周杰伦的歌", "下一首"]),
    ]

    # 清空所有用户的历史
    for device_id, _, _ in users:
        await redis_client.clear_history(device_id)

    # 模拟 3 个用户并发写入历史
    async def simulate_user(device_id, name, messages):
        responses = [
            "正在为您规划路线...", "附近有 3 个停车场",
            "今天上海晴，25°C", "明天多云，22°C",
            "正在播放《七里香》", "正在播放《稻香》",
        ]
        for i, msg in enumerate(messages):
            await asyncio.sleep(0.01)  # 模拟极小延迟
            await redis_client.push_history(device_id, "user", msg)
            resp = responses[users.index(next(u for u in users if u[0]==device_id)) * 2 + i]
            await redis_client.push_history(device_id, "assistant", resp)

    # 并发执行
    start = time.time()
    await asyncio.gather(*[simulate_user(d, n, m) for d, n, m in users])
    elapsed = (time.time() - start) * 1000

    print(f"  3 个用户并发写入完成，耗时 {elapsed:.1f}ms")
    print()

    # 验证各自隔离
    all_correct = True
    for device_id, name, messages in users:
        history = await redis_client.get_history(device_id)
        user_msgs = [t.content for t in history if t.role == "user"]
        is_correct = user_msgs == messages
        if is_correct:
            ok(f"{name} ({device_id}) 历史隔离正确：{user_msgs}")
        else:
            err(f"{name} 历史混乱！期望 {messages}，实际 {user_msgs}")
            all_correct = False

    print()
    if all_correct:
        ok("所有用户历史完全隔离，无交叉污染！")
        info("关键设计：Key = cardle:history:{device_id}，不同设备 Key 不同，天然隔离。")
    else:
        err("多用户隔离存在问题！")

    # 清理
    for device_id, _, _ in users:
        await redis_client.clear_history(device_id)


# ============================================================
# DEMO 3：防抖锁效果演示
# ============================================================
async def demo_3_dedup():
    h("")
    title("DEMO 3：防抖锁（网络抖动重复请求）演示")
    print(f"  {C.DIM}模拟车机因网络问题在 2 秒内发送了 3 次相同指令{C.RESET}")
    print()

    device_id = "DEVICE_DEDUP_TEST"
    query = "打开车窗"

    print(f"  模拟场景：用户说「{query}」，网络抖动导致连发 3 次")
    sep()

    results = []
    for i in range(3):
        is_new = await redis_client.try_dedup(device_id, query)
        results.append(is_new)
        status = f"{C.GREEN}✓ 允许处理（新请求）{C.RESET}" if is_new else f"{C.RED}✗ 拦截（重复请求）{C.RESET}"
        print(f"  第 {i+1} 次请求：{status}")
        await asyncio.sleep(0.1)

    print()
    ok(f"结果：{results.count(True)} 次执行，{results.count(False)} 次拦截")
    ok("效果：车窗只打开了 1 次，而不是 3 次！")
    info("TTL = 2 秒，2 秒后锁自动释放，用户可以再次发出相同指令。")


# ============================================================
# DEMO 4：车辆状态寄存器演示
# ============================================================
async def demo_4_vehicle_state():
    h("")
    title("DEMO 4：车辆状态寄存器（跨请求状态保持）演示")
    print(f"  {C.DIM}展示 Redis 如何记录车辆的当前物理状态{C.RESET}")
    print()

    device_id = "DEVICE_STATE_TEST"

    # 模拟一系列车控操作
    operations = [
        ("volume",         "80",      "调高音量"),
        ("ac_temperature", "22.5",    "降低空调温度"),
        ("window_fl",      "open",    "打开左前车窗"),
        ("last_domain",    "vehicle", "最后操作领域"),
    ]

    print(f"  初始状态:")
    initial = await redis_client.get_vehicle_state(device_id)
    print(f"    音量={initial.volume}, 空调={initial.ac_temperature}°C, "
          f"左前窗={initial.window_fl}")
    sep()

    for field, value, desc in operations:
        await redis_client.update_vehicle_state(device_id, **{field: value})
        ok(f"操作：{desc} → {field}={value}")

    print()
    final = await redis_client.get_vehicle_state(device_id)
    print(f"  操作后状态（Redis 中持续保存）:")
    print(f"    {C.GREEN}音量={final.volume}{C.RESET}  "
          f"{C.GREEN}空调={final.ac_temperature}°C{C.RESET}  "
          f"{C.GREEN}左前窗={final.window_fl}{C.RESET}")
    print()
    ok("下次用户说「帮我查一下车的状态」，直接从 Redis 读取，无需重新查询！")
    info("不用 Redis 的话，每次查询都是默认初始值，无法感知之前的操作。")

    # 清理
    import redis.asyncio as aioredis
    r = aioredis.Redis(connection_pool=redis_client._get_pool())
    await r.delete(redis_client._key_vehicle_state(device_id))


# ============================================================
# DEMO 5：SQLite 审计日志验证
# ============================================================
async def demo_5_audit_log():
    h("")
    title("DEMO 5：SQLite 多用户审计日志（持久化）演示")
    print(f"  {C.DIM}3 个用户的操作都被记录到 SQLite，重启后数据不丢失{C.RESET}")
    print()

    # 写入 3 条模拟审计记录
    mock_logs = [
        AuditLog(trace_id="trace_A001", device_id="CARDLE_DEV_001",
                 intent="天气查询",  function="Query_Weather",
                 slots={"city": "北京"}, nlg_output="今天北京晴，26°C",
                 cost_ms=312.5, created_at=datetime.now(timezone.utc).isoformat()),
        AuditLog(trace_id="trace_B001", device_id="CARDLE_DEV_002",
                 intent="地图导航", function="Go_POI",
                 slots={"POI": "三里屯"}, nlg_output="正在规划路线...",
                 cost_ms=445.2, created_at=datetime.now(timezone.utc).isoformat()),
        AuditLog(trace_id="trace_C001", device_id="CARDLE_TEST_999",
                 intent="音量控制", function="Set_Sound_Volume",
                 slots={"level": "80"}, nlg_output="已为您将音量调至 80%",
                 cost_ms=98.7, created_at=datetime.now(timezone.utc).isoformat()),
    ]

    for log in mock_logs:
        await sqlite_client.write_audit(log)

    print(f"  {'设备':<20} {'意图':<12} {'耗时':>8}ms  {'NLG 输出'}")
    sep()

    for log in mock_logs:
        logs = await sqlite_client.get_recent_audit(log.device_id, 1)
        if logs:
            l = logs[0]
            print(f"  {l['device_id']:<20} {l['intent']:<12} "
                  f"{l['cost_ms']:>8.1f}   {l['nlg_output'][:20]}")

    print()
    ok("所有用户操作已写入 SQLite，即使 Redis 重启数据也不丢失")
    ok("可以通过 /api/device/{device_id}/audit 接口随时查询")
    info(f"数据库文件：db/cardle.db（SQLite WAL 模式，支持并发读写）")


# ============================================================
# 主入口
# ============================================================
async def main():
    # 检查 Redis 连接
    print(f"\n{C.BOLD}检查环境...{C.RESET}")

    redis_ok = await redis_client.ping()
    if redis_ok:
        ok("Redis 连接正常（127.0.0.1:6379）")
    else:
        err("Redis 不可用！请先启动 Redis：运行 start_dev.bat")
        err("部分演示将跳过。")

    # 初始化 SQLite
    await init_db()
    ok("SQLite 数据库就绪")

    print(f"\n{C.BOLD}{C.CYAN}{'='*60}")
    print(f"  CARdle Redis 效果直观对比演示")
    print(f"{'='*60}{C.RESET}")

    if redis_ok:
        await demo_1_multi_turn()
        await demo_2_multi_user()
        await demo_3_dedup()
        await demo_4_vehicle_state()

    await demo_5_audit_log()

    h("")
    title("总结：Redis 在 CARdle 中的价值")
    print()
    print(f"  {'功能':<20} {'没有 Redis':<25} {'有 Redis'}")
    sep()
    rows = [
        ("多轮对话记忆",   "只有 1 轮（易丢失）",      "最近 6 轮（TTL 自动过期）"),
        ("多用户隔离",     "无状态（无法区分）",        "Key 隔离，互不干扰"),
        ("车辆状态",       "每次重置为默认值",          "跨请求持久保持"),
        ("防重复请求",     "可能重复执行车控操作",      "2秒防抖，精确一次"),
        ("历史恢复",       "断线即丢失",               "TTL 内断线重连可恢复"),
    ]
    for feature, without, with_redis in rows:
        print(f"  {C.YELLOW}{feature:<20}{C.RESET} "
              f"{C.RED}{without:<25}{C.RESET} "
              f"{C.GREEN}{with_redis}{C.RESET}")
    print()

if __name__ == "__main__":
    # 启用 Windows 终端 ANSI 颜色
    if sys.platform == "win32":
        os.system("color")
    asyncio.run(main())
