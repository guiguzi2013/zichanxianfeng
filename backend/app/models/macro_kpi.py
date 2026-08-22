"""宏观指标 / KPI 数据（首页宏观数据条 + KPI 卡片）

category: macro=宏观数据条（不良余额/不良率/AMC数量/处置规模）
          kpi  = KPI 卡片（在拍总数/今日新增/成交额/平均折扣率）
value 统一存字符串（展示格式如 "3.7"、"12,846"），unit 单独存。
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class MacroKpi(Base):
    __tablename__ = "macro_kpis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(10), default="macro")  # macro / kpi
    label: Mapped[str] = mapped_column(String(50), nullable=False)  # 显示名
    value: Mapped[str] = mapped_column(String(30), nullable=False)  # 数值（含格式）
    unit: Mapped[str] = mapped_column(String(10), default="")
    trend: Mapped[str] = mapped_column(String(50), default="")  # KPI 趋势文案（如 +3.2% 较上月）
    trend_up: Mapped[int] = mapped_column(Integer, default=1)  # 1 上涨(绿) / 0 下跌(红)
    sort: Mapped[int] = mapped_column(Integer, default=0)  # 排序
    source: Mapped[str] = mapped_column(String(100), default="")  # 数据来源标注
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
