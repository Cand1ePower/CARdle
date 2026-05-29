import asyncio
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 确保能导入模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_core.vehicle_tools import set_ac_temperature, open_window, close_window, set_volume, get_vehicle_status
from mcp_core.tool_dispatcher import dispatch_tool


class TestMCPTools(unittest.IsolatedAsyncioTestCase):

    async def test_set_ac_temperature(self):
        """测试空调温度设置"""
        res1 = await set_ac_temperature(temperature="26度")
        self.assertTrue(res1["success"])
        self.assertEqual(res1["当前温度"], "26度")

        res2 = await set_ac_temperature(adjust="up")
        self.assertTrue(res2["success"])
        self.assertEqual(res2["当前温度"], "28度")

        res3 = await set_ac_temperature(adjust="down")
        self.assertTrue(res3["success"])
        self.assertEqual(res3["当前温度"], "26度")

    async def test_window_controls(self):
        """测试车窗控制"""
        res1 = await open_window()
        self.assertTrue(res1["success"])
        self.assertEqual(res1["message"], "已为您打开车窗")

        res2 = await close_window()
        self.assertTrue(res2["success"])
        self.assertEqual(res2["message"], "已为您关闭车窗")

    async def test_set_volume(self):
        """测试音量控制"""
        res1 = await set_volume(level="30")
        self.assertTrue(res1["success"])
        self.assertEqual(res1["当前音量"], 30)

        res2 = await set_volume(level="up")
        self.assertTrue(res2["success"])
        self.assertEqual(res2["当前音量"], 40)

        res3 = await set_volume(level="down")
        self.assertTrue(res3["success"])
        self.assertEqual(res3["当前音量"], 30)

    async def test_tool_dispatcher(self):
        """测试工具分发器"""
        # 测试注册的工具能否正常调用
        res1_str = await dispatch_tool("set_ac_temperature", {"temperature": "25度"})
        self.assertIn("25度", res1_str)
        
        res2_str = await dispatch_tool("open_window", {})
        self.assertIn("已为您打开车窗", res2_str)

        # 测试未注册的工具
        res3_str = await dispatch_tool("unknown_tool", {})
        self.assertEqual(res3_str, "")

if __name__ == "__main__":
    unittest.main()
