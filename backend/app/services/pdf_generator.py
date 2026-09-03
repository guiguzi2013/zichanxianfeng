"""PDF 报告生成（reportlab：纯 Python，无系统依赖，Windows/Linux 均可用）

对应 12 章节报告结构：封面 + 目录 + 12 版块正文 + 三线表 + 免责声明。
替代原 WeasyPrint 实现（Windows 缺 GTK 无法运行）。
"""
import logging
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------- 字体注册 ----------------
# 候选字体：Windows 优先，其次常见 Linux 路径（Docker 需安装 fonts-noto-cjk）
_MSYH_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
_MSYHBD_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
_SIMSUN_CANDIDATES = [
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
]
# 封面大标题专用：方正小标宋（用户提供，公文书标题字体）
_FZXBS_CANDIDATES = [
    r"Q:\deepseek\font\方正小标宋简体.ttf",
    r"Q:\deepseek\zichanxianfeng\backend\data\fonts\方正小标宋简体.ttf",
    r"C:\Windows\Fonts\FZXBSJW.TTF",
    r"C:\Windows\Fonts\方正小标宋简体.ttf",
]

_FONT_REGISTERED = False


def _find_font(candidates: list[str]) -> str | None:
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _find_logo_path() -> str | None:
    """查找本站 logo（frontend/public/logo.png），供 PDF 封面使用"""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "public", "logo.png"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "public", "logo.png?v=3"),
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "public", "logo.png"),
    ]
    for p in candidates:
        norm = os.path.normpath(p)
        if os.path.exists(norm):
            return norm
    return None


def _register_fonts() -> tuple[str, str, str]:
    """注册中文字体，返回 (正文, 粗体, 标题)。TTC 需 subfontIndex=0。"""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return ("MSYH", "MSYHBD", "MSYHBD")

    body_path = _find_font(_MSYH_CANDIDATES)
    bold_path = _find_font(_MSYHBD_CANDIDATES)
    serif_path = _find_font(_SIMSUN_CANDIDATES)
    fzxbs_path = _find_font(_FZXBS_CANDIDATES)

    if not body_path:
        raise RuntimeError("未找到中文字体（需要 msyh.ttc 或 NotoSansCJK），无法生成 PDF")

    pdfmetrics.registerFont(TTFont("MSYH", body_path, subfontIndex=0))
    if bold_path:
        pdfmetrics.registerFont(TTFont("MSYHBD", bold_path, subfontIndex=0))
    else:
        pdfmetrics.registerFont(TTFont("MSYHBD", body_path, subfontIndex=0))
    if serif_path:
        pdfmetrics.registerFont(TTFont("SimSun", serif_path, subfontIndex=0))
    # 封面大标题：方正小标宋（公文书标题字体）
    if fzxbs_path:
        pdfmetrics.registerFont(TTFont("FZXBS", fzxbs_path, subfontIndex=0))
    pdfmetrics.registerFontFamily("MSYH", normal="MSYH", bold="MSYHBD", italic="MSYH", boldItalic="MSYHBD")
    _FONT_REGISTERED = True
    return ("MSYH", "MSYHBD", "MSYHBD")


# ---------------- 样式 ----------------
_PRIMARY = colors.HexColor("#1a5fb4")
_DARK = colors.HexColor("#0d3b73")
_GRAY = colors.HexColor("#555555")
_LIGHT_BG = colors.HexColor("#f2f6fb")
_WARN_BG = colors.HexColor("#faf7ef")
_WARN_EDGE = colors.HexColor("#d48806")
_DANGER_BG = colors.HexColor("#fdf1f1")
_DANGER_EDGE = colors.HexColor("#cf1322")


