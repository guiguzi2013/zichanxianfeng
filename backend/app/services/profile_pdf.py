# -*- coding: utf-8 -*-
"""债务人画像 → "XXX企业速览" PDF（2026-09-04 新增）

复用 pdf_generator 的字体/品牌样式与页眉页脚，正文为通用章节渲染：
调用方（api/debtor_profile.py）先把 qcc 数据清洗为 sections，本模块只排版。
sections: [{h: 章节标题, kvs: [[k,v],...], table: {headers:[], rows:[[]]} | None, note: str|None}]
封面标题 = 公司名 + 企业速览（正式命名，全篇不出现"债务人画像"）。
"""
import logging
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from .pdf_generator import _DARK, _PRIMARY, _esc, _find_logo_path, _h2_style_toc, _register_fonts, _styles

logger = logging.getLogger(__name__)

_TOC_TEMPLATE = ("一、企业基本信息", "二、股权结构与实际控制人", "三、主要人员", "四、对外投资与分支机构",
                 "五、经营与财务", "六、资质与知识产权", "七、司法与合规风险", "八、历史变更")


def _head(sec, i):
    """编号章节标题"""
    return f"{_CN_NUMS[i] if i < len(_CN_NUMS) else i + 1}、{sec['h']}"


_CN_NUMS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二")


def _kv_table(kvs: list, col_w) -> Table:
    rows = [[Paragraph(_esc(k), _kv_style()), Paragraph(_esc(v or "—"), _val_style())] for k, v in kvs]
    t = Table(rows, colWidths=[col_w * 0.34, col_w * 0.66], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d9d9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _data_table(headers, rows, col_w) -> Table:
    data = [[Paragraph(_esc(str(c or "")), _cell_h()) for c in headers]]
    for r in rows:
        data.append([Paragraph(_esc(str(c or "")), _cell()) for c in r])
    t = Table(data, colWidths=[col_w / len(headers)] * len(headers), repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d9d9")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5fb4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _kv_style():
    st = _styles()
    return ParagraphStyle("pkv", parent=st["cell_h"], fontSize=9.5, textColor=colors.HexColor("#333333"))


def _val_style():
    st = _styles()
    return ParagraphStyle("pkv2", parent=st["cell"], fontSize=9.5)


def _cell_h():
    st = _styles()
    return ParagraphStyle("pch", parent=st["cell_h"], fontSize=9, textColor=colors.white)


def _cell():
    st = _styles()
    return ParagraphStyle("pcd", parent=st["cell"], fontSize=8.6)


def generate_profile_pdf(company: str, sections: list, meta: dict, out_path: str) -> str:
    """生成 XXX企业速览 PDF。meta: {queried_at, sources(str), report_no}"""
    body, bold, title = _register_fonts()
    st = _styles()
    queried_at = meta.get("queried_at") or ""
    sources = meta.get("sources") or "企查查（实时接口）"

    flow = []
    # 封面占位（内容由 on_first 绘制）
    flow.append(Spacer(1, 1))
    # 目录
    flow.append(NextPageTemplate("body"))
    flow.append(PageBreak())
    flow.append(Paragraph("目 录", _h2_style_toc()))
    flow.append(Spacer(1, 12))
    toc_items = list(_TOC_TEMPLATE)
    for t in toc_items:
        flow.append(Paragraph(_esc(t), st["toc_item"]))
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
        "本报告由 NPL CN 平台基于企查查公开数据自动生成，数据截至 %s，仅供参考，不构成投资建议或尽调结论。"
        "信息准确性以企查查/官方登记为准，重大决策请结合工商、司法等官方渠道复核。" % (queried_at or "查询当日")),
        st["note"]))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    doc = BaseDocTemplate(
        out_path, pagesize=A4,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm, topMargin=2.0 * cm, bottomMargin=2.0 * cm,
        title=f"{company}企业速览", author="NPL CN",
    )
    frame_cover = Frame(2.0 * cm, 2.0 * cm, A4[0] - 4.0 * cm, A4[1] - 4.0 * cm, id="cover")
    frame_body = Frame(2.0 * cm, 2.0 * cm, A4[0] - 4.0 * cm, A4[1] - 4.0 * cm, id="body")

    def on_page(canv, _doc_):
        canv.saveState()
        canv.setFont("MSYH", 9)
        canv.setFillColor(colors.HexColor("#666666"))
        canv.drawString(2.0 * cm, A4[1] - 1.2 * cm, "NPL中国 · 企业速览")
        canv.drawRightString(A4[0] - 2.0 * cm, A4[1] - 1.2 * cm, "NPL CN")
        canv.drawString(2.0 * cm, 1.1 * cm, f"第 {canv.getPageNumber() - 1} 页" if canv.getPageNumber() > 1 else "")
        canv.drawRightString(A4[0] - 2.0 * cm, 1.1 * cm, queried_at)
        canv.restoreState()

    def on_cover(canv, _doc_):
        # 封面：logo 左上、标题居中、信息区、底部标语
        canv.saveState()
        logo = _find_logo_path()
        if logo:
            try:
                canv.drawImage(logo, 2.0 * cm, A4[1] - 2.6 * cm, width=3.2 * cm, height=1.1 * cm, preserveAspectRatio=True, mask="auto")
            except Exception:
                pass
        canv.setFont("MSYHBD", 12)
        canv.setFillColor(_PRIMARY)
        canv.drawString(2.0 * cm, A4[1] - 3.4 * cm, "企 业 速 览")
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
        # 副题 + 信息
        y = base - n * 52 - 30
        canv.setFont("MSYH", 10)
        canv.setFillColor(_PRIMARY)
        canv.drawCentredString(A4[0] / 2, y, f"{company} 企业速览报告")
        canv.setFont("MSYH", 9.5)
        canv.setFillColor(colors.HexColor("#444444"))
        info = [
            f"报告类型：企业画像速览",
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

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=on_cover),
        PageTemplate(id="body", frames=[frame_body], onPage=on_page),
    ])
    doc.build(flow)
    return out_path
