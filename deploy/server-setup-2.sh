#!/usr/bin/env bash
# server-setup-2.sh — 代码上传完成后在服务器执行
# 使用方式: 以 root 身份运行 bash /app/my_quant/deploy/server-setup-2.sh

set -euo pipefail

APP_DIR="/app/my_quant"
APP_USER="myquant"
DEPLOY_DIR="$APP_DIR/deploy"

echo "[5/9] 创建 Python 虚拟环境并安装依赖..."
cd "$APP_DIR"
if [ ! -d ".venv" ]; then
    sudo -u "$APP_USER" python3 -m venv .venv
fi
sudo -u "$APP_USER" .venv/bin/pip install --upgrade pip -q
sudo -u "$APP_USER" .venv/bin/pip install -r deploy/requirements-deploy.txt

echo "[6/9] 构建 Next.js 前端..."
cd "$APP_DIR/frontend"
sudo -u "$APP_USER" npm install --prefer-offline
sudo -u "$APP_USER" npm run build
echo "  前端构建完成"

echo "[7/9] 配置 .env 文件..."
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'EOF'
# MyQuant 环境变量 — 请填写实际值
KIMI_API_KEY=
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=moonshot-v1-32k
DEEPSEEK_API_KEY=
AGENT_ACCESS_TOKEN=
AGENT_DEFAULT_PROVIDER=kimi
EOF
    chown "$APP_USER":"$APP_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "  .env 文件已创建，请编辑填写 API Key: nano $ENV_FILE"
fi

echo "[8/9] 安装 systemd 服务..."
cp "$DEPLOY_DIR/myquant-backend.service" /etc/systemd/system/
cp "$DEPLOY_DIR/myquant-frontend.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable myquant-backend myquant-frontend
systemctl start myquant-backend
sleep 5   # 等待后端就绪
systemctl start myquant-frontend

echo "[9/9] 配置 Nginx..."
cp "$DEPLOY_DIR/nginx.conf" /etc/nginx/sites-available/myquant
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/myquant /etc/nginx/sites-enabled/myquant
nginx -t
systemctl restart nginx
systemctl enable nginx

# ── 健康检查 ─────────────────────────────────
echo ""
echo "========================================"
echo " 健康检查..."
echo "========================================"
sleep 8

backend_ok=0
frontend_ok=0
nginx_ok=0

if curl -sf http://127.0.0.1:8000/docs > /dev/null 2>&1; then
    echo "  ✓ 后端 FastAPI   http://127.0.0.1:8000"
    backend_ok=1
else
    echo "  ✗ 后端异常  检查: journalctl -u myquant-backend -n 50"
fi

if curl -sf http://127.0.0.1:3000 > /dev/null 2>&1; then
    echo "  ✓ 前端 Next.js   http://127.0.0.1:3000"
    frontend_ok=1
else
    echo "  ✗ 前端异常  检查: journalctl -u myquant-frontend -n 50"
fi

PUBLIC_IP=$(curl -sf http://ipv4.icanhazip.com 2>/dev/null || echo "<公网IP>")
if curl -sf "http://$PUBLIC_IP" > /dev/null 2>&1; then
    echo "  ✓ Nginx 代理    http://$PUBLIC_IP"
    nginx_ok=1
else
    echo "  ✗ Nginx 异常  检查: nginx -t && systemctl status nginx"
fi

echo ""
if [ $backend_ok -eq 1 ] && [ $frontend_ok -eq 1 ] && [ $nginx_ok -eq 1 ]; then
    echo "  部署成功！访问: http://$PUBLIC_IP"
else
    echo "  部分服务异常，请检查上方日志"
fi

echo ""
echo "常用运维命令:"
echo "  systemctl status myquant-backend myquant-frontend nginx"
echo "  journalctl -u myquant-backend -f      # 查看后端实时日志"
echo "  journalctl -u myquant-frontend -f     # 查看前端实时日志"
echo "  systemctl restart myquant-backend     # 重启后端（代码更新后）"
