"""拍卖平台成交数据（首页看板左栏）"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AuctionStat(Base):
    __tablename__ = "auction_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(100), nullable=False)  # 平台名（阿里资产/京东拍卖等）
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM 统计周期
    on_auction: Mapped[int] = mapped_column(Integer, default=0)  # 上拍数
    sold: Mapped[int] = mapped_column(Integer, default=0)  # 成交数
    amount: Mapped[float] = mapped_column(Float, default=0)  # 成交额（万元）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
