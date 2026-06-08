"""
CARdle Pydantic 数据模型定义
=============================
定义系统中所有核心数据实体的结构，用于：
  - SQLite 读写时的类型校验与序列化
  - API 层请求/响应的数据约束
  - Redis Hash 字段的结构文档化
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import json


# ────────────────────────────────────────────
# SQLite 持久层模型
# ────────────────────────────────────────────

class User(BaseModel):
    """车主用户档案（永久存储在 SQLite）"""
    user_id: str                            # uuid4 主键
    name: str                               # 车主姓名
    phone: Optional[str] = None             # 手机号（脱敏）
    created_at: str                         # ISO8601 注册时间
    preferences: dict = Field(default_factory=dict)  # 个性化偏好（默认城市等）

    def preferences_json(self) -> str:
        return json.dumps(self.preferences, ensure_ascii=False)


class Device(BaseModel):
    """车辆设备注册档案（永久存储在 SQLite）"""
    device_id: str                          # 车机唯一 ID（形如 CARDLE_VIN_001）
    user_id: str                            # 绑定车主的 user_id
    vin: Optional[str] = None              # 17 位 VIN 码
    model: Optional[str] = None            # 车型（Model 3 / Y 等）
    nickname: Optional[str] = None         # 车主给车起的昵称（如"小白"）
    registered_at: str                      # ISO8601 注册时间
    last_seen_at: Optional[str] = None     # 最后一次在线时间


class AuditLog(BaseModel):
    """每次对话请求的操作审计日志（永久存储在 SQLite）"""
    trace_id: str                           # 与网关 trace_id 对齐
    device_id: Optional[str] = None        # 来源车机 ID
    intent: Optional[str] = None           # 识别到的意图中文名
    function: Optional[str] = None         # 执行的功能函数名
    slots: dict = Field(default_factory=dict)  # NLU 提取的槽位
    nlg_output: Optional[str] = None       # 返回给用户的最终话术
    cost_ms: Optional[float] = None        # 端到端耗时（毫秒）
    created_at: str                         # ISO8601 发生时间

    def slots_json(self) -> str:
        return json.dumps(self.slots, ensure_ascii=False)


# ────────────────────────────────────────────
# Redis 内存层模型
# ────────────────────────────────────────────

class ConversationTurn(BaseModel):
    """单轮对话条目（存入 Redis List 的每一项）"""
    role: str                               # "user" 或 "assistant"
    content: str                            # 对话内容
    ts: int                                 # Unix 时间戳
    metadata: dict = Field(default_factory=dict)  # 结构化上下文，如 intent/slots/rewritten_query

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "ConversationTurn":
        return cls.model_validate_json(json_str)


class VehicleState(BaseModel):
    """车辆实时硬件状态（存入 Redis Hash）"""
    ac_temperature: str = "24.0"            # 当前空调温度（摄氏度）
    ac_mode: str = "auto"                   # 空调模式 (auto/cooling/heating/off)
    volume: str = "50"                      # 当前音量 (0-100)
    window_fl: str = "closed"              # 左前窗（closed/open）
    window_fr: str = "closed"              # 右前窗
    window_rl: str = "closed"              # 左后窗
    window_rr: str = "closed"              # 右后窗
    seat_heat_driver: str = "off"          # 主驾座椅加热 (off/low/mid/high)
    seat_heat_passenger: str = "off"       # 副驾座椅加热
    seat_vent_driver: str = "off"          # 主驾座椅通风 (off/low/high)
    last_domain: str = ""                   # 上一次交互所属领域
    last_query: str = ""                    # 上一次改写后的指令文本
    last_answer: str = ""                   # 上一次车机播报的话术

    def to_dict(self) -> dict:
        """转换为 Redis HSET 所需的字符串字典"""
        return {k: str(v) for k, v in self.model_dump().items()}

    @classmethod
    def from_dict(cls, d: dict) -> "VehicleState":
        return cls(**d)
