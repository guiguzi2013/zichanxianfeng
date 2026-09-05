# ============================================================
# 资产先锋（zichanxianfeng）单镜像
#   后端 FastAPI + 前端静态(dist) + Chromium 抓取(Playwright) + 附件 OCR
# 使用前：本地先 `npm run build`（frontend/dist 需为最新构建）
# 部署：cd deploy && docker compose up -d --build
# 注：国内服务器构建需配置镜像加速（见 deploy/部署与迁移说明.md）
# ============================================================
# 注：python 3.13 会拒绝 rapidocr-onnxruntime==1.4.4(Requires-Python <3.13)，用 3.12
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 1) 系统层：中文字体（PDF 报告 reportlab 需要 Noto CJK；方正小标宋走 data/fonts 种子）
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 2) Python 依赖 + Playwright Chromium（--with-deps 自动装浏览器系统库）
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/backend/requirements.txt \
    && playwright install --with-deps chromium

# 3) 应用代码（.dockerignore 已排除 app.db/uploads/pdf/.venv/node_modules）
COPY backend /app/backend
# 前端构建产物（本地已 npm run build）
COPY frontend/dist /app/frontend/dist

# 4) 项目字体目录 font/（fzxbs.ttf/msyh.ttc/msyhbd.ttc/simsun.ttc，英文名）
#    COPY 到卷外 /app/font：docker-compose 的命名卷 zxf-data 挂载 /app/backend/data，
#    旧卷会掩盖镜像内 data 下新增文件；字体放卷外路径，pdf_generator._proj() 优先取它
COPY font /app/font

WORKDIR /app/backend
EXPOSE 8000

# 单进程托管：后端直接服务前端静态 + API（与 Windows 本地形态一致）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
