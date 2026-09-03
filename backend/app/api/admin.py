"""管理后台路由：统计/用户管理/审计日志/用量报表/员工账号"""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Claim, ClueReport, FeedItem, Report, Task, Upload, UsageLog, User
from ..schemas.common import ApiResponse, err, ok
from ..services.security import hash_password
from .deps import require_admin, require_editor

router = APIRouter(prefix="/admin", tags=["admin"])


class EditorAccountCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=100)
    nickname: str | None = None
    land_price_perm: bool = False  # 是否允许录入土地价格库


class EditorAccountUpdate(BaseModel):
    nickname: str | None = None
    land_price_perm: bool | None = None


@router.post("/editor-accounts", response_model=ApiResponse)
def create_editor_account(req: EditorAccountCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """管理员开通员工（运营编辑）账号：可维护精选债权/热门捡漏；可选土地价格库录入权限"""
    exists = db.scalar(select(User).where(User.username == req.username))
    if exists:
        raise err("用户名已存在", http_status=409)
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        nickname=req.nickname or req.username,
        role="editor",
        land_price_perm=req.land_price_perm,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok({
        "id": user.id, "username": user.username, "nickname": user.nickname,
        "role": user.role, "land_price_perm": user.land_price_perm,
    }, "员工账号已创建")


@router.put("/editor-accounts/{user_id}", response_model=ApiResponse)
def update_editor_account(user_id: int, req: EditorAccountUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """修改员工账号（昵称 / 土地价格库权限）"""
    user = db.get(User, user_id)
    if user is None:
        raise err("用户不存在", http_status=404)
    if user.role != "editor":
        raise err("仅可修改员工（运营编辑）账号")
    data = req.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    db.refresh(user)
    return ok({
        "id": user.id, "username": user.username, "nickname": user.nickname,
        "role": user.role, "land_price_perm": user.land_price_perm,
    }, "员工账号已更新")


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
def get_stats(admin: User = Depends(require_editor), db: Session = Depends(get_db)):  # noqa: F821  User 来自 models import
    """平台统计（全局数据，admin/editor 可见）：用户/债权/任务/报告/内容数"""
    return ok({
        "users": db.scalar(select(func.count(User.id))),
        "claims": db.scalar(select(func.count(Claim.id))),
        "tasks": db.scalar(select(func.count(Task.id))),
        "tasks_done": db.scalar(select(func.count(Task.id)).where(Task.status == "done")),
        "reports": db.scalar(select(func.count(Report.id))),
        "clue_reports": db.scalar(select(func.count(ClueReport.id))),
        "feed_items": db.scalar(select(func.count(FeedItem.id)).where(FeedItem.is_active == 1)),
        "uploads": db.scalar(select(func.count(Upload.id))),
    })


@router.get("/users", response_model=ApiResponse)
def list_users(admin: User = Depends(require_editor), db: Session = Depends(get_db)):
    from datetime import datetime as _dt
    from ..models import LoginSession

    # 今日 00:00（自然日）
    now = _dt.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    sessions = db.execute(
        select(LoginSession).where(LoginSession.login_at >= day_start)
    ).all()

    def today_online_seconds(user_id: int) -> int:
        """今日在线时长：该用户今天所有会话与今日相交时长的累加（未登出按当前时间计）"""
        total = 0
        for (s,) in sessions:
            if s.user_id != user_id:
                continue
            start = s.login_at if s.login_at >= day_start else day_start
            end = s.logout_at or now
            if end > start:
                total += int((end - start).total_seconds())
        return total

    users = db.scalars(select(User).order_by(User.id)).all()
    return ok({
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "nickname": u.nickname,
                "role": u.role,
                "land_price_perm": getattr(u, "land_price_perm", False),
                "points": u.points,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "last_logout_at": u.last_logout_at.isoformat() if u.last_logout_at else None,
                "today_online_seconds": today_online_seconds(u.id),
            }
            for u in users
        ]
    })


