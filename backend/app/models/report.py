"""报告模型（9版块 JSON 存储 + PDF 路径）"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True, nullable=False)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str | None] = mapped_column(Text)  # 9版块 JSON
    pdf_path: Mapped[str | None] = mapped_column(String(255))
    supplements: Mapped[str | None] = mapped_column(Text)  # JSON list
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
