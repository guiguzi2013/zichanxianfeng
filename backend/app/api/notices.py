"""公告路由：公开查询 + 管理后台维护（含审计日志）"""
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Notice, User
from ..schemas.common import ApiResponse, err, ok
from ..services.audit import write_audit_log
from .deps import require_admin

router = APIRouter(tags=["notices"])


class NoticeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str | None = None
    is_pinned: bool = False
    enabled: bool = True
    published_at: datetime | None = None


def _notice_to_dict(n: Notice) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "is_pinned": bool(n.is_pinned),
        "enabled": bool(n.enabled),
        "published_at": n.published_at.isoformat() if n.published_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/notices", response_model=ApiResponse)
def list_notices(db: Session = Depends(get_db)):
    """公开：启用中的公告列表（置顶优先，时间倒序）"""
    notices = db.scalars(
        select(Notice)
        .where(Notice.enabled == True)  # noqa: E712
        .order_by(Notice.is_pinned.desc(), Notice.published_at.desc(), Notice.id.desc())
        .limit(50)
    ).all()
    return ok({"notices": [_notice_to_dict(n) for n in notices]})


@router.get("/notices/{notice_id}", response_model=ApiResponse)
def get_notice(notice_id: int, db: Session = Depends(get_db)):
    notice = db.get(Notice, notice_id)
    if notice is None or not notice.enabled:
        raise err("公告不存在", http_status=404)
    return ok(_notice_to_dict(notice))


# ---- 管理后台（admin）----


@router.post("/admin/notices", response_model=ApiResponse)
def create_notice(req: NoticeCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    notice = Notice(
        title=req.title,
        content=req.content,
        is_pinned=req.is_pinned,
        enabled=req.enabled,
        published_at=req.published_at or datetime.now(),
    )
    db.add(notice)
    write_audit_log(db, admin.id, "notice", "create", entity_id=None, change_summary={"title": req.title})
    db.commit()
    db.refresh(notice)
    return ok(_notice_to_dict(notice), "公告已发布")


@router.put("/admin/notices/{notice_id}", response_model=ApiResponse)
def update_notice(notice_id: int, req: NoticeCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise err("公告不存在", http_status=404)
    before = {"title": notice.title, "enabled": bool(notice.enabled)}
    notice.title = req.title
    notice.content = req.content
    notice.is_pinned = req.is_pinned
    notice.enabled = req.enabled
    notice.published_at = req.published_at or notice.published_at
    write_audit_log(db, admin.id, "notice", "update", entity_id=notice_id, change_summary={"before": before, "after": {"title": req.title, "enabled": req.enabled}})
    db.commit()
    db.refresh(notice)
    return ok(_notice_to_dict(notice), "公告已更新")


@router.delete("/admin/notices/{notice_id}", response_model=ApiResponse)
def delete_notice(notice_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise err("公告不存在", http_status=404)
    write_audit_log(db, admin.id, "notice", "delete", entity_id=notice_id, change_summary={"title": notice.title})
    db.delete(notice)
    db.commit()
    return ok(None, "公告已删除")
