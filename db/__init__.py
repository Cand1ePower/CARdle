"""
CARdle 持久化层统一入口
========================
提供两个核心接口：
  - get_redis()  : 获取 Redis 异步连接（内存层，高速 KV）
  - get_db()     : 获取 SQLite 异步连接（持久层，关系型档案）

使用方式：
  from db import get_redis, get_db
"""

from db.redis_client import get_redis, RedisClient
from db.sqlite_client import get_db, init_db

__all__ = ["get_redis", "get_db", "init_db", "RedisClient"]
