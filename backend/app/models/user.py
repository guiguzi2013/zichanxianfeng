"""用户模型"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20), default="user")  # user / admin / editor
    land_price_perm: Mapped[bool] = mapped_column(default=False)   # 员工是否有录入土地价格库权限
    points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 在线统计（2026-09-01）：最后登录时间 / 最后登出时间，在线时长 = 登出 − 登录
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_logout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
