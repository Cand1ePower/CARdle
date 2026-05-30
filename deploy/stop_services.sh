#!/bin/bash
# =============================================================
# CARdle 微服务停止脚本 (Ubuntu / Linux)
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$ROOT_DIR/logs"

echo "正在停止 CARdle 所有微服务..."

for pid_file in "$LOG_DIR"/*.pid; do
    if [ -f "$pid_file" ]; then
        service_name=$(basename "$pid_file" .pid)
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "  ✓ 已停止 $service_name (PID=$pid)"
        else
            echo "  ⚠ $service_name (PID=$pid) 已不在运行"
        fi
        rm "$pid_file"
    fi
done

echo "所有微服务已停止。"
