"""土地价格参考库模型

存放各地土地出让基准价/成交价（元/㎡），供抵押物估值参考。
用户尽调的抵押物或查询的土地估价，与库内地区/土地性质相近时自动匹配参考。
前台不展示，管理后台维护（支持批量导入自动归类）。
土地性质分类参照《土地利用现状分类》GB/T 21010-2017。
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LandPriceRef(Base):
    __tablename__ = "land_price_ref"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    province: Mapped[str | None] = mapped_column(String(50))   # 省（如 山东）
    city: Mapped[str | None] = mapped_column(String(50))       # 市（如 青岛）
    district: Mapped[str | None] = mapped_column(String(50))   # 区县（可选，如 城阳）
    land_type: Mapped[str] = mapped_column(String(50))         # 土地性质（工业/商业/住宅/综合 等，对齐用地分类）
    price_lo: Mapped[int] = mapped_column(Integer)             # 单价下限（元/㎡）
    price_hi: Mapped[int] = mapped_column(Integer)             # 单价上限（元/㎡）
    source: Mapped[str | None] = mapped_column(String(200))    # 来源（基准地价公示/成交公告/人工录入）
    effective_date: Mapped[str | None] = mapped_column(String(50))  # 生效日期（文本，便于维护）
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
