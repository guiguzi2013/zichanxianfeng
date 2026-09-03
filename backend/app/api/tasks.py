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
from ..services.extractor import KEY_FIELD_LABELS, KEY_FIELDS, is_valid_collateral
from .deps import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _check_claim_key_fields(db: Session, user_id: int, claim_ids: list[int]) -> None:
    """关键字段校验：债务人/本金/抵押物(合格) 任一缺失则不允许发起尽调
    （产品决策 2026-08-20；抵押物合格判定 2026-09-02 用户细化：房产类+描述具体）"""
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
            elif k == "collateral":
                extra = {}
                try:
                    extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
                except Exception:
                    extra = {}
                if not is_valid_collateral(v, extra.get("collateral_type")):
                    missing.append(KEY_FIELD_LABELS[k])
            elif not v:
                missing.append(KEY_FIELD_LABELS[k])
        if missing:
            name = claim.debtor_name or f"#{cid}"
            raise err(f"债权「{name}」缺少关键字段（{'、'.join(missing)}），请补充后再发起尽调")


def _task_name(db: Session, task: Task) -> str:
    """任务名称：取首个债权的债务人名（+ 债权数），如『青岛测试贸易有限公司 等3条』"""
    try:
        ids = json.loads(task.claim_ids or "[]")
    except Exception:
        ids = []
    if ids:
        first = db.get(Claim, ids[0])
        if first and first.debtor_name:
            name = str(first.debtor_name).split("；")[0][:30]
            return f"{name}{' 等' + str(len(ids)) + '条' if len(ids) > 1 else ''}"
    return f"任务#{task.id}"


def _task_to_out(db: Session, task: Task) -> TaskOut:
    """ORM → Pydantic。claim_ids 在 DB 里是 JSON 字符串，需先解析为 list 再构造
    （否则 model_validate 因类型不匹配报 500）。"""
    return TaskOut(
        id=task.id,
        name=_task_name(db, task),
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


def _infer_batch_claim_ids(db: Session, user_id: int, claim_ids: list[int]) -> list[int]:
    """推断当次导入的全量债权清单（历史任务用）。

    规则：与勾选债权同 source_raw（文件名）+ 创建时间在 5 分钟窗口内的同用户债权，
    视为同一次导入。勾选债权本身无 source_raw（如文本粘贴）时退回勾选清单。
    """
    if not claim_ids:
        return []
    from datetime import timedelta

    first = db.get(Claim, claim_ids[0])
    if first is None or not first.source_raw:
        return claim_ids
    raw = first.source_raw
    t0 = first.created_at
    # 同文件 + 同窗口
    batch = db.scalars(
        select(Claim).where(
            Claim.user_id == user_id,
            Claim.source_raw == raw,
            Claim.created_at >= t0 - timedelta(minutes=5),
            Claim.created_at <= t0 + timedelta(minutes=5),
        )
    ).all()
    ids = [c.id for c in batch]
    return ids if ids else claim_ids


def _task_source_ids(db: Session, task: Task) -> list[int]:
    """任务的全量债权清单：优先 source_claim_ids，否则按批次推断"""
    if task.source_claim_ids:
        try:
            ids = json.loads(task.source_claim_ids)
            if ids:
                return ids
        except Exception:
            pass
    return _infer_batch_claim_ids(db, task.user_id, json.loads(task.claim_ids or "[]"))


@router.post("", response_model=ApiResponse)
def create_task(req: TaskCreate, background: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 校验归属 + 关键字段（债务人/本金/抵押物）
    _check_claim_key_fields(db, user.id, req.claim_ids)

    source_ids = req.source_claim_ids or _infer_batch_claim_ids(db, user.id, req.claim_ids)
    task = Task(
        user_id=user.id,
        claim_ids=json.dumps(req.claim_ids),
        source_claim_ids=json.dumps(source_ids),
        status="pending",
        points_est=len(req.claim_ids) * 100,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    background.add_task(run_task_due_diligence, task.id, _update_task_progress)
    return ok(_task_to_out(db, task).model_dump(), "任务已创建")


@router.post("/save-only", response_model=ApiResponse)
def save_only(req: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for cid in req.claim_ids:
        claim = db.get(Claim, cid)
        if claim is None or claim.user_id != user.id:
            raise err(f"债权记录 {cid} 不存在")
    source_ids = req.source_claim_ids or _infer_batch_claim_ids(db, user.id, req.claim_ids)
    task = Task(
        user_id=user.id,
        claim_ids=json.dumps(req.claim_ids),
        source_claim_ids=json.dumps(source_ids),
        status="pending",
        points_est=0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return ok(_task_to_out(db, task).model_dump(), "已保存到我的任务")


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
    return ok(_task_to_out(db, task).model_dump(), "尽调已启动")


@router.post("/{task_id}/retry", response_model=ApiResponse)
def retry_task(task_id: int, background: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """重试失败任务（整单重跑，前端友好别名）"""
    return start_task(task_id, background, user, db)


@router.get("/{task_id}", response_model=ApiResponse)
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise err("任务不存在", http_status=404)
    return ok(_task_to_out(db, task).model_dump())


@router.get("/{task_id}/claims", response_model=ApiResponse)
def get_task_claims(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """任务原始债权表格：返回该任务关联的全部债权记录 + 每条是否已尽调（有报告）。

    前端据此展示"原始表格"：已尽调的显示已尽调选中态，未尽的仍可勾选发起新尽调。
    """
    from ..api.claims import _claim_to_out

    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise err("任务不存在", http_status=404)

    claim_ids = json.loads(task.claim_ids or "[]")
    # 全量清单：当次导入的所有债权（含未勾选）——优先 source_claim_ids，否则按批次推断
    source_ids = _task_source_ids(db, task)
    # 已尽调 = 该债权已有报告（本任务或其他任务生成的都算已尽调）
    from datetime import datetime as _dt

    from ..models import Report

    # 用户所有报告（找每个债权对应哪个任务的报告，供前端"查看"跳转）
    all_reports = db.scalars(
        select(Report).join(Task).where(Task.user_id == user.id)
    ).all()
    claim_report_task: dict[int, tuple[int, int]] = {}  # claim_id -> (task_id, report_id)（最近一份报告）
    for rp in sorted(all_reports, key=lambda x: x.created_at or _dt.min, reverse=True):
        if rp.claim_id not in claim_report_task:
            claim_report_task[rp.claim_id] = (rp.task_id, rp.id)

    claims_out = []
    for cid in source_ids:
        claim = db.get(Claim, cid)
        if claim is None or claim.user_id != user.id:
            continue
        item = _claim_to_out(claim).model_dump()
        item["diligence_done"] = cid in claim_report_task
        item["in_this_task"] = cid in claim_ids  # 是否本次任务勾选的
        loc = claim_report_task.get(cid)
        item["report_task_id"] = loc[0] if loc else None
        item["report_id"] = loc[1] if loc else None
        # 用户是否编辑过该债权（extra_fields.user_edited）——已尽调且修改过可重新尽调
        try:
            extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
        except Exception:
            extra = {}
        item["user_edited"] = bool(extra.get("user_edited"))
        claims_out.append(item)
    return ok({"task_id": task_id, "claims": claims_out})


@router.get("", response_model=ApiResponse)
def list_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tasks = db.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.id.desc())).all()
    return ok({"tasks": [_task_to_out(db, t).model_dump() for t in tasks]})