def _styles() -> dict:
    body, bold, title = _register_fonts()
    # 封面大标题专用：方正小标宋（FZXBS，公文书标题字体）；找不到时回退宋体/默认
    try:
        pdfmetrics.getFont("FZXBS")
        cover_title_font = "FZXBS"
    except Exception:
        try:
            pdfmetrics.getFont("SimSun")
            cover_title_font = "SimSun"
        except Exception:
            cover_title_font = title
    return {
        "cover_logo": ParagraphStyle("cover_logo", fontName=title, fontSize=16, leading=24,
                                     alignment=TA_CENTER, textColor=_DARK, spaceAfter=16),
        "cover_title": ParagraphStyle("cover_title", fontName=cover_title_font, fontSize=36, leading=46,
                                      alignment=TA_CENTER, textColor=_DARK),
        "cover_debtor": ParagraphStyle("cover_debtor", fontName=body, fontSize=13, leading=22,
                                       alignment=TA_CENTER, textColor=colors.HexColor("#333333"),
                                       spaceBefore=34),
        "cover_meta": ParagraphStyle("cover_meta", fontName=body, fontSize=10.5, leading=22,
                                     alignment=TA_CENTER, textColor=colors.HexColor("#444444"),
                                     spaceBefore=26),
        "cover_footer": ParagraphStyle("cover_footer", fontName=title, fontSize=11, leading=16,
                                       alignment=TA_CENTER, textColor=_PRIMARY, spaceBefore=52),
        "toc_item": ParagraphStyle("toc_item", fontName=body, fontSize=11, leading=22),
        "h2": ParagraphStyle("h2", fontName=title, fontSize=15, leading=22, textColor=_PRIMARY,
                             spaceBefore=20, spaceAfter=10),
        "h3": ParagraphStyle("h3", fontName=title, fontSize=12, leading=18, textColor=_DARK,
                             spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("body", fontName=body, fontSize=10.5, leading=17,
                               textColor=colors.HexColor("#222222")),
        "cell": ParagraphStyle("cell", fontName=body, fontSize=9.5, leading=14,
                               textColor=colors.HexColor("#222222")),
        "cell_h": ParagraphStyle("cell_h", fontName=title, fontSize=9.5, leading=14,
                                 textColor=colors.HexColor("#222222")),
        "num": ParagraphStyle("num", fontName=body, fontSize=9.5, leading=14,
                              alignment=2, textColor=colors.HexColor("#222222")),
        "warn": ParagraphStyle("warn", fontName=body, fontSize=9.5, leading=15,
                               textColor=colors.HexColor("#614700")),
        "note": ParagraphStyle("note", fontName=body, fontSize=9, leading=14,
                               textColor=colors.HexColor("#666666")),
        "li": ParagraphStyle("li", fontName=body, fontSize=10, leading=17,
                             textColor=colors.HexColor("#222222"), leftIndent=12, bulletIndent=0),
    }


# ---------------- 工具 ----------------
def _esc(text) -> str:
    """转义 HTML 特殊字符（Paragraph 用）+ 清理 emoji（reportlab 字体不支持）"""
    if text is None:
        return ""
    s = str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for emoji, repl in [("⚠️", "[!]"), ("⚠", "[!]"), ("✅", "[✓]"), ("📝", "[·]"),
                        ("⏱", ""), ("☑", "[✓]"), ("☐", "[ ]"), ("★", "★"), ("☆", "☆")]:
        s = s.replace(emoji, repl)
    return s


# 清洗系统内部技术性文案（异常类名/反爬/滑块/超时等不出现在报告）
_TECH_PATTERNS = (
    r"HTTP\w*Error", r"HTTPStatus", r"反爬", r"滑块",
    r"超时|timeout", r"连接失败|Connection", r"回退", r"未启用",
)


def _clean_note(text) -> str:
    if not text:
        return ""
    s = str(text)
    import re as _re
    for p in _TECH_PATTERNS:
        if _re.search(p, s):
            return "暂未获取到，建议人工核实"
    return s


# ---------------- 下载版报告清洗（网页保留，PDF 删除"未完成工作"提示） ----------------
# 领导/外部可见的下载报告不能出现"待核实/待补充/需人工核实/请补充"等未完成工作字样，
# 这些提示只在网页端对用户展示。这里统一识别并删除。
_PDF_UNFINISHED_MARKERS = [
    "需人工核实", "待人工核实", "待核实", "待补充", "暂未获取到",
    "建议人工核实", "建议上传补充材料", "建议补充", "人工补充",
    "请在补充材料", "在报告底部补充", "本页底部补充", "请补充",
    "无法估算", "无法计算", "数据不足", "无法确认",
    "未检索到", "未提取到",
]


def _pdf_unfinished(text) -> bool:
    """判断文本是否属于"未完成工作"提示（下载报告中应删除）"""
    if not text:
        return False
    s = str(text)
    return any(m in s for m in _PDF_UNFINISHED_MARKERS)


def _pdf_clean_note(text) -> str:
    """清洗说明类文本：删除"未完成工作"后缀，保留正常内容；全删则返回空串"""
    if not text:
        return ""
    s = str(text)
    for m in [
        "如有详细信息请在报告底部补充", "如有利息计算信息请在报告底部补充",
        "可以本页底部补充", "请在补充材料中补齐", "请在补充材料中上传",
        "本息为估算，建议上传补充材料", "，建议人工核实", "，需人工核实", "需人工核验",
    ]:
        s = s.replace(m, "")
    s = s.strip("，。；;、 \t\n")
    if not s or _pdf_unfinished(s):
        return ""
    return s


def _fmt_cents(cents) -> str:
    """分 → 元 字符串（PDF 中缺失显示 —）"""
    if cents is None:
        return "—"
    return f"{cents / 100:,.2f}"


def _fmt_wan(cents) -> str:
    """分 → 万元（4 位小数；PDF 中缺失显示 —）"""
    if cents is None:
        return "—"
    return f"{cents / 100 / 10000:.4f}"


def _three_line_table(data: list[list], col_widths: list, header_rows: int = 1) -> Table:
    """三线表：顶线 1.5pt + 表头下线 0.75pt + 行下线 0.25pt + 底线 1.5pt"""
    t = Table(data, colWidths=col_widths, repeatRows=header_rows)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, header_rows - 1), 1.5, colors.black),
        ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.75, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.black),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), _LIGHT_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    t.setStyle(TableStyle(style))
    return t


