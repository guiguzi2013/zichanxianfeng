"""抓取条目完整性门槛（2026-09-05 用户确认，方案 A：信息量太少直接放弃）

精选债权/捡漏 落库前过滤：信息不全面的条目直接放弃，保证页面观感正规。
2026-09-05 升级口径（用户看到详情页大量空白后拍板"彻底清除+抓取即弃"）：
- 不仅要有 金额/起拍价，还须有**实质描述信息**（抵押物描述/抵押类型/地区/利息/原文摘要任一），
  只有"债务人名+金额+起拍价"而其余全空的（典型：阿里打码系列 青岛**进出口/青岛某机械…、
  破产应收仅列金额）一律放弃——它们详情页打开几乎全空，观感差、也无法支撑尽调。
- 债务人不做强求（平台对个人/部分债权打码），但**全打码且无实质内容**的仍会被"无实质信息"拦下。
- 2026-09-05 二次收紧：占位/一句话正文（"详见竞买公告。""详见资产明细表"等）不算实质——
  京东个人债权详情接口只回一句、原文抓不到的，按"抓不到正文=放弃"处理（用户拍板）。

门槛（featured 与 bargain 统一）：
1. 起拍价必须有
2. 债权金额 或 资产金额 必须有
3. 实质信息至少一项：抵押物描述 / 抵押类型 / 地区 / 利息 / 有效原文(非占位,>=15字) / 公告表格
   （bargain 捡漏比 featured 更严：地区不算，须有 原文/表格/抵押/利息 之一——见 _substance_body）
"""
from __future__ import annotations

import re

# 占位/一句话正文：详情接口只回一句，视为正文抓取失败（2026-09-05 用户：一句话详情删除/不再抓）
_PLACEHOLDER_RE = re.compile(
    r'^\s*(?:详见竞买公告|详见资产明细表|详见公告|详见附件|见竞买公告|见公告|详见拍卖公告|详见招商公告|'
    r'详见原公告|详见合同|详见清单|标的物调查情况表|拍卖标的物调查情况表|详见竞买须知|详见公告正文|'
    r'详见其他文件|详情见公告|以公告为准|公告详情请见原文|详见网页|详见链接)\s*[。.！!]?\s*$'
)


def _has(v) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return s not in ("", "None", "0", "0万", "0元", "未知", "待定", "面议", "—", "-")


def _raw_ok(raw) -> bool:
    """有效原文：非空、非占位一句话、长度≥15（京东公告/询价正文一般 200+ 字）"""
    if not raw:
        return False
    s = str(raw).strip()
    if _PLACEHOLDER_RE.match(s):
        return False
    return len(s) >= 15


def _price_of(d: dict):
    return d.get("listing_price") or d.get("current_price")


def _substance_of(d: dict, summary: str = "") -> bool:
    """是否有实质描述信息（结构性字段：抵押描述/抵押类型/地区/利息/有效原文/公告表格）。
    2026-09-05 修正：summary 摘要文案（如"债务人 X，本金 Y…"）是抓取自动生成的模板文本，
    每条都有，不算实质信息——否则打码/无抵押条目会因摘要通过门槛回流（同步实测发现）。
    2026-09-05 二次修正：raw_text 须为有效原文（非占位一句话、≥15字），
    "详见竞买公告。"等占位不再算实质——京东个人债权常见此形态（原文抓不到=放弃）。"""
    return (_has(d.get("collateral_desc")) or _has(d.get("collateral_type"))
            or _has(d.get("region")) or _has(d.get("interest"))
            or _raw_ok(d.get("raw_text")) or _has(d.get("announce_table")))


def _substance_body(d: dict) -> bool:
    """捡漏版块专用：必须有"正文级"内容（有效原文/公告表格/抵押描述/利息），
    仅地区/起拍价等列表字段不算——2026-09-05 用户拍板"没内容的删除"（528/530 类
    详情页只有地区+价格、无正文的破产条目不再入库）。raw_text 占位不算。"""
    return (_raw_ok(d.get("raw_text")) or _has(d.get("announce_table"))
            or _has(d.get("collateral_desc")) or _has(d.get("collateral_type"))
            or _has(d.get("interest")))


def completeness_missing(detail: dict, section: str = "featured", summary: str = "") -> list[str]:
    """返回缺失项列表；空列表=完整可入库。"""
    d = detail or {}
    miss: list[str] = []

    price = _price_of(d)
    if not _has(price) or any(x in str(price) for x in ("待定", "面议")):
        miss.append("起拍价")

    # 金额（债权或资产金额）
    if not (_has(d.get("claim_total")) or _has(d.get("current_price")) or _has(d.get("assessment_price"))):
        miss.append("金额")

    # 实质信息（方案 A：只有名+金额+起拍 而无描述的条目放弃；
    # 捡漏版块 2026-09-05 更严：必须正文级内容——原文/公告表格/抵押描述/利息，仅地区不算）
    if section == "bargain":
        if not _substance_body(d):
            miss.append("实质信息(原文/表格/抵押/利息)")
    elif not _substance_of(d, summary):
        miss.append("实质信息(抵押/地区/利息/原文)")

    return miss


def is_complete(item: dict, section: str = "featured") -> bool:
    """整条（item 含 title/detail/summary）是否完整可入库"""
    it = item or {}
    detail = it.get("detail") or {}
    return not completeness_missing(detail, section, str(it.get("summary") or ""))
