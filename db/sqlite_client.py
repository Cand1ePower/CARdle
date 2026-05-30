"""
CARdle SQLite 异步客户端封装
==============================
使用 aiosqlite 提供非阻塞的 SQLite 操作。

数据库文件路径: db/cardle.db（与代码同目录）

表结构:
  users      → 车主用户档案
  devices    → 车辆设备注册表
  audit_log  → 操作审计日志（每次对话请求的快照）
"""

import os
import aiosqlite
from typing import Optional, List
from datetime import datetime, timezone

from db.models import User, Device, AuditLog
from utils import logger

# 数据库文件位置：项目根目录下 db/cardle.db
_DB_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(_DB_DIR, "cardle.db")


# ────────────────────────────────────────────
# 数据库初始化（建表）
# ────────────────────────────────────────────

DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    user_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    phone        TEXT UNIQUE,
    created_at   TEXT NOT NULL,
    preferences  TEXT DEFAULT '{}'
);
"""

DDL_DEVICES = """
CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    vin           TEXT UNIQUE,
    model         TEXT,
    nickname      TEXT,
    registered_at TEXT NOT NULL,
    last_seen_at  TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
"""

DDL_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id    TEXT NOT NULL,
    device_id   TEXT,
    intent      TEXT,
    function    TEXT,
    slots       TEXT DEFAULT '{}',
    nlg_output  TEXT,
    cost_ms     REAL,
    created_at  TEXT NOT NULL
);
"""

# 创建索引以加快常用查询
DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_log(trace_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_device ON audit_log(device_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);",
]


async def init_db() -> None:
    """
    初始化数据库，创建所有表和索引。
    应在服务启动时（FastAPI lifespan 或 startup 事件）调用一次。
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")  # 开启 WAL 模式，提升并发写性能
        await db.execute("PRAGMA foreign_keys=ON;")   # 开启外键约束
        await db.execute(DDL_USERS)
        await db.execute(DDL_DEVICES)
        await db.execute(DDL_AUDIT_LOG)
        for idx_ddl in DDL_INDEXES:
            await db.execute(idx_ddl)
        await db.commit()
    logger.info(f"[SQLite] 数据库初始化完成: {DB_PATH}")


def get_db() -> str:
    """返回数据库路径（供 aiosqlite.connect() 使用）"""
    return DB_PATH


# ────────────────────────────────────────────
# 数据库操作封装
# ────────────────────────────────────────────

def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO8601 字符串"""
    return datetime.now(timezone.utc).isoformat()


class SQLiteClient:
    """
    CARdle SQLite 业务操作封装。
    所有方法均为异步，可直接在协程中 await 调用。
    遇到数据库异常时记录错误日志，但不中断主流程（Fail-Safe）。
    """

    # ── Users（车主用户）──────────────────────

    async def create_user(self, user: User) -> bool:
        """新增车主用户"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO users VALUES (?,?,?,?,?)",
                    (user.user_id, user.name, user.phone, user.created_at, user.preferences_json())
                )
                await db.commit()
            logger.info(f"[SQLite] users.create user_id={user.user_id} name={user.name}")
            return True
        except Exception as e:
            logger.error(f"[SQLite] create_user failed: {e}")
            return False

    async def get_user(self, user_id: str) -> Optional[User]:
        """根据 user_id 查询车主"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM users WHERE user_id=?", (user_id,)
                )
                row = await cursor.fetchone()
                if row:
                    import json as _json
                    return User(
                        user_id=row["user_id"],
                        name=row["name"],
                        phone=row["phone"],
                        created_at=row["created_at"],
                        preferences=_json.loads(row["preferences"] or "{}"),
                    )
        except Exception as e:
            logger.error(f"[SQLite] get_user failed: {e}")
        return None

    # ── Devices（车辆设备）──────────────────

    async def register_device(self, device: Device) -> bool:
        """注册车辆设备（已存在则忽略）"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO devices VALUES (?,?,?,?,?,?,?)",
                    (device.device_id, device.user_id, device.vin, device.model,
                     device.nickname, device.registered_at, device.last_seen_at)
                )
                await db.commit()
            logger.info(f"[SQLite] devices.register device_id={device.device_id}")
            return True
        except Exception as e:
            logger.error(f"[SQLite] register_device failed: {e}")
            return False

    async def get_device(self, device_id: str) -> Optional[Device]:
        """根据 device_id 查询车辆设备档案"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM devices WHERE device_id=?", (device_id,)
                )
                row = await cursor.fetchone()
                if row:
                    return Device(**dict(row))
        except Exception as e:
            logger.error(f"[SQLite] get_device failed: {e}")
        return None

    async def touch_device(self, device_id: str) -> None:
        """更新设备的最后在线时间（在 connect 事件时调用）"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE devices SET last_seen_at=? WHERE device_id=?",
                    (_now_iso(), device_id)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"[SQLite] touch_device failed: {e}")

    async def list_devices_by_user(self, user_id: str) -> List[Device]:
        """查询某车主名下所有车辆"""
        result = []
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM devices WHERE user_id=? ORDER BY registered_at DESC",
                    (user_id,)
                )
                rows = await cursor.fetchall()
                result = [Device(**dict(r)) for r in rows]
        except Exception as e:
            logger.error(f"[SQLite] list_devices_by_user failed: {e}")
        return result

    # ── AuditLog（操作审计）──────────────────

    async def write_audit(self, log: AuditLog) -> None:
        """
        异步写入一条操作审计日志。
        在网关主处理流程完成后调用，不阻塞主流程（fire-and-forget）。
        """
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """INSERT INTO audit_log
                       (trace_id, device_id, intent, function, slots, nlg_output, cost_ms, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (log.trace_id, log.device_id, log.intent, log.function,
                     log.slots_json(), log.nlg_output, log.cost_ms, log.created_at)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"[SQLite] write_audit failed: {e}")

    async def get_recent_audit(self, device_id: str, limit: int = 20) -> List[dict]:
        """查询某设备最近 N 条审计记录（用于调试或面试 Demo）"""
        result = []
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT * FROM audit_log WHERE device_id=?
                       ORDER BY created_at DESC LIMIT ?""",
                    (device_id, limit)
                )
                rows = await cursor.fetchall()
                result = [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[SQLite] get_recent_audit failed: {e}")
        return result


# ── 全局单例 ────────────────────────────────
sqlite_client = SQLiteClient()