def _two_col_table(rows: list[tuple], label_w: float = 6.2 * cm) -> Table:
    """两列信息表（label | value）"""
    body, bold, title = _register_fonts()
    data = []
    for k, v in rows:
        data.append([Paragraph(_esc(k), _styles()["cell_h"]), Paragraph(_esc(v), _styles()["cell"])])
    t = Table(data, colWidths=[label_w, A4[0] - 2 * 2.0 * cm - label_w], repeatRows=0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#cccccc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7f9fc")),
    ]
    t.setStyle(TableStyle(style))
    return t


def _callout(text: str, kind: str = "warn") -> Table:
    """警示/危险 提示块（左边缘色条 + 浅背景）"""
    bg = _WARN_BG if kind == "warn" else _DANGER_BG
    edge = _WARN_EDGE if kind == "warn" else _DANGER_EDGE
    t = Table([[Paragraph(_esc(text), _styles()["warn"])]], colWidths=[A4[0] - 2 * 2.0 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3, edge),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _h2(text: str) -> Table:
    """章节标题（蓝色 + 下边框）"""
    t = Table([[Paragraph(_esc(text), _styles()["h2"])]], colWidths=[A4[0] - 2 * 2.0 * cm])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1, _PRIMARY),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _ul(items: list, style_key: str = "li") -> list:
    """无序列表 flowables"""
    out = []
    for it in items or []:
        out.append(Paragraph(f"• {_esc(it)}", _styles()[style_key]))
    return out


# ---------------- 版块渲染 ----------------
def _render_summary(s: dict) -> list:
    flow = [_h2("一、尽调结论摘要")]
    rows = [("综合评级", s.get("rating") or "—")]
    flow.append(_two_col_table(rows))
    logic = [x for x in (s.get("core_logic") or []) if not _pdf_unfinished(x)]
    if logic:
        flow.append(Spacer(1, 6))
        flow.extend(_ul(logic))
    return flow


def _render_reminders(s: dict) -> list:
    flow = [_h2("二、重要提醒")]
    items = [r for r in (s.get("items") or [])
             if not _pdf_unfinished(r.get("content")) and not _pdf_unfinished(r.get("trigger"))]
    if items:
        data = [[Paragraph("规则", _styles()["cell_h"]), Paragraph("触发条件", _styles()["cell_h"]),
                 Paragraph("提醒内容", _styles()["cell_h"])]]
        for r in items:
            data.append([
                Paragraph(_esc(r.get("rule_id") or ""), _styles()["cell"]),
                Paragraph(_esc(r.get("trigger") or ""), _styles()["cell"]),
                Paragraph(_esc(r.get("content") or ""), _styles()["cell"]),
            ])
        flow.append(_three_line_table(data, [3.0 * cm, 4.5 * cm, 8.5 * cm]))
    else:
        flow.append(Paragraph("未触发特殊提醒。", _styles()["note"]))
    return flow


