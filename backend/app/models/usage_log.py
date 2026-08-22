"""外部服务用量日志（成本控制：LLM / 企业数据服务每次调用记录）"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))  # deepseek / qcc / aiqicha / gsxt / zxgk
    action: Mapped[str] = mapped_column(String(50))  # extract/analyze/company_detail/...
    cost_estimate: Mapped[int] = mapped_column(Integer, default=0)  # 分
    detail: Mapped[str | None] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
