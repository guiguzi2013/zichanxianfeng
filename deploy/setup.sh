#!/bin/bash
# ============================================================
# 资产先锋 · 服务器一键部署脚本（Ubuntu/Debian）
# 用法：
#   sudo bash deploy/setup.sh
# 前置：域名已解析到本机、已 ICP 备案（未备案 80/443 会被封）
# ============================================================
set -euo pipefail

echo "==== 资产先锋部署脚本 ===="

# ---------- 1. 系统依赖 ----------
echo "[1/6] 安装系统依赖..."
apt-get update -y
apt-get install -y curl git docker.io docker-compose-v2 nginx

# ---------- 2. Docker 服务 ----------
echo "[2/6] 启用 Docker..."
systemctl enable docker
systemctl start docker

# ---------- 3. 拉取代码（若尚未存在） ----------
DEPLOY_DIR="/opt/zichanxianfeng"
if [ ! -d "$DEPLOY_DIR/deploy" ]; then
  echo "[3/6] 请先将项目代码上传到 $DEPLOY_DIR（例如 scp -r zichanxianfeng root@服务器:$DEPLOY_DIR）"
  echo "      或设置 GIT_REPO 环境变量自动拉取："
  echo "      export GIT_REPO=https://your-git-repo.git && sudo bash deploy/setup.sh"
  if [ -n "${GIT_REPO:-}" ]; then
    git clone "$GIT_REPO" "$DEPLOY_DIR"
  else
    echo "错误：未找到代码目录且未设置 GIT_REPO"
    exit 1
  fi
fi
cd "$DEPLOY_DIR"

# ---------- 4. 环境变量 ----------
echo "[4/6] 配置环境变量..."
if [ ! -f deploy/.env ]; then
  cp deploy/.env.example deploy/.env
  echo "已创建 deploy/.env，请编辑填写："
  echo "  - SECRET_KEY（openssl rand -hex 32 生成）"
  echo "  - DEEPSEEK_API_KEY"
  echo "  - 域名相关（nginx 配置）"
  echo "按任意键继续（或 Ctrl+C 编辑后重跑）..."
  read -r _
fi

# ---------- 5. 前端构建 ----------
echo "[5/6] 构建前端..."
if command -v node >/dev/null 2>&1; then
  cd frontend
  npm install --registry=https://registry.npmmirror.com
  npm run build
  cd ..
else
  echo "警告：服务器未装 Node，跳过前端构建。请在本机构建后把 frontend/dist 传到服务器。"
fi

# ---------- 6. HTTPS 证书 ----------
echo "[6/6] 申请 HTTPS 证书（如已配置域名）..."
DOMAIN="${DOMAIN:-}"
if [ -n "$DOMAIN" ]; then
  # 先启动 nginx（http 模式）供验证
  docker compose -f deploy/docker-compose.yml up -d nginx
  sleep 3
  docker compose -f deploy/docker-compose.yml run --rm certbot certonly \
    --webroot -w /var/www/certbot -d "$DOMAIN" --email "${ADMIN_EMAIL:-admin@example.com}" \
    --agree-tos --no-eff-email || echo "证书申请失败，可稍后手动执行"
  # 替换 nginx 配置为 https 模式（部署时按需调整）
fi

# ---------- 启动 ----------
echo "启动服务..."
docker compose -f deploy/docker-compose.yml up -d --build

echo ""
echo "==== 部署完成 ===="
echo "服务地址：http://$(hostname -I | awk '{print $1}')"
echo "如需 HTTPS，请配置 DOMAIN 环境变量后重跑证书步骤。"