def _render_claim_basic(s: dict) -> list:
    flow = [_h2("三、债权基本情况")]
    bt = s.get("basic_table") or {}
    rows = [
        ("债务人名称", bt.get("debtor_name") or "—"),
        ("债权本金", _fmt_cents(bt.get("principal_cents"))),
        ("利息/罚息", _fmt_cents(bt.get("interest_cents"))),
        ("担保类型", bt.get("guaranty_type") or "—"),
        ("担保人", bt.get("guarantor") or "无"),
        ("抵押物", bt.get("collateral") or "无"),
        ("司法状态", bt.get("judicial_status") or "—"),
        ("地区", bt.get("region") or "—"),
        ("抵押物类型", bt.get("collateral_type") or "—"),
        # 2026-09-02：房产证/抵押物明细（证上有的字段全部展示）
        ("产权证号", bt.get("property_cert_no") or "—"),
        ("权利人", bt.get("property_owner") or "—"),
        ("房屋用途", bt.get("property_use") or "—"),
        ("抵押登记编号", bt.get("mortgage_reg_no") or "—"),
        ("土地面积", f"{bt.get('land_area_sqm')}㎡" if bt.get("land_area_sqm") else "—"),
        ("建筑面积", f"{bt.get('building_area_sqm')}㎡" if bt.get("building_area_sqm") else "—"),
        ("建成年份", str(bt.get("build_year")) if bt.get("build_year") else "—"),
        ("建筑结构", bt.get("structure_type") or "—"),
        ("计息起始日", bt.get("interest_base_date") or "—"),
        ("案件号", bt.get("case_number") or "—"),
        ("案由", bt.get("case_cause") or "—"),
    ]
    flow.append(_two_col_table(rows))

    idetail = s.get("interest_detail") or {}
    mode = idetail.get("mode")
    if mode and mode != "none":
        flow.append(Spacer(1, 8))
        mode_label = {
            "with_judgment": "按判决书利率",
            "cutoff_continue": "截止日利息 + LPR续算",
            "cutoff_no_continue": "按录入利息",
            "no_info": "按录入利息",
        }.get(mode, "按LPR估算")
        flow.append(Paragraph(f"本息计算明细（{mode_label}，计算至 {idetail.get('end_date') or '报告当日'}）", _styles()["h3"]))
        data = [[Paragraph("项目", _styles()["cell_h"]), Paragraph("金额（元）", _styles()["cell_h"]),
                 Paragraph("说明", _styles()["cell_h"])]]
        for it in idetail.get("items") or []:
            data.append([
                Paragraph(_esc(it.get("name") or ""), _styles()["cell"]),
                Paragraph(_fmt_cents(it.get("amount_cents")), _styles()["num"]),
                Paragraph(_esc(_pdf_clean_note(it.get("note"))), _styles()["cell"]),
            ])
        flow.append(_three_line_table(data, [3.5 * cm, 4.0 * cm, 8.5 * cm]))
        # 利息说明（图2位置）：只保留正常说明，删除"未完成工作"类提示
        basis = _pdf_clean_note(idetail.get("basis_note"))
        if basis:
            flow.append(Spacer(1, 6))
            flow.append(_callout(basis, kind="warn"))
    return flow


def _render_legal_completeness(s: dict) -> list:
    flow = [_h2("四、法律文件完备性")]
    items = [it for it in (s.get("items") or [])
             if not _pdf_unfinished(it.get("status")) and not _pdf_unfinished(it.get("note"))]
    if items:
        data = [[Paragraph("文件/事项", _styles()["cell_h"]), Paragraph("状态", _styles()["cell_h"]),
                 Paragraph("说明", _styles()["cell_h"])]]
        for it in items:
            data.append([
                Paragraph(_esc(it.get("item") or ""), _styles()["cell"]),
                Paragraph(_esc(it.get("status") or ""), _styles()["cell"]),
                Paragraph(_esc(_pdf_clean_note(it.get("note"))), _styles()["cell"]),
            ])
        flow.append(_three_line_table(data, [5.0 * cm, 2.5 * cm, 8.5 * cm]))
        note = _pdf_clean_note(s.get("note"))
        if note:
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(_esc(note), _styles()["note"]))
    else:
        flow.append(Paragraph("法律文件以原件为准。", _styles()["note"]))
    return flow


