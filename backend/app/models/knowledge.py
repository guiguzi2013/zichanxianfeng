"""知识库模型：规范性文件 + 典型案例

规范性文件：规范报告用词与法条引用（人工维护版本/效力状态，到期提醒复核）
典型案例：尽调中可参考的执行/追索场景（抵押物占用、债务人生病等），
          尽调报告按场景标签匹配后附加风险提醒。
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LegalDoc(Base):
    """规范性文件（法律/司法解释/规定）"""

    __tablename__ = "legal_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str | None] = mapped_column(String(50), default="尽调法规")  # 知识分类
    source_type: Mapped[str | None] = mapped_column(String(20), default="manual")  # manual=文字录入(可编辑) / upload=文档上传(只读可删)
    title: Mapped[str] = mapped_column(String(300), nullable=False)   # 文件名称
    doc_no: Mapped[str | None] = mapped_column(String(100))           # 文号（如 法释〔2017〕8号）
    issuer: Mapped[str | None] = mapped_column(String(100))           # 发布机关
    effect_date: Mapped[str | None] = mapped_column(String(50))       # 施行日期（文本，便于人工维护）
    status: Mapped[str] = mapped_column(String(20), default="现行有效")  # 现行有效/已修改/已废止/需复核
    latest_version: Mapped[str | None] = mapped_column(String(200))   # 最新版本名称/修订说明
    tags: Mapped[str | None] = mapped_column(String(300))             # 逗号分隔标签（用于报告用词/引用）
    keywords: Mapped[str | None] = mapped_column(String(300))         # 逗号分隔关键词（匹配提醒用）
    summary: Mapped[str | None] = mapped_column(Text)                 # 核心条款摘要（报告可直接引用）
    note: Mapped[str | None] = mapped_column(Text)                    # 备注（使用提示/复核提示）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class KnowledgeCase(Base):
    """典型案例：执行/追索场景参考"""

    __tablename__ = "knowledge_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str | None] = mapped_column(String(50), default="尽调案例")  # 知识分类
    source_type: Mapped[str | None] = mapped_column(String(20), default="manual")  # manual=文字录入(可编辑) / upload=文档上传(只读可删)
    title: Mapped[str] = mapped_column(String(300), nullable=False)   # 案例标题
    scenario: Mapped[str | None] = mapped_column(String(100))         # 场景标签（如 抵押物占用）
    tags: Mapped[str | None] = mapped_column(String(300))             # 逗号分隔标签
    keywords: Mapped[str | None] = mapped_column(String(300))         # 逗号分隔关键词（报告匹配用）
    summary: Mapped[str | None] = mapped_column(Text)                 # 案情摘要
    approach: Mapped[str | None] = mapped_column(Text)                # 处理思路/法律路径
    result: Mapped[str | None] = mapped_column(Text)                  # 处理结果
    source: Mapped[str | None] = mapped_column(String(200))           # 来源
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
