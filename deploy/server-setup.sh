#!/usr/bin/env bash
# server-setup.sh — MyQuant 腾讯云 Ubuntu 22.04 初始化脚本
# 使用方式: 以 root 身份运行 bash server-setup.sh
# 预计耗时: 15-30 分钟（取决于网络速度）

set -euo pipefail

APP_DIR="/app/my_quant"
APP_USER="myquant"
NODE_VERSION="20"

echo "========================================"
echo " MyQuant 服务器初始化"
echo " 目标目录: $APP_DIR"
echo " 应用用户: $APP_USER"
echo "========================================"

# ── 1. 系统更新 ──────────────────────────────
echo "[1/9] 更新系统包..."
apt-get update -q
apt-get upgrade -y -q

# ── 2. 基础工具 ──────────────────────────────
echo "[2/9] 安装基础工具..."
apt-get install -y -q \
    curl wget git build-essential \
    python3 python3-venv python3-dev python3-pip \
    nginx \
    libssl-dev libffi-dev \
    htop unzip

# ── 3. Node.js 20 ────────────────────────────
echo "[3/9] 安装 Node.js $NODE_VERSION..."
curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash -
apt-get install -y nodejs
node --version
npm --version

# ── 4. 创建应用用户和目录 ────────────────────
echo "[4/9] 创建用户和目录..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /bin/bash --create-home --home-dir /home/$APP_USER "$APP_USER"
    echo "  用户 $APP_USER 已创建"
else
    echo "  用户 $APP_USER 已存在，跳过"
fi

mkdir -p "$APP_DIR"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
mkdir -p /var/log/myquant
chown -R "$APP_USER":"$APP_USER" /var/log/myquant

echo ""
echo "========================================"
echo " 下一步: 上传代码和数据"
echo "========================================"
echo ""
echo "在本机（Windows）执行:"
echo "  powershell scripts\\upload.ps1 -ServerIP <公网IP>"
echo ""
echo "然后回到服务器继续执行 server-setup-2.sh"
echo ""
