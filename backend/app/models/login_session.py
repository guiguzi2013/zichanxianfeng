"""登录会话模型（2026-09-01）：记录每次登录/登出时间，用于统计用户今日在线时长

- 登录时新建一条 session（login_at=now, logout_at=NULL）
- 登出/超时自动登出时，关闭该用户最近一条未关闭的 session（logout_at=now）
- 今日在线时长 = 今天（自然日 00:00 起）所有会话与今日相交时长的累加
  （会话跨天时只计今天部分；未登出的按当前时间计）
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    login_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    logout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
