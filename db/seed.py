"""
CARdle 数据库初始化脚本
========================
一键初始化 SQLite 数据库并插入测试数据。

运行方式：
    python db/seed.py

会执行以下操作：
  1. 创建 db/cardle.db 数据库文件（如不存在）
  2. 建立 users / devices / audit_log 三张表
  3. 插入 2 个测试车主 + 3 辆测试车辆
"""

import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone

# 确保在项目根目录下运行时能正确导入模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.sqlite_client import init_db, sqlite_client, DB_PATH
from db.models import User, Device


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ────────────────────────────────────────────
# 测试种子数据
# ────────────────────────────────────────────

TEST_USERS = [
    User(
        user_id="user_001_tesla_owner",
        name="张伟",
        phone="138****0001",
        created_at=_now(),
        preferences={
            "default_city": "北京",
            "music_genre": "流行",
            "preferred_temp": "24.0",
        }
    ),
    User(
        user_id="user_002_dev_tester",
        name="开发测试员",
        phone="138****9999",
        created_at=_now(),
        preferences={
            "default_city": "上海",
            "music_genre": "摇滚",
        }
    ),
]

TEST_DEVICES = [
    Device(
        device_id="CARDLE_DEV_001",          # 与 interactive_test.py 默认 device_id 对齐
        user_id="user_001_tesla_owner",
        vin="LRW3E7FA0MC123456",
        model="Model 3 Performance",
        nickname="小黑",
        registered_at=_now(),
        last_seen_at=None,
    ),
    Device(
        device_id="CARDLE_DEV_002",
        user_id="user_001_tesla_owner",
        vin="LRW3E7FA0MC654321",
        model="Model Y Long Range",
        nickname="大白",
        registered_at=_now(),
        last_seen_at=None,
    ),
    Device(
        device_id="CARDLE_TEST_999",
        user_id="user_002_dev_tester",
        vin=None,
        model="虚拟测试车机",
        nickname="测试机",
        registered_at=_now(),
        last_seen_at=None,
    ),
]


async def main():
    print("=" * 60)
    print("  CARdle 数据库初始化工具")
    print("=" * 60)
    print(f"[*] 数据库路径: {DB_PATH}")

    # 1. 建表
    print("\n[1/3] 正在创建数据库表结构...")
    await init_db()
    print("  ✓ 表结构创建完成 (users / devices / audit_log)")

    # 2. 插入测试车主
    print("\n[2/3] 正在写入测试车主数据...")
    for user in TEST_USERS:
        ok = await sqlite_client.create_user(user)
        status = "✓" if ok else "⚠ (已存在，跳过)"
        print(f"  {status} 车主: {user.name} (ID: {user.user_id})")

    # 3. 插入测试车辆
    print("\n[3/3] 正在写入测试车辆数据...")
    for device in TEST_DEVICES:
        ok = await sqlite_client.register_device(device)
        status = "✓" if ok else "⚠ (已存在，跳过)"
        print(f"  {status} 车辆: {device.nickname} | 型号: {device.model} | ID: {device.device_id}")

    # 4. 验证读取
    print("\n[验证] 正在验证数据写入...")
    user = await sqlite_client.get_user("user_001_tesla_owner")
    if user:
        print(f"  ✓ 车主查询成功: {user.name}，偏好城市: {user.preferences.get('default_city')}")
    
    devices = await sqlite_client.list_devices_by_user("user_001_tesla_owner")
    print(f"  ✓ 该车主名下车辆数量: {len(devices)}")
    for d in devices:
        print(f"    - {d.nickname} ({d.model}) → device_id: {d.device_id}")

    print("\n" + "=" * 60)
    print("  ✅ 数据库初始化完成！")
    print(f"  数据库文件已保存至: {DB_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
