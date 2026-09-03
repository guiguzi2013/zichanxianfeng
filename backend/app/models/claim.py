"""债权记录模型（用户输入解析后的结构化债权）"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    # 来源
    source_type: Mapped[str] = mapped_column(String(10))  # text / link / excel
    source_raw: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))

    # 结构化字段（金额统一存"分"）
    debtor_name: Mapped[str | None] = mapped_column(String(100))
    principal_cents: Mapped[int | None] = mapped_column(Integer)
    interest_cents: Mapped[int | None] = mapped_column(Integer)
    fees_cents: Mapped[int | None] = mapped_column(Integer)
    guaranty_type: Mapped[str | None] = mapped_column(String(50))
    guarantor: Mapped[str | None] = mapped_column(Text)
    collateral: Mapped[str | None] = mapped_column(Text)
    judicial_status: Mapped[str | None] = mapped_column(String(100))
    listing_price_cents: Mapped[int | None] = mapped_column(Integer)
    deadline: Mapped[str | None] = mapped_column(String(20))  # YYYY-MM-DD

    # 系统判断与完整度
    debtor_type: Mapped[str | None] = mapped_column(String(10))  # enterprise / person
    completeness: Mapped[str | None] = mapped_column(String(10))  # green / yellow / red
    missing_fields: Mapped[str | None] = mapped_column(Text)  # JSON list

    # 扩展
    extra_fields: Mapped[str | None] = mapped_column(Text)  # JSON

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
