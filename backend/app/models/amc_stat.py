"""AMC 机构数据（首页看板右栏排行）"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AmcStat(Base):
    __tablename__ = "amc_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_name: Mapped[str] = mapped_column(String(150), nullable=False)  # 机构名称
    scope: Mapped[str] = mapped_column(String(10), default="national")  # national=全国 / local=地方
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    listed_count: Mapped[int] = mapped_column(Integer, default=0)  # 挂牌笔数
    market_share: Mapped[float] = mapped_column(Float, default=0)  # 市场份额（%）
    trend: Mapped[str] = mapped_column(String(10), default="flat")  # up / down / flat
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
