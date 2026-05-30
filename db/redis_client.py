"""
CARdle Redis 客户端封装
========================
提供所有 Redis 操作的高层封装，屏蔽底层 Key 命名细节。

Key 命名规范：
  cardle:history:{device_id}          → 对话历史窗口 (List)
  cardle:session:{sid}                → 会话绑定：sid → device_id (String)
  cardle:vehicle_state:{device_id}    → 车辆实时状态 (Hash)
  cardle:dedup:{device_id}:{hash}     → 请求防抖锁 (String, TTL=2s)
"""

import os
import json
import hashlib
import redis.asyncio as aioredis
from typing import Optional, List
from datetime import datetime

from db.models import ConversationTurn, VehicleState
from utils import logger

# ────────────────────────────────────────────
# 配置常量
# ────────────────────────────────────────────
REDIS_HOST     = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB       = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)  # Memurai 默认无密码

# TTL 常量
TTL_HISTORY = 120   # 对话历史：2分钟无操作清除
TTL_SESSION = 3600  # 会话绑定：1小时
TTL_DEDUP   = 2     # 防抖锁：2秒

# 对话历史窗口最大长度
MAX_HISTORY_TURNS = 6

# Key 前缀
PREFIX = "cardle"


# ────────────────────────────────────────────
# 连接池（单例，全局复用）
# ────────────────────────────────────────────
_pool: Optional[aioredis.ConnectionPool] = None

def _get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True,   # 自动将 bytes 解码为 str
            max_connections=20,
            protocol=2,              # 强制 RESP2 协议，兼容 Redis 5.x / 6.x
        )
    return _pool

def get_redis() -> aioredis.Redis:
    """获取 Redis 连接（来自连接池，可直接 await 使用）"""
    return aioredis.Redis(connection_pool=_get_pool())


