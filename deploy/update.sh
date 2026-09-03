#!/bin/bash
# ============================================================
# NPL中国 · 服务器一键更新（git pull + 重建镜像 + 重启）
# 用法：sudo bash /opt/zichanxianfeng/deploy/update.sh
# 前置：首次部署已由 setup.sh 完成（含 deploy/.env 与数据卷）
# 日常迭代：本地 git commit/push → 服务器跑本脚本
# ============================================================
set -euo pipefail

cd /opt/zichanxianfeng

echo "[1/3] 拉取最新代码..."
git pull origin main

if [ ! -f deploy/.env ]; then
  echo "错误：缺少 deploy/.env —— 首次部署请先执行 deploy/setup.sh"
  exit 1
fi

echo "[2/3] 重新构建镜像（前端 dist 已随仓库，无需服务器装 node）..."
docker compose -f deploy/docker-compose.yml build

echo "[3/3] 重启服务..."
docker compose -f deploy/docker-compose.yml up -d

echo ""
echo "==== 更新完成 ===="
echo "健康检查：curl http://127.0.0.1:8000/api/health"