def _render_debtor(s: dict) -> list:
    flow = [_h2("五、债务人调查")]
    if s.get("type") == "person":
        flow.append(Paragraph("自然人债务人：无工商信息，重点关注司法风险。", _styles()["body"]))
    else:
        basic = s.get("basic")
        if basic:
            if isinstance(basic, dict):
                rows = [(str(k), str(v)) for k, v in basic.items() if not _pdf_unfinished(str(v))]
                if rows:
                    flow.append(_two_col_table(rows))
            else:
                flow.append(Paragraph(_esc(basic), _styles()["body"]))
        # 数据截至年份（共享缓存 1 年；2026-08-31 用户确认只标年份，利息另行实时计算）
        if s.get("data_as_of"):
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(f"数据截至：{_esc(s['data_as_of'])}（共享数据，来源企查查）", _styles()["note"]))
        jr = s.get("judicial_risk") or {}
        if jr.get("note"):
            note = _pdf_clean_note(jr["note"])
            if note:
                flow.append(Spacer(1, 6))
                flow.append(Paragraph(f"司法风险：{_esc(note)}", _styles()["body"]))
        if s.get("shareholders"):
            sh = s["shareholders"]
            if isinstance(sh, dict) and sh.get("note"):
                note = _pdf_clean_note(sh["note"])
                if note:
                    flow.append(Spacer(1, 4))
                    flow.append(Paragraph(f"股东信息：{_esc(note)}", _styles()["note"]))
        for f in s.get("risk_factors") or []:
            flow.append(Paragraph(f"• {_esc(f.get('label') or '')}：{f.get('count') or 0} 条", _styles()["li"]))
    return flow


def _render_guarantor(s: dict) -> list:
    flow = [_h2("六、担保人调查")]
    if s.get("present"):
        flow.append(Paragraph("存在保证担保。", _styles()["body"]))
        if s.get("note"):
            note = _pdf_clean_note(s["note"])
            if note:
                flow.append(Paragraph(_esc(note), _styles()["note"]))
    else:
        flow.append(Paragraph("无保证担保信息。", _styles()["note"]))
    return flow


def _render_collateral(s: dict) -> list:
    flow = [_h2("七、抵押物分析")]
    if not s.get("present"):
        note = _pdf_clean_note(s.get("note") or "无抵押物信息。")
        flow.append(Paragraph(_esc(note or "无抵押物信息。"), _styles()["note"]))
        return flow
    flow.append(Paragraph(_esc(s.get("collateral_desc") or "—"), _styles()["body"]))

    val = s.get("valuation") or {}
    if val.get("conservative_cents"):
        flow.append(Spacer(1, 8))
        rows = [
            ("估值区间（粗估）",
             f"{_fmt_wan(val.get('conservative_cents'))} ~ {_fmt_wan(val.get('optimistic_cents'))} 万元"),
            ("单价参考", val.get("unit_price_range") or "—"),
            ("面积", f"{val.get('area_sqm') or '—'} ㎡"),
            ("抵押物类型", val.get("collateral_type") or "—"),
        ]
        flow.append(_two_col_table(rows))
        # 成本法计算明细
        if s.get("valuation_method") == "cost" and s.get("valuation_notes"):
            notes = [n for n in s["valuation_notes"] if not _pdf_unfinished(n)]
            if notes:
                flow.append(Spacer(1, 4))
                flow.append(Paragraph("成本法粗估明细（土地出让价 + 建筑建安造价×折旧）", _styles()["h3"]))
                flow.extend(_ul(notes))
        # 主参考估值（经济下行取档）
        if val.get("reference_cents") and val.get("reference_label"):
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(
                f"{_esc(val['reference_label'])}：{_fmt_wan(val['reference_cents'])} 万元", _styles()["h3"]))
        note = _pdf_clean_note(val.get("estimate_note"))
        if note:
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(_esc(note), _styles()["note"]))

    cov = s.get("coverage_vs_interest") or {}
    if cov.get("interest_total_cents"):
        flow.append(Spacer(1, 8))
        rows = [
            (cov.get("collateral_label") or "抵押物主参考估值", f"{_fmt_wan(cov.get('collateral_cents'))} 万元"),
            ("本息合计", f"{_fmt_wan(cov.get('interest_total_cents'))} 万元"),
        ]
        if cov.get("coverage_ratio") is not None:
            rows.append(("覆盖比例（本息/抵押物）", f"{cov['coverage_ratio']}%（{'覆盖' if cov.get('covered') else '未覆盖'}）"))
        flow.append(_two_col_table(rows))
        if cov.get("note"):
            note = _pdf_clean_note(cov["note"])
            if note:
                flow.append(Spacer(1, 4))
                flow.append(Paragraph(_esc(note), _styles()["note"]))
    if s.get("ai_note"):
        note = _pdf_clean_note(s["ai_note"])
        if note:
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(f"解读：{_esc(note)}", _styles()["body"]))
    return flow


