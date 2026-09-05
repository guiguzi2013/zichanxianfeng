"""债务人画像(企业速览)报告存储（2026-09-04 新增）

与债权尽调 reports 表解耦（reports 强绑 task/claim），画像报告独立成表：
查询一次 → 摘要 content(JSON) + PDF 落盘，用户在"债务人画像"页历史记录可回看/下载。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class QccProfile(Base):
    __tablename__ = "qcc_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    company: Mapped[str] = mapped_column(String(200), index=True)   # 用户输入名
    search_name: Mapped[str | None] = mapped_column(String(200))     # 实际查询现名(更名后)
    content: Mapped[str | None] = mapped_column(Text)                # JSON: 摘要 + biz/risk 全量
    pdf_path: Mapped[str | None] = mapped_column(String(255))
    queried_at: Mapped[str | None] = mapped_column(String(20))       # 数据截至(企查查查询日)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
