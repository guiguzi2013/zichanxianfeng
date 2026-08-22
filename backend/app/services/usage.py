"""外部服务用量记录（成本控制：LLM / 数据源每次调用记账）"""
import json

from sqlalchemy.orm import Session

from ..models import UsageLog


def record_usage(
    db: Session,
    user_id: int,
    provider: str,
    action: str,
    task_id: int | None = None,
    cost_estimate: int = 0,
    detail: dict | None = None,
) -> None:
    """记录一次外部服务调用。与调用方同一事务（add + flush，由调用方 commit）。"""
    db.add(UsageLog(
        user_id=user_id,
        task_id=task_id,
        provider=provider,
        action=action,
        cost_estimate=cost_estimate,
        detail=json.dumps(detail, ensure_ascii=False) if detail else None,
    ))
    db.flush()
