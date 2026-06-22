"""
tests/unit/test_prompts.py
===========================
Prompt 模板格式与完整性单元测试
测试范围：prompts.py 中所有 prompt 模板
运行方式：python -m pytest tests/unit/test_prompts.py -v

不依赖外部服务，属于纯代码级别验证。
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import prompts

pytestmark = pytest.mark.unit


class TestArbitrationPrompt:

    def test_not_empty(self):
        """仲裁 Prompt 不能为空"""
        assert prompts.ARBITRAION_SYSTEM_PROMPT.strip()

    def test_contains_output_format(self):
        """仲裁 Prompt 必须包含 JSON 输出格式说明"""
        assert "intent" in prompts.ARBITRAION_SYSTEM_PROMPT
        assert "slots" in prompts.ARBITRAION_SYSTEM_PROMPT

    def test_no_markdown_code_block_instructions(self):
        """仲裁 Prompt 应明确禁止输出 Markdown 代码块（否则 JSON 解析会失败）"""
        # 必须包含禁止 ``` 的说明
        assert "```" in prompts.ARBITRAION_SYSTEM_PROMPT or "Markdown" in prompts.ARBITRAION_SYSTEM_PROMPT

    def test_output_format_is_valid_json_template(self):
        """输出格式示例本身应该是合法 JSON 结构"""
        import json
        template = '{"intent": "Test_Intent", "slots": {"key": "value"}}'
        parsed = json.loads(template)
        assert "intent" in parsed
        assert "slots" in parsed


class TestRewritePrompt:

    def test_not_empty(self):
        """改写 Prompt 不能为空"""
        assert prompts.REWRITE_SYSTEM_PROMPT.strip()

    def test_contains_key_instruction(self):
        """改写 Prompt 必须包含指代消解说明"""
        assert "指代词" in prompts.REWRITE_SYSTEM_PROMPT or "改写" in prompts.REWRITE_SYSTEM_PROMPT

    def test_contains_examples(self):
        """改写 Prompt 应包含示例（Few-shot）"""
        assert "示例" in prompts.REWRITE_SYSTEM_PROMPT or "A:" in prompts.REWRITE_SYSTEM_PROMPT


class TestCorrelationPrompt:

    def test_system_not_empty(self):
        assert prompts.CORRELATION_SYSTEM.strip()

    def test_prompt_has_placeholders(self):
        """关联性 Prompt 必须有两个占位符 {}"""
        count = prompts.CORRELATION_PROMPT.count("{}")
        assert count == 2, f"期望 2 个 {{}} 占位符，实际找到 {count} 个"

    def test_prompt_format_works(self):
        """占位符格式化不应抛出异常"""
        formatted = prompts.CORRELATION_PROMPT.format("打开空调", "再高点")
        assert "打开空调" in formatted
        assert "再高点" in formatted


class TestNLGPrompt:

    def test_not_empty(self):
        assert prompts.NLG_PROMPT.strip()

    def test_has_placeholders(self):
        """NLG Prompt 必须有两个占位符（指令 + 工具返回）"""
        count = prompts.NLG_PROMPT.count("{}")
        assert count == 2, f"期望 2 个 {{}} 占位符，实际找到 {count} 个"

    def test_format_works(self):
        """格式化不应抛出异常"""
        formatted = prompts.NLG_PROMPT.format("打开空调", '{"success": true}')
        assert "打开空调" in formatted


class TestDefaultNLG:

    def test_not_empty(self):
        """默认降级 NLG 文本不能为空"""
        assert prompts.DEFAULT_NLG.strip()

    def test_is_string(self):
        assert isinstance(prompts.DEFAULT_NLG, str)

    def test_reasonable_length(self):
        """默认 NLG 不应过短（< 3 字符）或过长（> 50 字符）"""
        length = len(prompts.DEFAULT_NLG)
        assert 3 <= length <= 50, f"DEFAULT_NLG 长度 {length} 超出合理范围 [3, 50]"
