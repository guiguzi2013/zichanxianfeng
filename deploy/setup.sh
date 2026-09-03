#!/bin/bash
# ============================================================
# 资产先锋 · 服务器一键部署（Ubuntu/Debian，Docker 单容器形态）
# 用法：
#   1) 把整个项目上传到服务器（保留 frontend/dist 最新构建）：
#      scp -r zichanxianfeng root@<服务器IP>:/opt/
#   2) sudo bash /opt/zichanxianfeng/deploy/setup.sh
# 访问：http://<服务器IP>:8000
# 香港服务器临时展示无需备案；正式上线迁回国内后再走 nginx+HTTPS（见说明文档）。
# ============================================================
set -euo pipefail

echo "==== 资产先锋部署脚本（Docker 单容器） ===="

# ---------- 1. 系统依赖 ----------
echo "[1/5] 安装 Docker..."
apt-get update -y
if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y docker.io docker-compose-v2 || apt-get install -y docker.io
fi
systemctl enable docker
systemctl start docker

# ---------- 2. 定位项目 ----------
DEPLOY_DIR="/opt/zichanxianfeng"
if [ ! -f "$DEPLOY_DIR/deploy/Dockerfile" ]; then
  echo "错误：未找到 $DEPLOY_DIR/deploy/Dockerfile"
  echo "请先上传：scp -r zichanxianfeng root@<IP>:/opt/   （目录名须为 zichanxianfeng）"
  exit 1
fi
cd "$DEPLOY_DIR"

# ---------- 3. 环境变量 ----------
echo "[2/5] 配置环境变量..."
if [ ! -f deploy/.env ]; then
  cp deploy/.env.example deploy/.env
  echo "已创建 deploy/.env —— 请编辑填写真实值后重新执行本脚本："
  echo "  SECRET_KEY       （服务器执行：openssl rand -hex 32）"
  echo "  DEEPSEEK_API_KEY （真实 LLM；留空则演示模式 LLM_MOCK=true）"
  echo "  QCC_TOKEN        （企查查；留空则回退代码内旧 token）"
  exit 0
fi

# ---------- 4. 前端 dist 检查 ----------
echo "[3/5] 检查前端构建产物..."
if [ ! -d frontend/dist ]; then
  echo "错误：缺少 frontend/dist —— 请在本机（Windows）构建后上传："
  echo "  cd frontend && npm run build"
  echo "  scp -r frontend/dist root@<IP>:/opt/zichanxianfeng/frontend/"
  exit 1
fi

# ---------- 5. 构建并启动 ----------
echo "[4/5] docker compose 构建镜像（首次较慢：pip + chromium 下载）..."
docker compose -f deploy/docker-compose.yml build

echo "[5/5] 启动服务..."
docker compose -f deploy/docker-compose.yml up -d

echo ""
echo "==== 部署完成 ===="
IP=$(hostname -I | awk '{print $1}')
echo "访问：http://$IP:8000  （健康检查：http://$IP:8000/api/health）"
echo "日志：docker compose -f deploy/docker-compose.yml logs -f"
echo ""
echo "数据迁移（把本机现有 app.db/uploads 带过去，可选）："
echo "  本机打包 backend/data → 服务器 docker run --rm -v zxf-data:/data -v \$PWD:/out alpine tar xzf 迁移包 -C /data"
echo "  详见 deploy/部署与迁移说明.md"
