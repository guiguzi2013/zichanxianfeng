# -*- coding: utf-8 -*-
"""财产线索单企业报告 → sections（2026-09-06 重构：查询结果 + 追索分析 融合成报告）

输入：query_property_clues 返回的 result（biz 各工具结果 + risk.scan 命中清单 + risk.details 明细）
输出：sections 通用结构 [{h, kvs, tables, note}]，供 网页报告页 + PDF 共用渲染
     （与债务人画像 sections 同构，前端报告页/PDF 排版可复用同一套渲染）

报告章节：
  一、企业概况（工商登记）
  二、股权与对外投资（股东/对外投资/分支）
  三、财产线索（动产抵押/土地抵押/司法拍卖/询价评估）
  四、无形资产（2026-09-06 新增：专利/国际专利/商标/商标文书/网络服务备案/特许经营/知产出质
      7 类核验总览 + 有记录维度明细章与变现/执行提示——无形资产同属财产, 可评估执行）
  五、司法与风险（scan 命中清单 + 明细示例）
  六、权利主张案件（2026-09-06 新增：该企业以 原告/上诉人/申请执行人 等权利方身份参与的
      涉诉记录 = 潜在未来债权——胜诉可能执行回款, 建议跟踪并事先保全/查封）
  七、追索分析与建议（规则引擎，服务债权人追缴）
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 财产线索工具展示名（与前端 CLUE_TOOLS 对齐）
_CLUE_LABELS = {
    "get_external_investments": "对外投资",
    "get_shareholder_info": "股东信息",
    "get_branches": "分支机构",
    "get_chattel_mortgage_info": "动产抵押",
    "get_land_mortgage_info": "土地抵押",
    "get_judicial_auction": "司法拍卖",
    "get_valuation_inquiry": "询价评估",
}
# 详情钻取名册（只展示有记录且已钻取的）
_DETAIL_LABELS = {
    "get_judicial_documents": "裁判文书",
    "get_case_filing_info": "立案信息",
    "get_hearing_notice": "开庭公告",
    "get_court_notice": "法院公告",
    "get_service_notice": "送达公告",
    "get_public_exhortation": "公示催告",
    "get_service_announcement": "劳动仲裁",
    "get_default_info": "违约事项",
    "get_disciplinary_list": "惩戒名单",
    "get_liquidation_info": "清算信息",
    "get_exit_restriction": "限制出境",
    "get_tax_abnormal": "税务非正常户",
    "get_tax_arrears_notice": "欠税公告",
    "get_stock_pledge_info": "股权质押",
    "get_guarantee_info": "对外担保",
    "get_property_asset_announcement": "财产悬赏公告",
    "get_bankruptcy_reorganization": "破产重整",
    "get_judgment_debtor_info": "被执行人",
    "get_dishonest_info": "失信信息",
    "get_high_consumption_restriction": "限制高消费",
    "get_terminated_cases": "终本案件",
    "get_equity_freeze": "股权冻结",
    "get_chattel_mortgage_info": "动产抵押",
    "get_land_mortgage_info": "土地抵押",
    "get_judicial_auction": "司法拍卖",
}
_HIGH_RISK = ("被执行人", "失信信息", "限制高消费", "终本案件", "股权冻结", "股权出质")


def _data(res: dict) -> object:
    if not (res or {}).get("ok"):
        return None
    return res.get("data")


def _first_list(d) -> list | None:
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list) and v:
                return v
    return None


def _fmt(v, n: int = 400) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        import json
        return json.dumps(v, ensure_ascii=False)[:n]
    return str(v)[:n]


def _strip(v) -> str:
    return str(v or "").strip()


# 明细列：跳过 内部id/加密串/超长URL 类字段（2026-09-06 裁判文书 did1.xxx 乱码修复）
_SKIP_KEY_RE = re.compile(r"文书ID|^id$|did|docId|url|link|href|^content$|全文|内容|uuid|^key$|token|sign|_id", re.I)
_SKIP_VAL_RE = re.compile(r"^did1?[.\w-]{20,}|^https?://|^[\w-]{40,}$")

# 各司法工具明细的推荐列序（按可读性排；不在表内的列自动附加）
_DETAIL_COL_ORDER = {
    "get_judicial_documents": ["案号", "案由", "文书标题", "裁判日期", "案件金额", "当事人"],
    "get_case_filing_info": ["案号", "案由", "当事人", "法院", "立案日期"],
    "get_court_notice": ["案号", "案由", "当事人", "公告类型", "公告人", "刊登日期"],
    "get_service_notice": ["案号", "案由", "当事人", "法院", "刊登日期"],
    "get_hearing_notice": ["案号", "案由", "当事人", "法院", "开庭日期"],
    "get_equity_freeze": ["案号", "被执行人", "冻结股权企业", "冻结金额", "冻结机关", "冻结日期"],
    "get_judgment_debtor_info": ["案号", "执行标的", "执行法院", "立案日期"],
    "get_dishonest_info": ["案号", "执行标的", "执行法院", "立案日期"],
    "get_high_consumption_restriction": ["案号", "被执行人", "执行法院", "立案日期"],
    "get_terminated_cases": ["案号", "执行标的", "执行法院", "终本日期"],
}


def _is_skip_key(k: str) -> bool:
    kk = str(k or "").strip()
    if not kk:
        return True
    return bool(_SKIP_KEY_RE.search(kk))


def _is_skip_val(v) -> bool:
    s = str(v or "").strip()
    return bool(s and _SKIP_VAL_RE.match(s))


def _col_order_for(tool: str, keys: list) -> list:
    """按工具推荐列序排列 keys；未命中列附加在后；最多取前 5 列防挤压"""
    pref = _DETAIL_COL_ORDER.get(tool) or []
    ordered = [k for k in pref if k in keys]
    rest = [k for k in keys if k not in ordered]
    return (ordered + rest)[:5]


def _flatten_json(v) -> str:
    """{原告:[X],被告:[Y]} / [A,B] → 可读文本（拍平嵌套，避免整段 JSON 占列）"""
    if isinstance(v, list):
        parts = [_flatten_json(x) for x in v]
        return "；".join(p for p in parts if p)
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            p = _flatten_json(val)
            if p:
                parts.append(f"{k}:{p}")
        return "；".join(parts)
    s = str(v or "").strip()
    if _is_skip_val(s):
        return ""
    return s


def _short_key(k: str, n: int = 14) -> str:
    s = str(k or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------- 无形资产章节(2026-09-06 用户拍板: 财产线索报告查 7 类无形资产) ----------
# 查询工具顺序 = qcc.py CLUES_IPR_TOOLS 一致: 专利/国际专利/商标/商标文书/网络服务备案/特许经营/知产出质
_IPR_ORDER = [
    "get_patent_info", "get_international_patent", "get_trademark_info",
    "get_trademark_document", "get_internet_service_info", "get_commercial_franchise",
    "get_ipr_pledge",
]
_IPR_LABELS = {
    "get_patent_info": "专利",
    "get_international_patent": "国际专利",
    "get_trademark_info": "商标",
    "get_trademark_document": "商标文书",
    "get_internet_service_info": "网络服务备案",
    "get_commercial_franchise": "特许经营",
    "get_ipr_pledge": "知产出质",
}
# 有记录明细表推荐列序(字段名随接口; 未命中列自动附加)
_IPR_COL_ORDER = {
    "get_patent_info": ["发明名称", "专利类型", "法律状态", "申请号", "申请日期"],
    "get_international_patent": ["发明名称", "法律状态", "申请号", "申请日期", "发明人"],
    "get_trademark_info": ["商标名称", "国际分类", "商标状态", "申请/注册号", "注册公告日期"],
    "get_trademark_document": ["文书类型", "商标文书号", "申请人", "被申请人", "公布日期"],
    "get_commercial_franchise": [],  # 结构未知 → 通用列
    "get_ipr_pledge": [],            # 结构未知 → 通用列
}
# 各维度变现/执行提示(面向从业者; 语言为产品文案非施工汇报)
_IPR_HINTS = {
    "get_patent_info":
        "专利属无形资产, 经评估可依法申请司法拍卖变现。其中发明专利价值最高(市场普遍数万元起, "
        "若技术可落地转化则价值难以估量); 实用新型与外观专利价值通常数千元(可转化成果者价值更高)。"
        "建议委托评估机构出具价值评估后, 向法院申请查封、拍卖处置。",
    "get_international_patent":
        "国际专利(欧盟、美国、日本等多国布局)单件价值通常数万至数十万元, 属高价值可执行无形资产, "
        "建议评估后申请执行。",
    "get_trademark_info":
        "注册商标承载品牌价值, 属可执行无形资产, 可向法院申请评估、查封并拍卖/转让执行; "
        "执行时注意核验商标当前法律状态与是否有近似争议。",
    "get_trademark_document":
        "该企业存在商标异议/评审等争议文书, 相关商标权利处于争议状态、存在失效风险——"
        "一旦商标被宣告无效或撤销失效, 即不能再作为该企业的无形资产评估变现。"
        "建议重点关注争议进展(异议/评审/诉讼结果), 处置执行前务必先核验相关商标的法律状态。",
    "get_internet_service_info":
        "备案网站对应的域名属知识产权(无形资产), 可申请评估执行; 同时建议登录备案网站核验企业经营现状, "
        "或可发现线上业务、收款渠道等新的财产线索。APP/小程序/算法备案本身执行难度大, 但可佐证经营活跃度。",
    "get_commercial_franchise":
        "商业特许经营权属无形资产, 可依法执行; 特许经营通常伴随持续加盟/授权收入, "
        "建议调查其特许经营收益是否存在隐瞒(加盟费、管理费流向), 该方向存在追偿空间。",
    "get_ipr_pledge":
        "该企业专利/商标已被用于质押融资——一方面说明其知产具备价值, 另一方面资产已被质权人锁定: "
        "执行前需先处理质押负担(清偿质权后处置或带押处置), 同时质权人信息本身可作追索线索。",
}


def _ipr_total(data) -> int:
    """从 摘要 '共有N条/仅有N条/累计共有N条' 提取总数; 无法解析返回 0"""
    if not isinstance(data, dict):
        return 0
    s = str(data.get("摘要") or "")
    m = re.search(r"(?:共有|仅有|累计共有)\s*(\d+)\s*条", s)
    if m:
        return int(m.group(1))
    # 网络服务备案子类合计 (网站7+APP5+...)
    subs = data.get("网络服务备案信息")
    if isinstance(subs, dict):
        return sum(len(v) for v in subs.values() if isinstance(v, list))
    return 0


def _ipr_has_records(data) -> bool:
    """判断该维度是否有记录: 返回 '未发现任何记录' 的 搜索结果 键 → 无;
    否则有(摘要+清单)。特判: 查询失败 ok=false 由调用方先行过滤。"""
    if not isinstance(data, dict):
        return False
    sr = data.get("搜索结果")
    if isinstance(sr, str) and "未发现" in sr:
        return False
    if "摘要" in data or "网络服务备案信息" in data:
        return True
    return False


def _ipr_records(data):
    """取该维度明细 list(网络服务备案为 4 子类 dict, 返回 None 由专用逻辑处理)"""
    if not isinstance(data, dict):
        return []
    subs = data.get("网络服务备案信息")
    if isinstance(subs, dict):
        return None
    for v in data.values():
        if isinstance(v, list) and v:
            return v
    return []


def _ipr_service_table(data: dict) -> dict:
    """网络服务备案: 网站/APP/小程序/算法 4 子类合并一张表(类别列区分, 避免同名表头混淆)"""
    subs = data.get("网络服务备案信息") or {}
    rows = []
    for cat, items in (
        ("备案网站", subs.get("备案网站") or []),
        ("APP备案", subs.get("APP备案") or []),
        ("小程序备案", subs.get("小程序备案") or []),
        ("算法备案", subs.get("算法备案") or []),
    ):
        for it in items[:50]:
            if not isinstance(it, dict):
                continue
            if cat == "备案网站":
                name = _strip(it.get("网站名称") or it.get("服务名称") or it.get("名称"))
                dom = _flatten_json(it.get("域名") or it.get("网址") or "")
                rows.append([cat, f"{name}({dom})" if dom else name, "",
                             _strip(it.get("ICP备案号") or it.get("服务备案号")),
                             _strip(it.get("ICP备案日期") or it.get("备案日期") or it.get("审核日期"))])
            elif cat == "算法备案":
                rows.append([cat,
                             _strip(it.get("算法/服务名称") or it.get("服务名称") or it.get("名称")),
                             _strip(it.get("算法/服务类型") or ""),
                             _strip(it.get("备案编号") or it.get("服务备案号")),
                             _strip(it.get("备案日期") or it.get("审核日期"))])
            else:
                rows.append([cat,
                             _strip(it.get("服务名称") or it.get("名称") or it.get("小程序名称")),
                             "",
                             _strip(it.get("服务备案号") or ""),
                             _strip(it.get("审核日期") or "")])
    return _table(["类别", "名称", "类型", "备案号/编号", "日期"], rows)


def _ipr_detail_table(tool: str, records: list, limit: int = 30) -> dict:
    """通用维度明细表: 推荐列序 + 语义化值(拍平 JSON/跳过内部键), 最多 limit 行"""
    pref = _IPR_COL_ORDER.get(tool) or []
    keys: list = []
    rows: list = []
    for it in records:
        if not isinstance(it, dict):
            continue
        if not keys:
            ks = [k for k in it.keys() if not _is_skip_key(k)]
            keys = [k for k in pref if k in ks] + [k for k in ks if k not in pref]
            keys = keys[:5]
        if not keys:
            break
        row = []
        for k in keys:
            v = it.get(k)
            if isinstance(v, (dict, list)):
                v = _flatten_json(v)
            s = _fmt(v, 200)
            if _is_skip_val(s):
                s = ""
            row.append(s)
        if any(row):
            rows.append(row)
        if len(rows) >= limit:
            break
    return _table([_short_key(k) for k in keys], rows)


def _build_ipr_sections(result: dict) -> list[dict]:
    """无形资产 章节组: 总览章(7 维度核验结果) + 有记录维度各一个明细章(含变现提示)。
    result.ipr = {tool: {label, price, ok, data, queried_at}}; 缺失/为空(查询未执行)则不建章。"""
    ipr = result.get("ipr") or {}
    if not ipr:
        return []
    secs: list[dict] = []
    overview_kvs: list = []
    detail_dims: list = []  # [(tool, total, records)]
    for tool in _IPR_ORDER:
        r = ipr.get(tool) or {}
        label = _IPR_LABELS.get(tool, tool)
        if not r.get("ok"):
            overview_kvs.append([label, "查询未成功（数据源未返回）"])
            continue
        data = r.get("data")
        if not _ipr_has_records(data):
            overview_kvs.append([label, "未发现记录"])
            continue
        total = _ipr_total(data) if isinstance(data, dict) else 0
        records = _ipr_records(data)
        shown = len(records) if isinstance(records, list) else None
        overview_kvs.append([label, f"{total if total > 0 else (shown or 0)} 条"])
        detail_dims.append((tool, label, data, records, total))
    sec = {"h": "无形资产", "kvs": _kv(overview_kvs), "tables": [], "note": None,
           "note_slot": "ipr_overview"}  # note_slot: 渲染端忽略; 供 LLM 律师式润色(advice_writer)
    if overview_kvs:
        sec["note"] = ("以上为对企业无形资产的核验结果。存在记录的维度详见下文各节及其处置提示; "
                       "未发现记录的维度说明暂未检索到对应无形资产(不排除线下存在未公示登记, "
                       "如著作权登记、商业秘密、未备案资产等, 需线下进一步核验)。")
    secs.append(sec)
    # 明细章
    for tool, label, data, records, total in detail_dims:
        h = f"无形资产 · {label}"
        note = _IPR_HINTS.get(tool, "")
        if tool == "get_internet_service_info":
            tb = _ipr_service_table(data)
            n_sub = sum(len(v) for v in (data.get("网络服务备案信息") or {}).values() if isinstance(v, list))
            secs.append({"h": h, "kvs": [], "tables": [tb] if tb.get("rows") else [],
                         "note": f"{note} 该企业共 {n_sub} 项备案。" if note else None,
                         "note_slot": f"ipr_{tool}"})
            continue
        tb = _ipr_detail_table(tool, records) if records else None
        if total > 0 and total > (len(tb.get("rows") or []) if tb else 0) and note:
            note = f"{note} 该企业共 {total} 条记录, 上表列示其中 {len(tb.get('rows') or [])} 条。"
        elif total > 0 and note:
            note = f"{note} 该企业共 {total} 条记录。"
        secs.append({"h": h, "kvs": [], "tables": [tb] if tb and tb.get("rows") else [],
                     "note": note, "note_slot": f"ipr_{tool}"})
    return secs


# ---------- 权利主张案件章节(2026-09-06 用户拍板: 该企业作为原告/权利方的涉诉 = 潜在未来债权) ----------
# 权利方角色(精确匹配, 防"被上诉人"含"上诉人"子串误判):
#   该企业以这些角色出现 → 若胜诉可能取得执行回款/受偿财产 = 未来可变现财产
_CLAIMANT_ROLES = ("原告", "上诉人", "申请人", "申请执行人", "再审申请人", "原审原告", "申诉人")
# 明确义务方(出现即不算权利方记录; 列表用于排除, 即便与权利方词有子串关系)
_DEFENDANT_ROLES = ("被告", "被上诉人", "被申请人", "被执行人", "原审被告", "第三人")
# 来源工具 → 展示名 与 状态判定
_CLAIM_SOURCES = {
    "get_judicial_documents": "裁判文书",
    "get_case_filing_info": "立案信息",
    "get_hearing_notice": "开庭公告",
    "get_court_notice": "法院公告",
    "get_service_notice": "送达公告",
    "get_service_announcement": "劳动仲裁",
}
# 各工具日期键(状态展示用)
_CLAIM_DATE_KEYS = {
    "get_judicial_documents": ("裁判日期", "发布日期"),
    "get_case_filing_info": ("立案日期",),
    "get_hearing_notice": ("开庭日期", "开庭时间"),
    "get_court_notice": ("刊登日期", "公告日期"),
    "get_service_notice": ("发布日期", "刊登日期"),
}


def _claim_role_of(parties: dict, company: str) -> str:
    """返回该企业在当事人中的权利方角色名; 无(义务方/未出现)返回 ''"""
    for role, names in parties.items():
        if not isinstance(names, list):
            names = [names]
        hit = any(str(n).strip() == company for n in names)
        if not hit:
            continue
        if role in _DEFENDANT_ROLES:
            return ""
        if role in _CLAIMANT_ROLES:
            return role
        # 未知角色(如 案外人/法定代表人/保证人): 不作为权利方入选
        return ""
    return ""


def _claim_status(tool: str, it: dict) -> str:
    """状态标签: 已判决/审理中/待开庭/已开庭/执行阶段/程序公告"""
    if tool == "get_judicial_documents":
        return "已判决" if _strip(it.get("裁判日期")) else "已判决"
    if tool == "get_case_filing_info":
        return "审理中"
    if tool == "get_hearing_notice":
        d = _strip(it.get("开庭日期") or it.get("开庭时间"))
        if d:
            try:
                from datetime import datetime
                today = datetime.now().date()
                dt = datetime.strptime(d[:10], "%Y-%m-%d").date()
                return "待开庭" if dt >= today else "已开庭"
            except Exception:
                return "开庭公告"
        return "开庭公告"
    if tool == "get_court_notice":
        bt = _strip(it.get("公告类型") or "")
        # 法院公告是历史程序节点(刊登日期), 不据此推断当前是否待开庭, 避免误导
        if "执行" in bt:
            return "执行阶段"
        return "程序公告"
    if tool in ("get_service_notice", "get_service_announcement"):
        return "程序公告"
    return "涉诉"


def _claim_rows_of(result: dict) -> tuple[list, dict]:
    """从 risk.details 筛出 该企业为权利方 的记录。
    返回 (rows, stats): rows=[{案号,身份,状态,法院,日期,来源}], stats={状态: 计数}"""
    company = result.get("search_name") or result.get("company") or ""
    details = (result.get("risk") or {}).get("details") or {}
    rows: list = []
    seen: set = set()
    # 来源优先级(同案号去重, 保留更完整来源)
    prio = ("get_judicial_documents", "get_case_filing_info", "get_hearing_notice", "get_court_notice", "get_service_notice")
    for tool in prio:
        dd = details.get(tool)
        if not dd or not dd.get("ok"):
            continue
        data = dd.get("data")
        lst = _first_list(data) if isinstance(data, dict) else []
        if not lst:
            continue
        for it in lst:
            if not isinstance(it, dict):
                continue
            parties = it.get("当事人")
            if not isinstance(parties, dict):
                continue
            role = _claim_role_of(parties, company)
            if not role:
                continue
            case_no = _strip(it.get("案号") or it.get("文书标题") or "")
            if case_no and case_no in seen:
                continue
            if case_no:
                seen.add(case_no)
            status = _claim_status(tool, it)
            date = ""
            for k in _CLAIM_DATE_KEYS.get(tool, ()):
                date = _strip(it.get(k))
                if date:
                    break
            court = _strip(it.get("法院") or it.get("执行法院") or it.get("公告人") or "")
            rows.append({"案号": case_no, "身份": role, "状态": status, "法院": court,
                         "日期": date, "来源": _CLAIM_SOURCES.get(tool, tool)})
    stats: dict = {}
    for r in rows:
        stats[r["状态"]] = stats.get(r["状态"], 0) + 1
    return rows, stats


def _build_claimant_sections(result: dict) -> list[dict]:
    """权利主张案件 章节(有记录才建): 该企业作为 原告/权利方 的涉诉清单 + 保全建议"""
    rows, stats = _claim_rows_of(result)
    if not rows:
        return []
    table_rows = [[r["案号"], r["身份"], r["状态"], r["法院"], r["日期"], r["来源"]] for r in rows[:40]]
    # 统计话术
    parts = []
    for label in ("已判决", "审理中", "待开庭", "已开庭", "执行阶段"):
        if stats.get(label):
            parts.append(f"{label} {stats[label]} 起")
    stat_txt = ("（" + "、".join(parts) + "）") if parts else ""
    note = (
        f"该企业以原告/权利方身份参与 {len(rows)} 起涉诉记录{stat_txt}。此类案件若胜诉, "
        "企业将取得执行回款或受偿财产, 属其未来可变现财产, 建议予以关注。具体建议: "
        "①持续跟踪案件进展与裁判结果; ②在判决生效、款项划转前, 及时申请财产保全或轮候查封, "
        "锁定该企业因胜诉可能取得的财产(执行款、受偿账户、第三方到期债权等); "
        "③将胜诉回款纳入受偿预期统筹评估, 与既有债权执行统筹安排。"
    )
    sec = {"h": "权利主张案件", "kvs": [], "tables": [],
           "note": note, "note_slot": "claimant"}
    if table_rows:
        sec["tables"].append(_table(["案号", "本企业身份", "案件状态", "法院/公告机关", "日期", "来源"], table_rows))
    return [sec]


# ---------- 追索分析（规则引擎；与前端 analyzeRecovery 对齐，服务 PDF） ----------

def analyze_recovery(data: dict) -> list[dict]:
    """把财产线索转成"可执行/可追索"动作建议：[{level: high/medium/info, text}]"""
    items: list[dict] = []
    biz = data.get("biz") or {}
    risk = data.get("risk") or {}
    scan = risk.get("scan") or {}
    factors = scan.get("data", {}).get("风险因子扫描") or [] if scan.get("ok") else []
    counts = {f.get("风险因子"): f.get("条目数") or 0 for f in factors}

    reg = biz.get("get_company_registration_info") or {}
    reg_d = reg.get("data") if reg.get("ok") else None
    if isinstance(reg_d, str):
        reg_d = None
    status = _strip((reg_d or {}).get("登记状态"))

    def nlist(key):
        r = biz.get(key)
        return _first_list(r.get("data")) if r and r.get("ok") else []

    inv = nlist("get_external_investments")
    shares = nlist("get_shareholder_info")
    chattel = nlist("get_chattel_mortgage_info")
    land = nlist("get_land_mortgage_info")
    auction = nlist("get_judicial_auction")

    if inv:
        items.append({"level": "high", "text": f"对外投资 {len(inv)} 条：可申请冻结并执行其对外投资股权，这是重要执行标的"})
    if shares:
        items.append({"level": "high", "text": f"股东信息 {len(shares)} 条：股权属可执行财产，可申请查封、冻结、评估处置"})
    if chattel:
        items.append({"level": "medium", "text": f"动产抵押 {len(chattel)} 条：核实抵押物现状与受偿顺位后再决定执行路径"})
    if land:
        items.append({"level": "medium", "text": f"土地抵押 {len(land)} 条：核实土地权属现状，可通过拍卖变价受偿"})
    if auction:
        items.append({"level": "medium", "text": f"司法拍卖 {len(auction)} 条：相关资产已进入处置程序，关注进展并申请参与分配"})
    if counts.get("被执行人"):
        items.append({"level": "high", "text": f"被执行 {counts['被执行人']} 条：可申请执行参与分配、查询履行情况，或追加/变更被执行人"})
    if counts.get("失信信息"):
        items.append({"level": "high", "text": f"失信 {counts['失信信息']} 条：已入信用惩戒名单，可申请限制高消费、联动布控"})
    if counts.get("限制高消费"):
        items.append({"level": "medium", "text": f"限高 {counts['限制高消费']} 条：已被限制消费，配合失信惩戒施压"})
    if counts.get("终本案件"):
        items.append({"level": "medium", "text": f"终本案件 {counts['终本案件']} 条：前期执行未果，需通过律师调查令/财产报告令补充银行、不动产、车辆等线索"})
    if counts.get("股权冻结"):
        items.append({"level": "medium", "text": f"股权冻结 {counts['股权冻结']} 条：他案已冻结，注意轮候查封并尽早申报债权"})
    if counts.get("股权出质"):
        items.append({"level": "medium", "text": f"股权出质 {counts['股权出质']} 条：股权已质押，核实质权顺位与实现条件"})
    if status and re.search(r"吊销|注销|清算", status):
        items.append({"level": "medium", "text": f"登记状态「{status}」：主体资格异常，追索重心转向保证人/关联方"})
    if not items:
        items.append({"level": "info", "text": "未发现明显可执行线索：建议申请律师调查令/法院财产报告令，查询银行账户、不动产、车辆、应收账款、到期债权等"})
    return items


# ---------- 汇总（报告头指标） ----------

def build_summary(result: dict) -> dict:
    biz = result.get("biz") or {}
    risk = result.get("risk") or {}
    reg = biz.get("get_company_registration_info") or {}
    reg_d = reg.get("data") if reg.get("ok") else None
    if isinstance(reg_d, str):
        reg_d = None
    reg_d = reg_d or {}
    scan = risk.get("scan") or {}
    factors = scan.get("data", {}).get("风险因子扫描") or [] if scan.get("ok") else []
    hits = [f for f in factors if (f.get("条目数") or 0) > 0]

    # 财产线索条数（对外投资/抵押/拍卖等）
    clue_total = 0
    for k in ("get_external_investments", "get_shareholder_info", "get_chattel_mortgage_info",
              "get_land_mortgage_info", "get_judicial_auction", "get_branches"):
        r = biz.get(k)
        lst = _first_list(r.get("data")) if r and r.get("ok") else []
        clue_total += len(lst or [])

    # 无形资产条数（2026-09-06：财产线索报告新增维度）
    ipr_total = 0
    for r in (result.get("ipr") or {}).values():
        if not r.get("ok"):
            continue
        data = r.get("data")
        if _ipr_has_records(data):
            t = _ipr_total(data) if isinstance(data, dict) else 0
            ipr_total += t if t > 0 else 0

    # 权利主张案件数（该企业为原告/权利方的涉诉记录 = 潜在未来债权）
    claim_rows, _ = _claim_rows_of(result)

    n_high = sum(1 for f in hits if f.get("风险因子") in ("被执行人", "失信信息"))
    return {
        "company": result.get("company") or result.get("search_name") or "",
        "search_name": result.get("search_name") or result.get("company") or "",
        "renamed": bool(result.get("renamed")),
        "legal_person": _strip((reg_d or {}).get("法定代表人")),
        "status": _strip((reg_d or {}).get("登记状态")),
        "established": _strip((reg_d or {}).get("成立日期")),
        "capital": _strip((reg_d or {}).get("注册资本")),
        "credit_code": _strip((reg_d or {}).get("统一社会信用代码")),
        "clue_total": clue_total,
        "ipr_total": ipr_total,
        "claim_count": len(claim_rows),
        "risk_total": sum(f.get("条目数") or 0 for f in hits),
        "risk_breakdown": [{"label": f.get("风险因子"), "count": f.get("条目数") or 0} for f in hits],
        "n_high_risk": n_high,
    }


# ---------- sections 构建 ----------

def _kv(kvs: list) -> list:
    return [[_fmt(k), _fmt(v)] for k, v in kvs if _strip(v)]


def _table(headers: list, rows: list) -> dict:
    return {"headers": headers, "rows": rows}


def build_sections(result: dict) -> list[dict]:
    """财产线索查询结果 → 报告 sections（通用渲染结构）"""
    biz = result.get("biz") or {}
    risk = result.get("risk") or {}
    secs: list[dict] = []

    # 一、企业概况
    reg = biz.get("get_company_registration_info") or {}
    reg_d = reg.get("data") if reg.get("ok") else None
    if isinstance(reg_d, str):
        reg_d = None
    reg_d = reg_d or {}
    sec1_kvs = [
        ("企业全称", reg_d.get("企业名称")),
        ("统一社会信用代码", reg_d.get("统一社会信用代码")),
        ("法定代表人", reg_d.get("法定代表人")),
        ("成立日期", reg_d.get("成立日期")),
        ("注册资本", reg_d.get("注册资本")),
        ("注册地址", reg_d.get("注册地址")),
        ("企业类型", reg_d.get("企业类型")),
        ("登记状态", reg_d.get("登记状态")),
        ("经营范围", reg_d.get("经营范围")),
    ]
    sec1 = {"h": "企业概况", "kvs": _kv(sec1_kvs), "tables": [], "note": None}
    secs.append(sec1)

    # 二、股权与对外投资
    sec2 = {"h": "股权与对外投资", "kvs": [], "tables": [], "note": None}
    shr = biz.get("get_shareholder_info") or {}
    shr_rows = []
    for s in (_first_list(shr.get("data")) if shr.get("ok") else []) or []:
        if isinstance(s, dict):
            shr_rows.append([_strip(s.get("股东名称") or s.get("股东")),
                             _fmt(s.get("持股比例") or s.get("出资比例")),
                             _fmt(s.get("认缴出资额") or s.get("认缴出资额(万元)")),
                             _strip(s.get("认缴出资日期"))])
    if shr_rows:
        sec2["tables"].append(_table(["股东名称", "持股比例", "认缴出资", "认缴日期"], shr_rows[:30]))
    inv = biz.get("get_external_investments") or {}
    inv_rows = []
    for it in (_first_list(inv.get("data")) if inv.get("ok") else []) or []:
        if isinstance(it, dict):
            inv_rows.append([_strip(it.get("被投资企业名称") or it.get("企业名称")),
                             _fmt(it.get("投资比例") or it.get("持股比例")),
                             _fmt(it.get("投资金额") or it.get("认缴出资额")),
                             _strip(it.get("登记状态") or it.get("状态"))])
    if inv_rows:
        sec2["tables"].append(_table(["对外投资企业", "投资比例", "投资金额", "状态"], inv_rows[:30]))
    br = biz.get("get_branches") or {}
    br_rows = []
    for b in (_first_list(br.get("data")) if br.get("ok") else []) or []:
        if isinstance(b, dict):
            br_rows.append([_strip(b.get("分支机构名称") or b.get("企业名称")),
                            _strip(b.get("负责人")),
                            _strip(b.get("登记状态") or b.get("状态"))])
    if br_rows:
        sec2["tables"].append(_table(["分支机构", "负责人", "状态"], br_rows[:30]))
    secs.append(sec2)

    # 三、财产线索（抵押/拍卖/询价评估）
    sec3 = {"h": "财产线索", "kvs": [], "tables": [], "note": None}
    for tool in ("get_chattel_mortgage_info", "get_land_mortgage_info",
                 "get_judicial_auction", "get_valuation_inquiry"):
        r = biz.get(tool)
        arr = (_first_list(r.get("data")) if r and r.get("ok") else []) or []
        if not arr:
            continue
        label = _CLUE_LABELS.get(tool, tool)
        # 统一取每条的 名称/金额/日期/状态 类字段，缺失列留空（字段名因接口而异，取前5个值）
        rows = []
        headers_used = []
        for it in arr[:20]:
            if isinstance(it, dict):
                keys = list(it.keys())
                if not headers_used:
                    headers_used = keys[:5]
                rows.append([_fmt(it.get(k)) for k in headers_used])
        if not rows:
            continue
        # 表头若单列且像标题，则加序号列
        if len(headers_used) == 1 and headers_used[0] == label:
            rows = [[str(i + 1), r2[0]] for i, r2 in enumerate(rows)]
            headers_used = ["序号", label]
        sec3["tables"].append(_table(headers_used, rows))
    if not sec3["tables"]:
        sec3["note"] = "未查询到 动产抵押/土地抵押/司法拍卖 等财产线索记录（可能无记录，需线下核验）"
    secs.append(sec3)

    # 四、无形资产（2026-09-06：专利/商标/备案/特许经营/知产出质等 7 类核验 + 变现提示）
    secs.extend(_build_ipr_sections(result))

    # 五、司法与风险
    sec4 = {"h": "司法与风险", "kvs": [], "tables": [], "note": None}
    scan = risk.get("scan") or {}
    factors = scan.get("data", {}).get("风险因子扫描") or [] if scan.get("ok") else []
    hits = [f for f in factors if (f.get("条目数") or 0) > 0]
    if not hits:
        sec4["note"] = "经全维度扫描，未发现失信/被执行/限高/终本/冻结/涉诉等风险记录。"
    else:
        risk_rows = [[f.get("风险因子"), str(f.get("条目数") or 0)] for f in hits]
        sec4["tables"].append(_table(["风险维度", "记录数"], risk_rows[:40]))
        # 明细示例（risk.details 已钻取的）
        details = risk.get("details") or {}
        for t, dd in details.items():
            if not dd.get("ok"):
                continue
            arr = _first_list(dd.get("data"))
            if not arr or not isinstance(arr[0], dict):
                continue
            label = _DETAIL_LABELS.get(t, t)
            keys = [k for k in arr[0].keys() if not _is_skip_key(k)]
            keys = _col_order_for(t, keys)
            if not keys:
                continue
            rows = []
            for it in arr[:10]:
                row = []
                skip_row = False
                for k in keys:
                    v = it.get(k)
                    if isinstance(v, (dict, list)):
                        v = _flatten_json(v)
                    s = _fmt(v, 200)
                    if _is_skip_val(s):
                        s = ""
                    if not s and k == keys[0]:
                        skip_row = True  # 首列(通常案号)为空 → 整行跳过
                    row.append(s)
                if not skip_row:
                    rows.append(row)
            if rows:
                sec4["tables"].append(_table([_short_key(k) for k in keys], rows))
    secs.append(sec4)

    # 五、权利主张案件（2026-09-06：该企业为原告/权利方的涉诉 = 潜在未来债权）
    secs.extend(_build_claimant_sections(result))

    # 六、追索分析与建议
    # note_slot=recovery_intro: AI 润色后填 AI 引言(表格分级保留); 无 AI 结果则 note=None 不显示
    sec5 = {"h": "追索分析与建议", "kvs": [], "tables": [], "note": None, "note_slot": "recovery_intro"}
    advice = analyze_recovery(result)
    rows = [[{"high": "优先处置", "medium": "需关注", "info": "建议动作"}.get(a.get("level"), ""), a.get("text")] for a in advice]
    if rows:
        sec5["tables"].append(_table(["处置优先级", "建议"], rows))
    secs.append(sec5)

    return secs
