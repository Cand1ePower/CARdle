"""
tests/unit/test_mcp_tools.py
=============================
MCP 工具层单元测试
测试范围：空调控制、车窗控制、音量控制、工具分发器
运行方式：python -m pytest tests/unit/test_mcp_tools.py -v

不依赖任何外部服务，可随时独立运行。
"""

import sys
import os
import pytest

# 确保能导入根模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mcp_core.vehicle_tools import (
    set_ac_temperature,
    open_window,
    close_window,
    set_volume,
    get_vehicle_status,
)
from mcp_core.tool_dispatcher import dispatch_tool


pytestmark = pytest.mark.unit


# ───────────────────────────────────────────────
# 空调温度控制测试
# ───────────────────────────────────────────────

class TestSetAcTemperature:

    @pytest.mark.asyncio
    async def test_absolute_set(self):
        """绝对值设置：把空调设为 26 度"""
        result = await set_ac_temperature(temperature="26度")
        assert result["success"] is True
        assert result["当前温度"] == "26度"

    @pytest.mark.asyncio
    async def test_relative_up(self):
        """相对调整：升温（默认步长 2 度）"""
        await set_ac_temperature(temperature="26度")  # 先设基准
        result = await set_ac_temperature(adjust="up")
        assert result["success"] is True
        assert result["当前温度"] == "28度"

    @pytest.mark.asyncio
    async def test_relative_down(self):
        """相对调整：降温"""
        await set_ac_temperature(temperature="26度")
        result = await set_ac_temperature(adjust="down")
        assert result["success"] is True
        assert result["当前温度"] == "24度"

    @pytest.mark.asyncio
    async def test_chain_up_then_down(self):
        """链式操作：升温后再降温，应回到原值"""
        await set_ac_temperature(temperature="24度")
        await set_ac_temperature(adjust="up")
        result = await set_ac_temperature(adjust="down")
        assert result["当前温度"] == "24度"


# ───────────────────────────────────────────────
# 车窗控制测试
# ───────────────────────────────────────────────

class TestWindowControls:

    @pytest.mark.asyncio
    async def test_open_window(self):
        """开车窗"""
        result = await open_window()
        assert result["success"] is True
        assert "打开" in result["message"]

    @pytest.mark.asyncio
    async def test_close_window(self):
        """关车窗"""
        result = await close_window()
        assert result["success"] is True
        assert "关闭" in result["message"]

    @pytest.mark.asyncio
    async def test_open_then_close(self):
        """开后再关，两次都成功"""
        r1 = await open_window()
        r2 = await close_window()
        assert r1["success"] and r2["success"]


# ───────────────────────────────────────────────
# 音量控制测试
# ───────────────────────────────────────────────

class TestSetVolume:

    @pytest.mark.asyncio
    async def test_absolute_set(self):
        """绝对值设置音量"""
        result = await set_volume(level="30")
        assert result["success"] is True
        assert result["当前音量"] == 30

    @pytest.mark.asyncio
    async def test_relative_up(self):
        """音量调大"""
        await set_volume(level="30")
        result = await set_volume(level="up")
        assert result["success"] is True
        assert result["当前音量"] == 40

    @pytest.mark.asyncio
    async def test_relative_down(self):
        """音量调小"""
        await set_volume(level="30")
        result = await set_volume(level="down")
        assert result["success"] is True
        assert result["当前音量"] == 20


# ───────────────────────────────────────────────
# 工具分发器测试
# ───────────────────────────────────────────────

class TestToolDispatcher:

    @pytest.mark.asyncio
    async def test_dispatch_set_ac(self):
        """分发器：正确路由到空调控制"""
        result_str = await dispatch_tool("set_ac_temperature", {"temperature": "25度"})
        assert "25度" in result_str

    @pytest.mark.asyncio
    async def test_dispatch_open_window(self):
        """分发器：正确路由到车窗控制"""
        result_str = await dispatch_tool("open_window", {})
        assert "打开" in result_str

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self):
        """分发器：未注册的工具应返回空字符串，不报错"""
        result_str = await dispatch_tool("unknown_tool_xyz", {})
        assert result_str == ""

    @pytest.mark.asyncio
    async def test_dispatch_get_status(self):
        """分发器：获取车辆状态"""
        result_str = await dispatch_tool("get_vehicle_status", {})
        # 返回字符串中应包含状态信息
        assert isinstance(result_str, str)
        assert len(result_str) > 0