@router.get("/users/{user_id}/sessions", response_model=ApiResponse)
def list_user_sessions(
    user_id: int,
    offset: int = 0,
    limit: int = 100,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """该用户全部登录会话（登录/登出/在线时长，按时间倒序，分页；2026-09-01 会话表）

    注意：展示的是该用户**所有历史登录记录**，不限当天；login_sessions 表自
    2026-09-01 起记录，此前无会话数据。
    """
    from datetime import datetime as _dt
    from sqlalchemy import func as _func
    from ..models import LoginSession

    user = db.get(User, user_id)
    if user is None:
        raise err("用户不存在", http_status=404)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    total = db.scalar(_func.count(LoginSession.id).select().where(LoginSession.user_id == user_id)) or 0
    sessions = db.scalars(
        select(LoginSession).where(LoginSession.user_id == user_id)
        .order_by(LoginSession.id.desc()).offset(offset).limit(limit)
    ).all()
    now = _dt.now()
    out = []
    for s in sessions:
        login = s.login_at
        logout = s.logout_at or now
        online = s.logout_at is None
        out.append({
            "id": s.id,
            "login_at": login.isoformat() if login else None,
            "logout_at": s.logout_at.isoformat() if s.logout_at else None,
            "duration_seconds": int((logout - login).total_seconds()) if login and logout > login else 0,
            "online": online,
        })
    return ok({
        "user_id": user_id,
        "username": user.username,
        "total": total,
        "sessions": out,
        "note": "登录会话自 2026-09-01 起记录（此前的历史登录无会话数据）",
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


@router.get("/reports", response_model=ApiResponse)
def list_admin_reports(
    username: str | None = None,
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """平台报告列表（全局，admin/editor 可见）：用于员工查看用户生成的报告，处理用户问题/投诉。

    员工只能查看报告生成页，不能下载 PDF（下载权限在前端按角色隐藏）。
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    q = select(Report, Task, User).join(Task, Report.task_id == Task.id).join(User, Task.user_id == User.id)
    if username:
        q = q.where(User.username.contains(username) | User.nickname.contains(username))
    q = q.order_by(Report.id.desc()).limit(limit).offset(offset)
    rows = db.execute(q).all()
    total = db.scalar(select(func.count(Report.id)))
    out = []
    for report, task, u in rows:
        debtor = ""
        try:
            import json as _json
            content = report.content
            if content:
                if isinstance(content, str):
                    content = _json.loads(content)
                debtor = (content.get("report_meta") or {}).get("debtor_name") or ""
        except Exception:  # noqa: BLE001
            debtor = ""
        out.append({
            "report_id": report.id,
            "task_id": report.task_id,
            "claim_id": report.claim_id,
            "version": report.version,
            "debtor_name": debtor,
            "username": u.username,
            "nickname": u.nickname,
            "task_status": task.status,
            "created_at": report.created_at.isoformat() if report.created_at else None,
        })
    return ok({"total": total, "reports": out})


# ---------- 财产线索/深挖报告留存（2026-09-01 用户确认落库，供管理后台查看与单条清缓存） ----------

@router.get("/clue-reports", response_model=ApiResponse)
def list_clue_reports(
    username: str | None = None,
    report_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """财产线索/深挖报告列表（admin/editor 可见）：case=综合分析 / deep=深挖"""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    q = select(ClueReport, User).join(User, ClueReport.user_id == User.id)
    if username:
        q = q.where(User.username.contains(username) | User.nickname.contains(username))
    if report_type:
        q = q.where(ClueReport.report_type == report_type)
    q = q.order_by(ClueReport.id.desc()).limit(limit).offset(offset)
    rows = db.execute(q).all()
    total = db.scalar(select(func.count(ClueReport.id)))
    out = []
    for cr, u in rows:
        out.append({
            "id": cr.id,
            "report_type": cr.report_type,
            "title": cr.title,
            "subject_names": json.loads(cr.subject_names) if cr.subject_names else [],
            "username": u.username,
            "nickname": u.nickname,
            "created_at": cr.created_at.isoformat() if cr.created_at else None,
        })
    return ok({"total": total, "reports": out})


@router.get("/clue-reports/{report_id}", response_model=ApiResponse)
def get_clue_report(report_id: int, admin: User = Depends(require_editor), db: Session = Depends(get_db)):
    """查看财产线索/深挖报告全文（admin/editor 可读，员工做客服答疑）"""
    cr = db.get(ClueReport, report_id)
    if cr is None:
        raise err("报告不存在", http_status=404)
    content = json.loads(cr.content) if cr.content else None
    return ok({
        "id": cr.id,
        "report_type": cr.report_type,
        "title": cr.title,
        "subject_names": json.loads(cr.subject_names) if cr.subject_names else [],
        "content": content,
        "created_at": cr.created_at.isoformat() if cr.created_at else None,
    })


@router.post("/clue-reports/{report_id}/clear-cache", response_model=ApiResponse)
def clear_clue_report_cache(report_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """单条清缓存（仅管理员）：按报告涉及的主体名称清除企查查缓存（下次查询重新实查扣积分）"""
    from ..api.qcc import _cache_delete

    cr = db.get(ClueReport, report_id)
    if cr is None:
        raise err("报告不存在", http_status=404)
    names = json.loads(cr.subject_names) if cr.subject_names else []
    if not names:
        raise err("该报告未记录主体名称，无法清缓存")
    total = 0
    cleared = []
    for n in names:
        n = n.strip()
        if not n:
            continue
        deleted = _cache_delete(n)
        if deleted:
            total += deleted
            cleared.append(n)
    return ok({"report_id": report_id, "cleared": cleared, "deleted": total},
              f"已清除 {len(cleared)} 个主体的缓存（共 {total} 条缓存键），下次查询将重新实查")


@router.post("/reports/{report_id}/clear-cache", response_model=ApiResponse)
def clear_report_cache(report_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """尽调报告单条清缓存（仅管理员）：按债务人名称清除企查查缓存"""
    from ..api.qcc import _cache_delete

    report = db.get(Report, report_id)
    if report is None:
        raise err("报告不存在", http_status=404)
    task = db.get(Task, report.task_id)
    if task is None:
        raise err("任务不存在", http_status=404)
    claim = db.get(Claim, report.claim_id) if report.claim_id else None
    debtor = claim.debtor_name if claim else None
    if not debtor:
        raise err("该报告未关联债务人名称，无法清缓存")
    deleted = _cache_delete(debtor)
    return ok({"report_id": report_id, "debtor": debtor, "deleted": deleted},
              f"已清除「{debtor}」的缓存（{deleted} 条缓存键），下次尽调将重新实查")
