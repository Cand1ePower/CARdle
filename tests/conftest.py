"""
CARdle pytest 全局 Fixtures
============================
提供各层测试共用的基础设施：
  - 服务就绪检测（自动 skip，避免集成测试因服务未启动而报错）
  - 唯一 trace_id 生成器
  - 报告目录初始化
"""

import uuid
from pathlib import Path

import httpx
import pytest


# ───────────────────────────────────────────────
# 基础配置
# ───────────────────────────────────────────────

GATEWAY_URL = "http://127.0.0.1:8000"
GEMMA_NLU_URL = "http://127.0.0.1:8011"


# ───────────────────────────────────────────────
# 工具 Fixtures
# ───────────────────────────────────────────────

@pytest.fixture
def trace_id(request) -> str:
    """为每个测试函数生成唯一 trace_id，便于日志追踪和串场验证。"""
    safe_name = request.node.name.replace("[", "_").replace("]", "")
    return f"test_{safe_name}_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def scratch_dir() -> Path:
    """确保 scratch/ 目录存在并返回路径（用于保存测试报告）。"""
    repo_root = Path(__file__).resolve().parent
    scratch = repo_root / "scratch"
    scratch.mkdir(exist_ok=True)
    return scratch


# ───────────────────────────────────────────────
# 服务就绪检测 Fixtures（集成/E2E 测试使用）
# ───────────────────────────────────────────────

def _check_http(url: str, description: str):
    """检测 HTTP 服务是否可达，不可达则 skip 整组测试。"""
    try:
        resp = httpx.get(url + "/health", timeout=3.0)
        if resp.status_code not in (200, 404):  # 404 也说明服务在跑
            pytest.skip(f"{description} 返回非预期状态码 {resp.status_code}，请先启动服务")
    except Exception as exc:
        pytest.skip(f"{description} 不可达（{exc}），请先运行 python tools/runner.py")


@pytest.fixture(scope="session")
def require_gateway():
    """
    集成测试前置条件：验证主网关 (8000) 已启动。
    Usage:
        def test_something(require_gateway): ...
    """
    _check_http(GATEWAY_URL, "主网关 (8000)")


@pytest.fixture(scope="session")
def require_gemma_nlu():
    """
    集成测试前置条件：验证 Gemma NLU 服务 (8011) 已启动。
    Usage:
        def test_something(require_gemma_nlu): ...
    """
    try:
        resp = httpx.get(GEMMA_NLU_URL + "/docs", timeout=3.0)
        if resp.status_code != 200:
            pytest.skip("Gemma NLU 服务 (8011) 未就绪")
    except Exception as exc:
        pytest.skip(f"Gemma NLU 服务 (8011) 不可达（{exc}）")
