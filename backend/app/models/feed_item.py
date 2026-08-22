"""首页栏目数据模型（精选债权/捡漏/存量盘活/拍卖/AMC/公告）"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class FeedItem(Base):
    __tablename__ = "feed_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section: Mapped[str] = mapped_column(String(20), index=True)  # featured/bargain/asset_revive/amc/auction/notice
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(Text)  # JSON list
    source: Mapped[str | None] = mapped_column(String(100))  # 北交所/淘宝/手工录入
    source_url: Mapped[str | None] = mapped_column(String(500))
    detail_json: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[int] = mapped_column(Integer, default=1)  # 1 上架 / 0 下架
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
