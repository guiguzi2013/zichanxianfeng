# -*- coding: utf-8 -*-
"""财产线索报告 PDF（2026-09-06 重构新增）

复用 pdf_generator/profile_pdf 的字体/品牌/表格排版，正文为通用 sections 渲染。
调用方（api/clues.py clue_query_report）把查询结果+追索分析清洗为 sections，本模块只排版。
封面标题 = 公司名 + 财产线索报告（正式命名，全篇不出现"财产线索工具/企查查"等内部词）。
"""
import logging
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer,
)

from .pdf_generator import _DARK, _PRIMARY, _esc, _find_logo_path, _register_fonts, _styles
from .profile_pdf import _data_table, _kv_table

logger = logging.getLogger(__name__)


def _head(sec, i):
    _CN = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
    return f"{_CN[i] if i < len(_CN) else i + 1}、{sec['h']}"


def generate_clue_report_pdf(company: str, sections: list, meta: dict, out_path: str) -> str:
    """生成 XXX财产线索报告 PDF。meta: {queried_at, sources, report_no}"""
    _register_fonts()
    st = _styles()
    queried_at = meta.get("queried_at") or ""
    sources = meta.get("sources") or "公开渠道（司法公开 / 信用公示 / 拍卖平台）"

    flow = []
    # 封面占位（由 on_cover 绘制）
    flow.append(Spacer(1, 1))
    # 目录
    flow.append(NextPageTemplate("body"))
    flow.append(PageBreak())
    flow.append(Paragraph("目 录", st["h2"]))
    flow.append(Spacer(1, 12))
    for sec in sections:
        flow.append(Paragraph(_esc(sec["h"]), st["toc_item"]))
    # 正文
    col_w = A4[0] - 4.0 * cm
    for i, sec in enumerate(sections):
        flow.append(PageBreak() if i else Spacer(1, 6))
        flow.append(Paragraph(_esc(_head(sec, i)), st["h2"]))
        flow.append(Spacer(1, 8))
        if sec.get("kvs"):
            flow.append(_kv_table(sec["kvs"], col_w))
            flow.append(Spacer(1, 8))
        for tb in sec.get("tables") or []:
            if tb.get("headers") and tb.get("rows"):
                flow.append(Spacer(1, 4))
                flow.append(_data_table(tb["headers"], tb["rows"], col_w))
                flow.append(Spacer(1, 8))
        if sec.get("note"):
            flow.append(Paragraph(_esc(sec["note"]), st["note"]))
    # 免责
    flow.append(Spacer(1, 20))
    flow.append(Paragraph(_esc(
        "本报告由 NPL CN 平台基于公开渠道（司法公开 / 信用公示 / 拍卖平台）信息生成，数据截至 %s，"
        "仅供参考，不构成投资建议或尽调结论。信息准确性以官方登记为准，重大决策请结合工商、司法等官方渠道复核。" % (queried_at or "查询当日")),
        st["note"]))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    doc = BaseDocTemplate(
        out_path, pagesize=A4,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm, topMargin=2.0 * cm, bottomMargin=2.0 * cm,
        title=f"{company}财产线索报告", author="NPL CN",
    )
    frame_cover = Frame(2.0 * cm, 2.0 * cm, A4[0] - 4.0 * cm, A4[1] - 4.0 * cm, id="cover")
    frame_body = Frame(2.0 * cm, 2.0 * cm, A4[0] - 4.0 * cm, A4[1] - 4.0 * cm, id="body")

    def on_cover(canv, _doc_):
        canv.saveState()
        logo = _find_logo_path()
        if logo:
            try:
                canv.drawImage(logo, 2.0 * cm, A4[1] - 2.6 * cm, width=3.2 * cm, height=1.1 * cm,
                               preserveAspectRatio=True, mask="auto")
            except Exception:
                pass
        canv.setFont("MSYHBD", 12)
        canv.setFillColor(_PRIMARY)
        canv.drawString(2.0 * cm, A4[1] - 3.4 * cm, "财 产 线 索 报 告")
        # 主标题（公司名，可能长 → 拆行居中）
        lines = []
        cur = ""
        for ch in company:
            cur += ch
            if len(cur) >= 16:
                lines.append(cur)
                cur = ""
        if cur:
            lines.append(cur)
        n = len(lines)
        base = A4[1] / 2 + (n - 1) * 24
        canv.setFont("FZXBS", 34 if len(company) <= 12 else 26)
        canv.setFillColor(_DARK)
        for j, ln in enumerate(lines):
            w = canv.stringWidth(ln, canv._fontname, canv._fontsize)
            canv.drawString((A4[0] - w) / 2, base - j * 52, ln)
        y = base - n * 52 - 30
        canv.setFont("MSYH", 10)
        canv.setFillColor(_PRIMARY)
        canv.drawCentredString(A4[0] / 2, y, f"{company} 财产线索报告")
        canv.setFont("MSYH", 9.5)
        canv.setFillColor(colors.HexColor("#444444"))
        info = [
            f"报告类型：财产线索报告",
            f"报告编号：{meta.get('report_no') or '—'}",
            f"数据来源：{sources}",
            f"数据截至：{queried_at}",
            f"生成时间：{meta.get('generated_at') or datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        yy = y - 70
        for line in info:
            w = canv.stringWidth(line, "MSYH", 9.5)
            canv.drawString((A4[0] - w) / 2, yy, line)
            yy -= 18
        canv.setFont("MSYH", 10)
        canv.setFillColor(_PRIMARY)
        canv.drawRightString(A4[0] - 2.0 * cm, 2.2 * cm, "NPL中国 · 不良资产数字化平台")
        canv.restoreState()

    def on_page(canv, _doc_):
        canv.saveState()
        canv.setFont("MSYH", 9)
        canv.setFillColor(colors.HexColor("#666666"))
        canv.drawString(2.0 * cm, A4[1] - 1.2 * cm, "NPL中国 · 财产线索报告")
        canv.drawRightString(A4[0] - 2.0 * cm, A4[1] - 1.2 * cm, "NPL CN")
        canv.drawString(2.0 * cm, 1.1 * cm, f"第 {canv.getPageNumber() - 1} 页" if canv.getPageNumber() > 1 else "")
        canv.drawRightString(A4[0] - 2.0 * cm, 1.1 * cm, queried_at)
        canv.restoreState()

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=on_cover),
        PageTemplate(id="body", frames=[frame_body], onPage=on_page),
    ])
    doc.build(flow)
    return out_path