def _render_legal(s: dict) -> list:
    flow = [_h2("八、法律文书与法规依据")]
    docs = s.get("documents") or {}
    note = _pdf_clean_note(docs.get("not_found_note"))
    if note:
        flow.append(Paragraph(_esc(note), _styles()["body"]))
    # 法规依据：引用知识库匹配的具体现行法规（依据《XX法》），无匹配则不输出
    statutes = s.get("statutes") or []
    if statutes:
        flow.append(Spacer(1, 6))
        flow.append(Paragraph("法规依据（依据现行有效法规）：", _styles()["h3"]))
        for st in statutes:
            name = _esc(st.get("name") or "")
            doc_no = _esc(st.get("doc_no") or "")
            line = f"《{name}》" + (f"（{doc_no}）" if doc_no else "")
            flow.append(Paragraph(line, _styles()["body"]))
            if st.get("summary"):
                flow.append(Paragraph(_esc(st["summary"]), _styles()["note"]))
            flow.append(Spacer(1, 4))
    if s.get("supplement_note"):
        note = _pdf_clean_note(s["supplement_note"])
        if note:
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(_esc(note), _styles()["note"]))
    return flow


def _render_execution_recovery(s: dict) -> list:
    flow = [_h2("九、司法执行与受偿分析")]
    if not s:
        flow.append(Paragraph("暂无司法执行信息。", _styles()["note"]))
        return flow
    rows = []
    for label, key in [("司法状态", "judicial_status"), ("抵押顺位", "mortgage_rank"),
                       ("查封情况", "seizure")]:
        v = s.get(key)
        if v and not _pdf_unfinished(v):
            rows.append((label, v))
    rec = s.get("execution_records") or {}
    if rec:
        rows.append(("被执行人记录", f"{rec.get('executed') or 0} 条"))
        rows.append(("失信信息", f"{rec.get('dishonest') or 0} 条"))
        rows.append(("限制高消费", f"{rec.get('limited_consumption') or 0} 条"))
    if rows:
        flow.append(_two_col_table(rows))
    if s.get("repayment_priority_note"):
        note = _pdf_clean_note(s["repayment_priority_note"])
        if note:
            flow.append(Spacer(1, 6))
            flow.append(Paragraph(_esc(note), _styles()["note"]))
    obj = s.get("execution_objection_risk") or {}
    if obj.get("risk"):
        flow.append(Spacer(1, 6))
        flow.append(_callout(obj["risk"]))
        if obj.get("law_ref"):
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(f"法律依据：{_esc(obj['law_ref'])}", _styles()["note"]))
    if s.get("ai_note"):
        note = _pdf_clean_note(s["ai_note"])
        if note:
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(f"解读：{_esc(note)}", _styles()["body"]))
    return flow


def _render_risk(s: dict) -> list:
    flow = [_h2("十、风控评估")]
    favorable = [x for x in (s.get("favorable") or []) if not _pdf_unfinished(x)]
    risk = [x for x in (s.get("risk") or []) if not _pdf_unfinished(x)]
    if favorable:
        flow.append(Paragraph("有利因素", _styles()["h3"]))
        flow.extend(_ul(favorable))
    if risk:
        flow.append(Paragraph("风险因素", _styles()["h3"]))
        flow.extend(_ul(risk))
    if not favorable and not risk:
        flow.append(Paragraph("综合评估见本报告各章节。", _styles()["note"]))
    return flow


def _render_disposal(s: dict) -> list:
    flow = [_h2("十一、处置方案")]
    paths = s.get("paths") or []
    paths = [p for p in paths if not _pdf_unfinished(p.get("name"))]
    if not paths:
        flow.append(Paragraph("处置方案详见各章节分析。", _styles()["note"]))
        return flow
    for i, p in enumerate(paths):
        flow.append(Paragraph(f"路径{i + 1}：{_esc(p.get('name') or '处置路径')}", _styles()["h3"]))
        if p.get("detail"):
            flow.append(Paragraph(_esc(_pdf_clean_note(p["detail"])), _styles()["body"]))
        if p.get("cycle_estimate"):
            flow.append(Paragraph(f"预计周期：{_esc(_pdf_clean_note(p['cycle_estimate']))}", _styles()["note"]))
        if p.get("risk"):
            risk = _pdf_clean_note(p["risk"])
            if risk:
                flow.append(Spacer(1, 4))
                flow.append(_callout(f"风险：{risk}"))
    if s.get("note"):
        note = _pdf_clean_note(s["note"])
        if note:
            flow.append(Spacer(1, 8))
            flow.append(Paragraph(_esc(note), _styles()["note"]))
    if s.get("coverage_warning"):
        note = _pdf_clean_note(s["coverage_warning"])
        if note:
            flow.append(Spacer(1, 4))
            flow.append(_callout(note, kind="warn"))
    if s.get("ai_note"):
        note = _pdf_clean_note(s["ai_note"])
        if note:
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(f"解读：{_esc(note)}", _styles()["body"]))
    return flow


