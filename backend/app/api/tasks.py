"""尽调任务路由：创建/查询/列表/仅保存"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, Task, User
from ..schemas.common import ApiResponse, err, ok
from ..schemas.task import TaskCreate, TaskOut
from ..services.due_diligence import run_task_due_diligence
from ..services.extractor import KEY_FIELD_LABELS, KEY_FIELDS
from .deps import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _check_claim_key_fields(db: Session, user_id: int, claim_ids: list[int]) -> None:
    """关键字段校验：债务人/本金/抵押物 任一缺失则不允许发起尽调（产品决策 2026-08-20）"""
    for cid in claim_ids:
        claim = db.get(Claim, cid)
        if claim is None or claim.user_id != user_id:
            raise err(f"债权记录 {cid} 不存在")
        missing = []
        for k in KEY_FIELDS:
            v = getattr(claim, k)
            if k == "principal_cents":
                if v is None:
                    missing.append(KEY_FIELD_LABELS[k])
            elif not v:
                missing.append(KEY_FIELD_LABELS[k])
        if missing:
            name = claim.debtor_name or f"#{cid}"
            raise err(f"债权「{name}」缺少关键字段（{'、'.join(missing)}），请补充后再发起尽调")


def _task_to_out(task: Task) -> TaskOut:
    """ORM → Pydantic。claim_ids 在 DB 里是 JSON 字符串，需先解析为 list 再构造
    （否则 model_validate 因类型不匹配报 500）。"""
    return TaskOut(
        id=task.id,
        claim_ids=json.loads(task.claim_ids or "[]"),
        status=task.status,
        current_node=task.current_node,
        progress=task.progress,
        points_est=task.points_est,
        error=task.error,
        created_at=task.created_at,
        finished_at=task.finished_at,
    )


def _update_task_progress(task_id: int, node: str, percent: int):
    """后台尽调进程内的进度回调（独立 Session，避免跨线程共享）"""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task:
            task.current_node = node
            task.progress = max(task.progress, percent)
            db.commit()
    finally:
        db.close()


@router.post("", response_model=ApiResponse)
def create_task(req: TaskCreate, background: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 校验归属 + 关键字段（债务人/本金/抵押物）
    _check_claim_key_fields(db, user.id, req.claim_ids)

    task = Task(
        user_id=user.id,
        claim_ids=json.dumps(req.claim_ids),
        status="pending",
        points_est=len(req.claim_ids) * 100,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    background.add_task(run_task_due_diligence, task.id, _update_task_progress)
    return ok(_task_to_out(task).model_dump(), "任务已创建")


@router.post("/save-only", response_model=ApiResponse)
def save_only(req: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for cid in req.claim_ids:
        claim = db.get(Claim, cid)
        if claim is None or claim.user_id != user.id:
            raise err(f"债权记录 {cid} 不存在")
    task = Task(
        user_id=user.id,
        claim_ids=json.dumps(req.claim_ids),
        status="pending",
        points_est=0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return ok(_task_to_out(task).model_dump(), "已保存到我的任务")


@router.post("/{task_id}/start", response_model=ApiResponse)
def start_task(task_id: int, background: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """对已保存（pending）任务启动尽调"""
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise err("任务不存在", http_status=404)
    if task.status not in ("pending", "failed"):
        raise err("任务已在运行或已完成")
    _check_claim_key_fields(db, user.id, json.loads(task.claim_ids or "[]"))
    task.status = "pending"
    task.error = None
    db.commit()
    background.add_task(run_task_due_diligence, task.id, _update_task_progress)
    return ok(_task_to_out(task).model_dump(), "尽调已启动")


@router.post("/{task_id}/retry", response_model=ApiResponse)
def retry_task(task_id: int, background: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """重试失败任务（整单重跑，前端友好别名）"""
    return start_task(task_id, background, user, db)


@router.get("/{task_id}", response_model=ApiResponse)
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise err("任务不存在", http_status=404)
    return ok(_task_to_out(task).model_dump())


@router.get("", response_model=ApiResponse)
def list_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tasks = db.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.id.desc())).all()
    return ok({"tasks": [_task_to_out(t).model_dump() for t in tasks]})
