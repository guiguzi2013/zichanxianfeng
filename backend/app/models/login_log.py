"""登录日志模型（安全审计）"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LoginLog(Base):
    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    username: Mapped[str | None] = mapped_column(String(50))
    ip: Mapped[str | None] = mapped_column(String(50))
    result: Mapped[str] = mapped_column(String(10), default="success")  # success / fail
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
