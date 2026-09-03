"""尽调任务模型"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    claim_ids: Mapped[str] = mapped_column(Text)  # JSON list（本次勾选发起尽调的债权）
    source_claim_ids: Mapped[str | None] = mapped_column(Text)  # JSON list（当次导入的全量债权，含未勾选）
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/running/done/failed/partial
    current_node: Mapped[str | None] = mapped_column(String(30))
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    points_est: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
