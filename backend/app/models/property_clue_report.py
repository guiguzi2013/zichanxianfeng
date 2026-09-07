"""财产线索单企业报告存储（2026-09-06 重构：单企业查询即生成报告）

背景：财产线索从"多主体列表查询+综合分析按钮"改为"输入一家企业 → 查询即生成报告"
（用户拍板 2026-09-06：①单企业输入 ②查询结果直接生成报告(查询+分析融合) ③可下载PDF、
在"我的报告"回看/重复下载 ④同企业只能查一次(重复提示已有) ⑤去掉"深度对比"(深挖后续再做)）。

与 qcc_profiles(债务人画像/企业速览) 解耦：线索报告独立成表，后续可独立演进。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class PropertyClueReport(Base):
    __tablename__ = "property_clue_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    company: Mapped[str] = mapped_column(String(200), index=True)   # 用户输入的企业名
    search_name: Mapped[str | None] = mapped_column(String(200))     # 实际查询现名(更名后)
    content: Mapped[str | None] = mapped_column(Text)                # JSON: sections(查询+分析融合)
    pdf_path: Mapped[str | None] = mapped_column(String(255))
    queried_at: Mapped[str | None] = mapped_column(String(20))       # 数据截至(企查查查询日)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 2026-09-08 回收站: 软删时间
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
