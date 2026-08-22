# ============================================================
# 资产先锋 · Zeabur / 通用容器部署（多阶段构建，单进程模式）
# Stage 1: Node 构建前端 → dist
# Stage 2: Python 运行后端，托管 dist（与本地单进程模式一致）
# 不改业务代码，仅部署配置。
# ============================================================

# ---------- Stage 1：构建前端 ----------
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2：后端运行 ----------
FROM python:3.11-slim

WORKDIR /app

# WeasyPrint 系统依赖（中文字体 + 渲染库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# 前端构建产物 → 单进程模式期望路径（main.py 按 __file__ 三级上溯找 /frontend/dist）
COPY --from=frontend-build /build/dist /frontend/dist

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
