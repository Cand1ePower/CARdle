#!/bin/bash
# =============================================================
# CARdle 微服务启动脚本 (Ubuntu / Linux)
# =============================================================
# 一次性拉起所有微服务 + 主网关，支持 systemd 或直接运行
#
# 使用方式:
#   chmod +x deploy/start_services.sh
#   ./deploy/start_services.sh
# =============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

echo "=================================================="
echo "  CARdle 微服务集群启动"
echo "  根目录: $ROOT_DIR"
echo "=================================================="

# 检查 .env 文件
if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "  ⚠️  未找到 .env 文件！请先执行:"
    echo "     cp .env.example .env && nano .env"
    exit 1
fi

# 函数：后台启动微服务
start_service() {
    local name=$1
    local script=$2
    local port=$3

    # 检测端口是否已在用
    if lsof -Pi :$port -sTCP:LISTEN -t > /dev/null 2>&1; then
        echo "  [SKIP] $name 已在端口 $port 运行"
        return
    fi

    echo "  [START] 启动 $name (端口 $port)..."
    nohup $VENV_PYTHON "$ROOT_DIR/$script" \
        > "$LOG_DIR/${name}.log" 2>&1 &
    echo $! > "$LOG_DIR/${name}.pid"
    echo "         PID=$(cat $LOG_DIR/${name}.pid) 日志: $LOG_DIR/${name}.log"
}

echo ""
echo "── 启动周边微服务 ──────────────────────────────"
start_service "rewrite"       "client/rewrite.py"              8006
start_service "reject"        "train/reject_infer.py"          8007
start_service "arbitration"   "client/arbitration.py"          8008
start_service "correlation"   "client/correlation.py"          8009
start_service "chatnlu_infer" "function_call/chatnlu_infer.py" 8015

echo ""
echo "── 等待微服务就绪 (5秒) ────────────────────────"
sleep 5

echo ""
echo "── 启动核心网关 (前台运行，Ctrl+C 停止) ────────"
echo "  日志同时输出到: $LOG_DIR/gateway.log"
echo ""

cd "$ROOT_DIR"
source .venv/bin/activate

$VENV_PYTHON -m uvicorn server:combined_app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info \
    2>&1 | tee "$LOG_DIR/gateway.log"