# ────────────────────────────────────────────
# RedisClient：业务层高封装
# ────────────────────────────────────────────
class RedisClient:
    """
    CARdle Redis 业务操作封装类。
    提供对话历史、会话绑定、车辆状态、防抖锁四类功能的读写接口。
    
    所有方法均为异步，可直接在 FastAPI / Socket.IO 协程中 await 调用。
    遇到 Redis 不可用时，方法会捕获异常并返回默认值（Fail-Safe 设计），
    确保主流程不会因为 Redis 宕机而崩溃。
    """

    # ── Key 构造器 ──────────────────────────
    @staticmethod
    def _key_history(device_id: str) -> str:
        return f"{PREFIX}:history:{device_id}"

    @staticmethod
    def _key_session(sid: str) -> str:
        return f"{PREFIX}:session:{sid}"

    @staticmethod
    def _key_vehicle_state(device_id: str) -> str:
        return f"{PREFIX}:vehicle_state:{device_id}"

    @staticmethod
    def _key_dedup(device_id: str, query: str) -> str:
        h = hashlib.md5(query.encode()).hexdigest()[:8]
        return f"{PREFIX}:dedup:{device_id}:{h}"

    # ── 对话历史窗口 ────────────────────────

    async def push_history(self, device_id: str, role: str, content: str) -> None:
        """追加一条对话记录到设备的历史窗口，并刷新 TTL"""
        try:
            r = get_redis()
            key = self._key_history(device_id)
            turn = ConversationTurn(
                role=role,
                content=content,
                ts=int(datetime.now().timestamp())
            )
            await r.rpush(key, turn.to_json())
            # 只保留最近 MAX_HISTORY_TURNS * 2 条（user + assistant 各算一条）
            await r.ltrim(key, -(MAX_HISTORY_TURNS * 2), -1)
            await r.expire(key, TTL_HISTORY)
            logger.info(f"[Redis] history.push device={device_id} role={role}")
        except Exception as e:
            logger.error(f"[Redis] push_history failed (degraded): {e}")

    async def get_history(self, device_id: str) -> List[ConversationTurn]:
        """获取设备最近的对话历史（最多 MAX_HISTORY_TURNS 轮）"""
        try:
            r = get_redis()
            key = self._key_history(device_id)
            raw_list = await r.lrange(key, -(MAX_HISTORY_TURNS * 2), -1)
            turns = [ConversationTurn.from_json(s) for s in raw_list]
            logger.info(f"[Redis] history.get device={device_id} turns={len(turns)}")
            return turns
        except Exception as e:
            logger.error(f"[Redis] get_history failed (degraded): {e}")
            return []

    async def clear_history(self, device_id: str) -> None:
        """清空设备的对话历史（如用户主动说"重新开始"）"""
        try:
            r = get_redis()
            await r.delete(self._key_history(device_id))
            logger.info(f"[Redis] history.clear device={device_id}")
        except Exception as e:
            logger.error(f"[Redis] clear_history failed: {e}")

    # ── 会话绑定（sid ↔ device_id）──────────

    async def bind_session(self, sid: str, device_id: str) -> None:
        """车机连接时，将 Socket.IO sid 绑定到 device_id"""
        try:
            r = get_redis()
            await r.setex(self._key_session(sid), TTL_SESSION, device_id)
            logger.info(f"[Redis] session.bind sid={sid[:8]}... → device={device_id}")
        except Exception as e:
            logger.error(f"[Redis] bind_session failed: {e}")

    async def get_device_id(self, sid: str) -> Optional[str]:
        """根据 sid 查询绑定的 device_id，连接断开或未绑定时返回 None"""
        try:
            r = get_redis()
            device_id = await r.get(self._key_session(sid))
            return device_id
        except Exception as e:
            logger.error(f"[Redis] get_device_id failed (degraded): {e}")
            return None

    async def unbind_session(self, sid: str) -> None:
        """车机断连时，清理会话绑定"""
        try:
            r = get_redis()
            await r.delete(self._key_session(sid))
            logger.info(f"[Redis] session.unbind sid={sid[:8]}...")
        except Exception as e:
            logger.error(f"[Redis] unbind_session failed: {e}")

    # ── 车辆状态寄存器 ──────────────────────

    async def get_vehicle_state(self, device_id: str) -> VehicleState:
        """读取车辆当前状态，若无记录则返回默认状态"""
        try:
            r = get_redis()
            key = self._key_vehicle_state(device_id)
            data = await r.hgetall(key)
            if data:
                return VehicleState.from_dict(data)
            # 首次访问，初始化默认状态并写入
            default_state = VehicleState()
            await r.hset(key, mapping=default_state.to_dict())
            logger.info(f"[Redis] vehicle_state.init device={device_id}")
            return default_state
        except Exception as e:
            logger.error(f"[Redis] get_vehicle_state failed (degraded): {e}")
            return VehicleState()

    async def update_vehicle_state(self, device_id: str, **fields) -> None:
        """
        更新车辆状态的指定字段。
        
        用法示例:
            await redis_client.update_vehicle_state(
                device_id, volume="70", last_domain="vehicle"
            )
        """
        try:
            r = get_redis()
            key = self._key_vehicle_state(device_id)
            # 将所有值转为字符串（Redis Hash 只存字符串）
            str_fields = {k: str(v) for k, v in fields.items()}
            await r.hset(key, mapping=str_fields)
            logger.info(f"[Redis] vehicle_state.update device={device_id} fields={list(fields.keys())}")
        except Exception as e:
            logger.error(f"[Redis] update_vehicle_state failed: {e}")

    # ── 请求防抖锁 ──────────────────────────

    async def try_dedup(self, device_id: str, query: str) -> bool:
        """
        原子性防抖：尝试为 (device_id, query) 组合设置 2 秒锁。
        
        Returns:
            True  → 加锁成功，本次请求为新请求，正常处理
            False → 锁已存在，本次请求为重复请求，应当丢弃
        """
        try:
            r = get_redis()
            key = self._key_dedup(device_id, query)
            # SET key "1" EX 2 NX：若 key 不存在则设置（原子操作）
            result = await r.set(key, "1", ex=TTL_DEDUP, nx=True)
            is_new = result is not None  # NX 成功时返回 True，已存在时返回 None
            if not is_new:
                logger.info(f"[Redis] dedup.blocked device={device_id} query='{query[:20]}'")
            return is_new
        except Exception as e:
            logger.error(f"[Redis] try_dedup failed (degraded, allow): {e}")
            return True  # Redis 故障时默认放行，不阻断主流程

    # ── 健康检查 ────────────────────────────

    async def ping(self) -> bool:
        """检查 Redis 连接是否正常"""
        try:
            r = get_redis()
            result = await r.ping()
            return result is True
        except Exception:
            return False


# ── 全局单例 ────────────────────────────────
redis_client = RedisClient()
