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

from .api import admin, auth, activity, claims, clues, compare, dashboard, debtor_profile, feed, feedback, knowledge, land_price, notices, qcc, reports, tasks, valuation
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


app = FastAPI(title="NPL中国平台 API", version="0.1.0", lifespan=lifespan)

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


# 员工/管理员与普通用户分离：员工账号仅用于后台管理，不能调用前台用户业务接口
# 例外：GET /api/reports/{task_id} 允许员工查看用户报告（处理投诉）；下载/生成/补充材料仍拦截
_FRONTEND_API_PREFIXES = ("/api/claims", "/api/tasks", "/api/valuation", "/api/clues", "/api/compare", "/api/activity", "/api/land-price/match")
_FRONTEND_READ_ALLOWED = ("/api/reports/",)


@app.middleware("http")
async def block_staff_frontend_api(request: Request, call_next):
    path = request.url.path
    blocked = any(path.startswith(p) for p in _FRONTEND_API_PREFIXES)
    # reports：GET 列表/详情（读）放行；POST（生成PDF/补充材料）、GET pdf/download 拦截
    if path.startswith("/api/reports/"):
        if request.method == "GET" and not path.endswith("/pdf/download"):
            blocked = False
        else:
            blocked = True
    if blocked:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                from .services.security import decode_token
                payload = decode_token(auth[7:])
                if payload:
                    role = payload.get("role")
                    if role in ("editor", "admin"):
                        return JSONResponse(status_code=403, content={"code": 1, "message": "员工账号仅用于管理后台，不能使用前台用户功能"})
            except Exception:  # noqa: BLE001
                pass
    return await call_next(request)


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
app.include_router(valuation.router, prefix="/api")
app.include_router(activity.router, prefix="/api")
app.include_router(land_price.router, prefix="/api")
app.include_router(debtor_profile.router, prefix="/api")

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
        # 2026-09-02：index.html 不缓存（no-cache），保证前端构建后用户刷新即拿到新版本
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})

    logging.info("前端已挂载：%s（单进程模式，访问 http://127.0.0.1:8000）", FRONTEND_DIST)
else:
    logging.info("未找到前端构建产物 %s，仅提供 API（开发模式请另跑 npm run dev）", FRONTEND_DIST)
