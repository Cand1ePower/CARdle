#!/bin/bash
# =============================================================
# CARdle Ubuntu 服务器一键部署脚本
# =============================================================
# 使用方式:
#   chmod +x deploy/setup_ubuntu.sh
#   ./deploy/setup_ubuntu.sh
#
# 适用系统: Ubuntu 20.04 / 22.04 / 24.04 LTS
# =============================================================

set -e  # 任何命令失败立即退出

echo "=================================================="
echo "  CARdle 智能座舱网关 - Ubuntu 部署脚本"
echo "=================================================="

# ── Step 1: 更新系统包 ──────────────────────────────
echo ""
echo "[1/6] 更新系统包..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv git curl 2>&1 | tail -5

# ── Step 2: 安装 Redis ──────────────────────────────
echo ""
echo "[2/6] 安装 Redis 服务器..."
sudo apt-get install -y redis-server

# 配置 Redis：修改 bind 地址（仅本地）和持久化策略
sudo tee -a /etc/redis/redis.conf > /dev/null << 'EOF'

# CARdle 自定义配置
maxmemory 256mb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
EOF

sudo systemctl enable redis-server   # 开机自启
sudo systemctl start redis-server
echo "  ✓ Redis 已启动: $(redis-cli ping)"

# ── Step 3: 创建 Python 虚拟环境 ─────────────────────
echo ""
echo "[3/6] 创建 Python 虚拟环境..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q

# ── Step 4: 安装 Python 依赖 ──────────────────────────
echo ""
echo "[4/6] 安装 Python 依赖..."
pip install -r requirements.txt -q
echo "  ✓ Python 依赖安装完成"

# ── Step 5: 初始化数据库 ──────────────────────────────
echo ""
echo "[5/6] 初始化 SQLite 数据库..."
python db/seed.py
echo "  ✓ 数据库初始化完成"

# ── Step 6: 验证配置 ──────────────────────────────────
echo ""
echo "[6/6] 验证部署环境..."
echo -n "  Redis: "
redis-cli ping
echo -n "  Python: "
python --version
echo -n "  FastAPI: "
python -c "import fastapi; print(fastapi.__version__)"

echo ""
echo "=================================================="
echo "  ✅ 部署完成！启动服务请运行："
echo ""
echo "  # 1. 复制并填写配置:"
echo "  cp .env.example .env && nano .env"
echo ""
echo "  # 2. 启动所有微服务 (推荐):"
echo "  ./deploy/start_services.sh"
echo ""
echo "  # 或手动启动网关:"
echo "  source .venv/bin/activate"
echo "  uvicorn server:combined_app --host 0.0.0.0 --port 8000"
echo "=================================================="
