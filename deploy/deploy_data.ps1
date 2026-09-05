# 部署助手：将本地最新 app.db 同步到 nplcn 服务器（香港 47.82.68.246）
# 用法（先在下方填好 SSH 密码或用 ssh-agent/密钥）：
#   本机:  pwsh .\deploy_data.ps1  （会把 app.db 传到 /tmp/zxf-data/ 并灌入卷 zxf-data）
# 前置：代码已 push 到 github（本脚本不含代码更新，代码走服务器 git pull 或 scp）
param(
  [string]$Host_ = "47.82.68.246",
  [string]$User = "root"
)
$ErrorActionPreference = "Stop"
$proj = "Q:\deepseek\zichanxianfeng"
$db = Join-Path $proj "backend\data\app.db"

Write-Host "[1/4] 本地校验 app.db 存在" -ForegroundColor Cyan
if (-not (Test-Path $db)) { throw "app.db 不存在: $db" }
$size = (Get-Item $db).Length
Write-Host "  app.db $([math]::Round($size/1MB,2)) MB"

Write-Host "[2/4] 上传 app.db 到服务器 /tmp/zxf-data/" -ForegroundColor Cyan
# 需要交互式密码或已配置密钥；若无法交互请改用 sshpass 或先在 ssh-agent 加载密钥
ssh -o StrictHostKeyChecking=accept-new "${User}@${Host_}" "mkdir -p /tmp/zxf-data"
scp $db "${User}@${Host_}:/tmp/zxf-data/app.db"

Write-Host "[3/4] 服务器: 灌入 zxf-data 卷（先停容器防写冲突）" -ForegroundColor Cyan
ssh "${User}@${Host_}" "cd /opt/zichanxianfeng && docker compose -f deploy/docker-compose.yml down && docker run --rm -v zxf-data:/data -v /tmp/zxf-data:/src alpine sh -c 'cp -a /src/. /data/' && docker compose -f deploy/docker-compose.yml up -d"

Write-Host "[4/4] 健康检查" -ForegroundColor Cyan
Start-Sleep -Seconds 6
ssh "${User}@${Host_}" "curl -s http://127.0.0.1:8000/api/health"
Write-Host ""
Write-Host "完成。若容器内 app.db 权限/属主异常，可执行: docker exec zxf chown -R 1000:1000 /app/backend/data" -ForegroundColor Green
