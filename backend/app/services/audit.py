"""审计日志写入辅助（后台写操作全记录，不可删除）"""
import json

from sqlalchemy.orm import Session

from ..models import AuditLog


def write_audit_log(
    db: Session,
    operator_id: int,
    module: str,
    action: str,
    entity_id: str | None = None,
    change_summary: dict | None = None,
) -> None:
    """记录一条后台写操作。与调用方同一事务（add + flush，由调用方 commit）。"""
    db.add(AuditLog(
        operator_id=operator_id,
        module=module,
        action=action,
        entity_id=str(entity_id) if entity_id is not None else None,
        change_summary=json.dumps(change_summary, ensure_ascii=False) if change_summary else None,
    ))
    db.flush()
