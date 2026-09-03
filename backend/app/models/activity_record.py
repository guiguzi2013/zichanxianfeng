"""活动记录模型：土地厂房估价 / 财产线索查询 等用户操作留痕

用户需求（2026-08-25）：粘贴的房产估值、查询过的财产线索也应在"我的任务"中有记录，
分区块展示。kind 区分活动类型：
  - valuation: 土地厂房估价
  - clue: 财产线索查询
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ActivityRecord(Base):
    __tablename__ = "activity_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="valuation")  # valuation / clue
    title: Mapped[str] = mapped_column(String(300))      # 展示标题（如 土地厂房估价 / 财产线索：某某公司）
    summary: Mapped[str | None] = mapped_column(Text)    # 一句话摘要（如 估值区间 664.37~1169.52万元）
    detail: Mapped[str | None] = mapped_column(Text)     # JSON 详情（完整结果/请求参数）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
