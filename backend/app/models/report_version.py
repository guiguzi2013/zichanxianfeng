"""报告版本模型（补充材料触发重新生成后保留历史版本，可查看/回退）"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ReportVersion(Base):
    __tablename__ = "report_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)  # 九版块 JSON 快照
    source: Mapped[str] = mapped_column(String(20), default="ai")  # ai / supplement / manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
