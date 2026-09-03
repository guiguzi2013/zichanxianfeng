"""活动记录服务：土地厂房估价 / 财产线索查询 留痕与查询

"我的任务"分区块展示用户操作记录：智能尽调任务（tasks 表）、
土地厂房估价（activity_records kind=valuation）、财产线索（kind=clue）。
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActivityRecord

logger = logging.getLogger(__name__)


def add_activity(db: Session, user_id: int, kind: str, title: str, summary: str | None = None, detail: dict | None = None) -> ActivityRecord:
    """新增一条活动记录"""
    rec = ActivityRecord(
        user_id=user_id,
        kind=kind,
        title=title,
        summary=summary,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def list_activity(db: Session, user_id: int, kind: str | None = None, limit: int = 50) -> list[dict]:
    """按用户查询活动记录（最新在前）"""
    q = select(ActivityRecord).where(ActivityRecord.user_id == user_id)
    if kind:
        q = q.where(ActivityRecord.kind == kind)
    q = q.order_by(ActivityRecord.id.desc()).limit(limit)
    rows = db.scalars(q).all()
    out = []
    for r in rows:
        detail = None
        if r.detail:
            try:
                detail = json.loads(r.detail)
            except Exception:
                detail = None
        out.append({
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "summary": r.summary,
            "detail": detail,
            "created_at": r.created_at.isoformat(),
        })
    return out
