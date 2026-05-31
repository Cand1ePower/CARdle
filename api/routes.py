from fastapi import APIRouter
from db.redis_client import redis_client
from db.sqlite_client import sqlite_client

router = APIRouter()

@router.get("/health")
async def health_check():
    redis_ok = await redis_client.ping()
    return {
        "status": "healthy",
        "service": "CARdle",
        "version": "2.0.0",
        "redis": "connected" if redis_ok else "degraded",
    }

@router.get("/api/device/{device_id}")
async def get_device_info(device_id: str):
    """查询车辆档案（含实时状态）"""
    device = await sqlite_client.get_device(device_id)
    if not device:
        return {"error": f"设备 {device_id} 未注册"}
    state = await redis_client.get_vehicle_state(device_id)
    history = await redis_client.get_history(device_id)
    return {
        "device": device.model_dump(),
        "realtime_state": state.model_dump(),
        "recent_history_turns": len(history),
    }

@router.get("/api/device/{device_id}/audit")
async def get_device_audit(device_id: str, limit: int = 10):
    """查询车辆最近的操作审计日志"""
    logs = await sqlite_client.get_recent_audit(device_id, limit)
    return {"device_id": device_id, "count": len(logs), "logs": logs}
