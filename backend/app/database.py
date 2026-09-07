"""数据库引擎与会话管理（SQLAlchemy 2.0 + SQLite，P2 迁 PostgreSQL）"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()

# SQLite 相对路径（./data/app.db）锚定到后端包目录，避免受调用方 cwd 影响
if settings.database_url.startswith("sqlite:///./"):
    _base = Path(__file__).resolve().parent.parent  # backend/
    _rel = settings.database_url.replace("sqlite:///./", "", 1)
    settings.database_url = f"sqlite:///{(_base / _rel).as_posix()}"

# SQLite 需要 check_same_thread=False 供 FastAPI 多线程使用
if settings.database_url.startswith("sqlite"):
    # busy_timeout：材料识别后台任务与前台请求可能并发写库，等待而非立即报锁
    connect_args = {"check_same_thread": False, "timeout": 30}
    # SQLite 不会自动创建目录，启动前确保数据目录存在
    # 处理 sqlite:///./data/app.db 或 sqlite:////abs/path 形式
    db_path_str = settings.database_url.replace("sqlite:///", "", 1)
    if db_path_str and db_path_str != ":memory:":
        db_path = Path(db_path_str)
        if db_path.parent and str(db_path.parent) != ".":
            db_path.parent.mkdir(parents=True, exist_ok=True)
else:
    connect_args = {}

# 同时确保上传/PDF 目录存在
for d in (settings.upload_dir, settings.pdf_dir):
    if d:
        os.makedirs(d, exist_ok=True)

engine = create_engine(settings.database_url, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖：请求级会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- 轻量迁移：create_all 只建新表, 老表缺列在此补 ----------
def ensure_schema():
    """为既有表补齐新增列(2026-09-08 回收站 deleted_at 等)。幂等。"""
    import sqlite3
    from .config import get_settings as _gs
    url = _gs().database_url
    if not url.startswith("sqlite:///"):
        return  # 非 sqlite 跳过(未来 Postgres 用正式迁移)
    db_path = url.replace("sqlite:///", "", 1)
    if db_path == ":memory:":
        return
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        cur = conn.cursor()
        additions = {
            "reports": [("deleted_at", "DATETIME")],
            "tasks": [("deleted_at", "DATETIME")],
            "qcc_profiles": [("deleted_at", "DATETIME")],
            "property_clue_reports": [("deleted_at", "DATETIME")],
        }
        for table, cols in additions.items():
            try:
                existing = {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}
                for name, decl in cols:
                    if name not in existing:
                        cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            except Exception:
                pass  # 表不存在等: 由 create_all 建全量
        conn.commit()
    finally:
        conn.close()
