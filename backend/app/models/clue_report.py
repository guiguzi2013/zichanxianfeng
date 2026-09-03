"""财产线索报告留存模型（2026-09-01）

用户确认（2026-09-01）：财产线索综合分析报告 / 深度调查(深挖)报告需要落库留存，
供管理后台（admin/editor）查看，处理用户问题/投诉；管理员可针对单条报告清缓存。

report_type:
  - case: 财产线索综合分析报告（/clues/case-report、/clues/case-report-deep）
  - deep: 深度调查（/clues/deep-investigation，用户拟改名"深挖"，功能待完善）
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ClueReport(Base):
    __tablename__ = "clue_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    report_type: Mapped[str] = mapped_column(String(20), default="case")  # case / deep
    title: Mapped[str] = mapped_column(String(300))      # 展示标题（如 财产线索综合分析：3 个主体）
    subject_names: Mapped[str | None] = mapped_column(Text)  # JSON list：涉及的主体名称（清缓存用）
    content: Mapped[str] = mapped_column(Text)           # 报告全文 JSON

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
