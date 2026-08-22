"""审计日志模型（后台写操作全记录，不可删除）"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    module: Mapped[str] = mapped_column(String(30))  # claim/ad/notice/auction/amc/macro/user
    action: Mapped[str] = mapped_column(String(20))  # create/update/delete
    entity_id: Mapped[str | None] = mapped_column(String(50))
    change_summary: Mapped[str | None] = mapped_column(Text)  # JSON 变更摘要
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
