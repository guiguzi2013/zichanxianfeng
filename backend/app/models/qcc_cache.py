"""企查查查询结果缓存模型

同一企业在 TTL 内的重复查询直接复用缓存（零企查查调用、零积分消耗），
缓存为网站自有，所有用户共享。
"""
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class QccCache(Base):
    __tablename__ = "qcc_cache"

    company: Mapped[str] = mapped_column(String(200), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)  # JSON: {company, biz, risk}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
