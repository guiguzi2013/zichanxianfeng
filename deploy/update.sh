#!/bin/bash
# ============================================================
# NPL中国 · 服务器一键更新（git pull + 重建镜像 + 重启）
# 用法：sudo bash /opt/zichanxianfeng/deploy/update.sh
# 前置：首次部署已由 setup.sh 完成（含 deploy/.env 与数据卷）
# 日常迭代：本地 git commit/push → 服务器跑本脚本
# ============================================================
set -euo pipefail

# 重要（2026-09-06 修复）：必须 cd 到 deploy/ 内再执行 compose，
# docker-compose.override.yml（zxf 加入 sub2api 网络供 Caddy 反代 nplcn.cn）
# 只在 cwd 含默认 compose 文件名时自动合并；在项目根用 -f 指定会跳过 override，
# 导致 zxf 掉出 sub2api_sub2api-network → https 502（曾真实发生）
cd /opt/zichanxianfeng/deploy

echo "[1/3] 拉取最新代码..."
git -C /opt/zichanxianfeng pull origin main

if [ ! -f .env ]; then
  echo "错误：缺少 deploy/.env —— 首次部署请先执行 deploy/setup.sh"
  exit 1
fi

echo "[2/3] 重新构建镜像（前端 dist 已随仓库，无需服务器装 node）..."
docker compose build

echo "[3/3] 重启服务（override 生效：zxf 保持接入 sub2api 网络）..."
docker compose up -d

echo ""
echo "==== 更新完成 ===="
echo "健康检查：curl http://127.0.0.1:8000/api/health"
echo "公网检查：curl https://nplcn.cn/api/health"
echo "网络自检：docker inspect zxf --format '{{range \$k,\$v := .NetworkSettings.Networks}}{{\$k}} {{end}}'  # 应含 sub2api_sub2api-network"
