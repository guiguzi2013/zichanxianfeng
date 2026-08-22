"""PDF 报告生成（WeasyPrint：HTML → PDF，正式文档风格）

对应设计文档第9章：封面 + 目录 + 九版块正文 + 三线表 + 免责声明。
"""
import logging
import os
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def _fmt_cents(cents: int | None) -> str:
    if cents is None:
        return "⚠️ 需人工核实"
    return f"{cents / 100:,.2f}"


def generate_report_pdf(report_id: int, content: dict) -> str:
    """生成 PDF，返回文件路径"""
    try:
        from weasyprint import HTML  # 延迟导入，未装时不影响其他功能
    except ImportError:
        logger.warning("weasyprint 未安装，PDF 生成不可用")
        raise RuntimeError("weasyprint 未安装：pip install weasyprint")

    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))
    template = env.get_template("report_pdf.html")

    meta = content.get("report_meta", {})
    sections = content.get("sections", {})
    html = template.render(
        meta=meta,
        sections=sections,
        fmt=_fmt_cents,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        disclaimer=content.get("disclaimer", ""),
    )

    os.makedirs(settings.pdf_dir, exist_ok=True)
    path = os.path.join(settings.pdf_dir, f"report_{report_id}.pdf")
    HTML(string=html).write_pdf(path)
    return path