def _render_pending(s: list) -> list:
    # 下载版报告不展示"待补充信息"（未完成工作提示只在网页端显示）
    return []


def _render_supplement_info(s: dict) -> list:
    flow = [_h2("补充信息")]
    if not s or (not s.get("user_notes") and not s.get("file_count")):
        return []
    if s.get("summary"):
        flow.append(Paragraph(_esc(s["summary"]), _styles()["body"]))
        flow.append(Spacer(1, 4))
    notes = s.get("user_notes") or []
    if notes:
        flow.append(Paragraph("用户补充说明", _styles()["h3"]))
        flow.extend(_ul(notes))
    if s.get("file_count"):
        flow.append(Spacer(1, 4))
        flow.append(Paragraph(f"补充材料：已上传 {s['file_count']} 份（判决书/评估报告/尽调说明等），已结合到本报告分析中。", _styles()["body"]))
    return flow


# ---------------- 主入口 ----------------
def generate_report_pdf(report_id: int, content: dict) -> str:
    """生成 PDF，返回文件路径"""
    st = _styles()
    meta = content.get("report_meta", {})
    sections = content.get("sections", {})

    # 封面 + 目录 + 正文 flowables
    flow = []

    # ---- 封面 ----
    # 封面全部由 canvas 在 onPage 回调中绝对定位绘制：
    #   logo 左上角 → 标题(方正小标宋48号)垂直居中 → 标题下方蓝线 → 信息区 → 标语右下角(大边距)
    generated_at = meta.get("generated_at") or ""
    try:
        generated_at = datetime.fromisoformat(str(generated_at)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        generated_at = str(generated_at)[:16]

    data_sources = meta.get("data_sources") or []
    cover_info = {
        "debtor": meta.get("debtor_name") or "—",
        "report_no": meta.get("report_no") or "—",
        "generated_at": generated_at,
        "data_sources": "、".join(data_sources) if data_sources else "—",
        "logo_path": _find_logo_path(),
    }
    # 封面页不放流式内容（仅一个空 spacer 占位，实际内容在 cover onPage 绘制）
    flow.append(Spacer(1, 1))

    # ---- 目录 ----
    toc_items = [
        "一、尽调结论摘要", "二、重要提醒", "三、债权基本情况", "四、法律文件完备性",
        "五、债务人调查", "六、担保人调查", "七、抵押物分析", "八、法律文书与法规依据",
        "九、司法执行与受偿分析", "十、风控评估", "十一、处置方案",
    ]
    flow.append(NextPageTemplate("body"))
    flow.append(PageBreak())
    flow.append(Paragraph("目 录", _h2_style_toc()))
    flow.append(Spacer(1, 12))
    for t in toc_items:
        flow.append(Paragraph(_esc(t), st["toc_item"]))

    # ---- 正文 ----
    flow.append(PageBreak())
    flow.extend(_render_summary(sections.get("summary") or {}))
    flow.extend(_render_reminders(sections.get("reminders") or {}))
    flow.extend(_render_claim_basic(sections.get("claim_basic") or {}))
    flow.extend(_render_legal_completeness(sections.get("legal_completeness") or {}))
    flow.extend(_render_debtor(sections.get("debtor") or {}))
    flow.extend(_render_guarantor(sections.get("guarantor") or {}))
    flow.extend(_render_collateral(sections.get("collateral") or {}))
    flow.extend(_render_legal(sections.get("legal") or {}))
    flow.extend(_render_execution_recovery(sections.get("execution_recovery") or {}))
    flow.extend(_render_risk(sections.get("risk") or {}))
    flow.extend(_render_disposal(sections.get("disposal") or {}))
    flow.extend(_render_pending(sections.get("pending_supplements") or []))
    flow.extend(_render_supplement_info(sections.get("supplement_info") or {}))

    # 免责声明
    flow.append(Spacer(1, 24))
    disclaimer = content.get("disclaimer") or ""
    flow.append(Paragraph(_esc(disclaimer), _styles()["note"]))

    os.makedirs(settings.pdf_dir, exist_ok=True)
    path = os.path.join(settings.pdf_dir, f"report_{report_id}.pdf")

    doc = BaseDocTemplate(
        path, pagesize=A4,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm,
        topMargin=2.0 * cm, bottomMargin=2.0 * cm,
        title=f"债权尽职调查报告 - {meta.get('debtor_name') or ''}",
        author="NPL CN",
    )
    frame_cover = Frame(2.0 * cm, 2.0 * cm, A4[0] - 4.0 * cm, A4[1] - 4.0 * cm, id="cover")
    frame_body = Frame(2.0 * cm, 2.0 * cm, A4[0] - 4.0 * cm, A4[1] - 4.0 * cm, id="body")

    def on_page(canv, doc_):
        canv.saveState()
        canv.setFont("MSYH", 9)
        canv.setFillColor(colors.HexColor("#666666"))
        canv.drawCentredString(A4[0] / 2, 1.1 * cm, f"- {canv.getPageNumber()} -")
        canv.restoreState()

    def on_cover(canv, doc_):
        """封面页 canvas 绘制：logo 左上角 + 48号标题垂直居中 + 蓝线 + 信息区 + 标语右下角"""
        _register_fonts()
        W, H = A4
        ml = 1.2 * cm   # 左边距（logo 更靠左上角）
        mr = 2.5 * cm   # 右边距（标语用）
        mt = 1.2 * cm   # 上边距（logo 更靠左上角）

        # 1) logo 左上角
        logo_path = cover_info.get("logo_path")
        logo_bottom = H - mt  # logo 底部 y（无 logo 时兜底）
        try:
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(logo_path)
            iw, ih = ir.getSize()
            lw = 3.5 * cm
            lh = lw * ih / iw
            logo_bottom = H - mt - lh
            canv.drawImage(logo_path, ml, logo_bottom, width=lw, height=lh,
                           preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001
            canv.setFont("MSYHBD", 16)
            canv.setFillColor(_DARK)
            logo_bottom = H - mt - 20
            canv.drawString(ml, logo_bottom, "NPL中国 · 中国不良资产尽调与投融资平台")

        # 2) logo 下方黑色细横线（左右满屏，类似 Word 页眉；按豆包原图用黑色）
        line_y = logo_bottom - 12
        canv.setStrokeColor(colors.black)
        canv.setLineWidth(1)  # 细线
        canv.line(0, line_y, W, line_y)

        # 3) 大标题：方正小标宋 48 号，位于页面 ~30% 高度（参考豆包商业布局，非垂直居中）
        try:
            pdfmetrics.getFont("FZXBS")
            title_font = "FZXBS"
        except Exception:
            title_font = "MSYHBD"
        canv.setFont(title_font, 48)
        canv.setFillColor(_DARK)
        title_text = "债权尽职调查报告"
        title_w = canv.stringWidth(title_text, title_font, 48)
        title_y = H * 0.70  # 标题基准线：标题底部视觉 ~30% 高度（参考豆包商业布局）
        canv.drawString((W - title_w) / 2, title_y, title_text)

        # 4) 信息区：债务人/编号/日期/来源（居中，位于标题下方，行间距紧凑——参考豆包布局）
        info_y = title_y - 70  # 标题与信息区间距
        canv.setFont("MSYH", 12)
        canv.setFillColor(colors.HexColor("#333333"))
        info_lines = [
            f"债务人：{cover_info['debtor']}",
            f"报告编号：{cover_info['report_no']}",
            f"报告日期：{cover_info['generated_at']}",
            f"数据来源：{cover_info['data_sources']}",
        ]
        for line in info_lines:
            lw_ = canv.stringWidth(line, "MSYH", 12)
            canv.drawString((W - lw_) / 2, info_y, line)
            info_y -= 22  # 紧凑行距（豆包风格）

        # 5) 标语：右下角（与底边、右边保留较大边距）
        canv.setFont("MSYHBD", 11)
        canv.setFillColor(_PRIMARY)
        footer_text = "NPL中国 · 不良资产数字化平台"
        canv.drawRightString(W - mr, 2.2 * cm, footer_text)

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=on_cover),
        PageTemplate(id="body", frames=[frame_body], onPage=on_page),
    ])
    doc.build(flow)
    logger.info("reportlab PDF generated: %s", path)
    return path


def _h2_style_toc():
    """目录标题样式（无下边框）"""
    body, bold, title = _register_fonts()
    return ParagraphStyle("toc_h", fontName=title, fontSize=15, leading=22, textColor=_PRIMARY)
