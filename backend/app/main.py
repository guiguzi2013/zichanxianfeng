"""FastAPI 应用入口

启动：uvicorn app.main:app --reload
单进程模式：若存在 frontend/dist，则后端直接托管前端（生产形态，无需另跑 Vite）。
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, auth, claims, clues, compare, dashboard, feed, feedback, knowledge, notices, qcc, reports, tasks
from .database import Base, engine
from . import models  # noqa: F401  确保模型注册

logging.basicConfig(level=logging.INFO)

# 前端构建产物目录（相对 backend/ 的 ../frontend/dist）
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 开发期自动建表；生产用 Alembic 迁移
    Base.metadata.create_all(bind=engine)
    # 知识库种子（首次启动）
    from .services.knowledge_seed import seed_knowledge
    seed_knowledge()
    yield


app = FastAPI(title="资产先锋平台 API", version="0.1.0", lifespan=lifespan)

# CORS：开发期允许前端 dev server；生产由 Nginx 同源代理
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"code": 500, "message": "服务器内部错误", "data": None})


@app.get("/api/health", tags=["system"])
def health():
    return {"code": 0, "message": "ok", "data": {"status": "alive"}}


app.include_router(auth.router, prefix="/api")
app.include_router(claims.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(feed.router, prefix="/api")
app.include_router(compare.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(qcc.router, prefix="/api")
app.include_router(notices.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(clues.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")

# ---- 单进程模式：后端托管前端构建产物（若存在）----
if FRONTEND_DIST.exists():
    # 静态资源（JS/CSS/图片等）
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """SPA 路由回退：非 /api 路径一律返回 index.html（前端路由处理）"""
        candidate = FRONTEND_DIST / full_path
        # 若请求的是存在的静态文件（如 favicon），直接返回
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

    logging.info("前端已挂载：%s（单进程模式，访问 http://127.0.0.1:8000）", FRONTEND_DIST)
else:
    logging.info("未找到前端构建产物 %s，仅提供 API（开发模式请另跑 npm run dev）", FRONTEND_DIST)
