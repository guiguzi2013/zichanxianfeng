"""管理后台路由：统计/用户管理/审计日志/用量报表/员工账号"""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Claim, FeedItem, Report, Task, Upload, UsageLog, User
from ..schemas.common import ApiResponse, err, ok
from ..services.security import hash_password
from .deps import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


class EditorAccountCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    nickname: str | None = None


@router.post("/editor-accounts", response_model=ApiResponse)
def create_editor_account(req: EditorAccountCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """管理员开通员工（运营编辑）账号：仅可录入/删改『精选债权』『热门捡漏』"""
    exists = db.scalar(select(User).where(User.username == req.username))
    if exists:
        raise err("用户名已存在", http_status=409)
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        nickname=req.nickname or req.username,
        role="editor",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok({"id": user.id, "username": user.username, "nickname": user.nickname, "role": user.role}, "员工账号已创建（仅可维护精选债权/热门捡漏）")


@router.delete("/editor-accounts/{user_id}", response_model=ApiResponse)
def delete_editor_account(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """禁用/删除员工账号"""
    user = db.get(User, user_id)
    if user is None:
        raise err("用户不存在", http_status=404)
    if user.role != "editor":
        raise err("仅可删除员工（运营编辑）账号")
    db.delete(user)
    db.commit()
    return ok(None, "员工账号已删除")


@router.get("/stats", response_model=ApiResponse)
def get_stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):  # noqa: F821  User 来自 models import
    """平台统计：用户/债权/任务/报告/内容数"""
    return ok({
        "users": db.scalar(select(func.count(User.id))),
        "claims": db.scalar(select(func.count(Claim.id))),
        "tasks": db.scalar(select(func.count(Task.id))),
        "tasks_done": db.scalar(select(func.count(Task.id)).where(Task.status == "done")),
        "reports": db.scalar(select(func.count(Report.id))),
        "feed_items": db.scalar(select(func.count(FeedItem.id)).where(FeedItem.is_active == 1)),
        "uploads": db.scalar(select(func.count(Upload.id))),
    })


@router.get("/users", response_model=ApiResponse)
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.id)).all()
    return ok({
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "nickname": u.nickname,
                "role": u.role,
                "points": u.points,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    })


@router.get("/audit-logs", response_model=ApiResponse)
def list_audit_logs(limit: int = 100, offset: int = 0, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """审计日志：按时间倒序分页查询（只读）"""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    logs = db.scalars(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    ).all()
    total = db.scalar(select(func.count(AuditLog.id)))
    return ok({
        "total": total,
        "logs": [
            {
                "id": log.id,
                "operator_id": log.operator_id,
                "module": log.module,
                "action": log.action,
                "entity_id": log.entity_id,
                "change_summary": json.loads(log.change_summary) if log.change_summary else None,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    })


@router.get("/usage-report", response_model=ApiResponse)
def usage_report(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """外部服务用量报表：按 provider/action 汇总 + 总成本 + 最近记录"""
    by_provider = db.execute(
        select(UsageLog.provider, func.count(UsageLog.id), func.sum(UsageLog.cost_estimate))
        .group_by(UsageLog.provider)
        .order_by(func.count(UsageLog.id).desc())
    ).all()
    by_action = db.execute(
        select(UsageLog.action, func.count(UsageLog.id))
        .group_by(UsageLog.action)
        .order_by(func.count(UsageLog.id).desc())
    ).all()
    total_cost = db.scalar(select(func.sum(UsageLog.cost_estimate))) or 0
    recent = db.scalars(select(UsageLog).order_by(UsageLog.id.desc()).limit(20)).all()
    return ok({
        "total_calls": db.scalar(select(func.count(UsageLog.id))),
        "total_cost_cents": total_cost,
        "by_provider": [{"provider": p, "calls": c, "cost_cents": s or 0} for p, c, s in by_provider],
        "by_action": [{"action": a, "calls": c} for a, c in by_action],
        "recent": [
            {
                "id": u.id,
                "user_id": u.user_id,
                "task_id": u.task_id,
                "provider": u.provider,
                "action": u.action,
                "cost_estimate": u.cost_estimate,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in recent
        ],
    })
