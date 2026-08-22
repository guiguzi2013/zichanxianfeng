"""深度调查报告生成器：把深度调查原始数据组织为"资产维度 + 变现难度 + 变现路径 + 线下查询指引"

深度调查定位：财产线索（轻量）跑完不满意时，用户付费触发的进阶调查。
与 case_analyzer 的区别：本模块聚焦"资产本身 + 怎么变现"，而非"该不该追"。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 变现难度分级（越低越好变现）
DIFF_LOW = "低"
DIFF_MID = "中"
DIFF_HIGH = "中高"
DIFF_VERY_HIGH = "高"
DIFF_EXTREME = "极高"

# 各资产维度的变现难度 + 变现路径（核心知识库）
ASSET_PATH_GUIDE: dict[str, dict[str, str]] = {
    "对外投资股权": {
        "难度": DIFF_MID,
        "路径": "冻结被执行人在目标公司的股权 → 法院评估股权价值 → 司法拍卖/变卖；"
                "若目标公司为存续且有分红，也可申请执行股息红利。",
    },
    "动产抵押资产": {
        "难度": DIFF_HIGH,
        "路径": "核实抵押登记信息 → 查封该动产 → 评估 → 拍卖/变卖；"
                "注意抵押权人优先受偿，追偿时可能只能分配剩余价值。",
    },
    "土地抵押资产": {
        "难度": DIFF_MID,
        "路径": "向不动产登记部门核实土地权属及抵押情况 → 申请查封 → 评估 → 司法拍卖；"
                "土地变现价值较高但周期长（3-12 个月），需关注抵押优先权。",
    },
    "司法拍卖/处置资产": {
        "难度": DIFF_MID,
        "路径": "该企业已有资产进入司法拍卖/处置程序 → 申请参与分配或轮候查封；"
                "及时向执行法院递交参与分配申请，否则可能错过受偿机会。",
    },
    "询价评估资产": {
        "难度": DIFF_MID,
        "路径": "存在询价/评估记录说明法院已启动处置 → 主动联系执行法院确认资产清单与评估价；"
                "可据此预估可回收金额。",
    },
    "对外应收债权": {
        "难度": DIFF_VERY_HIGH,
        "路径": "债务人（被执行人）对第三人享有的债权 → 申请法院发出履行到期债务通知（执行第三人到期债权）；"
                "或提起代位权诉讼。需要债权凭证（合同/判决/对账单），第三人异议则需另诉。",
    },
    "股东权益/分红": {
        "难度": DIFF_MID,
        "路径": "若本企业为某公司股东：冻结股权份额 → 拍卖或执行分红；"
                "若为企业股东欠款（本企业是股东），可冻结其在本企业的分红。",
    },
    "知识产权": {
        "难度": DIFF_VERY_HIGH,
        "路径": "向国家知识产权局/版权中心核实专利、商标、著作权登记 → 申请查封 → 评估 → 拍卖/许可收费；"
                "知识产权评估难、流拍率高，常需以'打包+许可费分成'方式变现。",
    },
    "银行存款/网络资金": {
        "难度": DIFF_LOW,
        "路径": "最快变现路径：申请法院网络查控（总对总查控系统）→ 冻结 → 划扣；"
                "需在立案执行后立即申请，防止转移。",
    },
    "不动产（房产）": {
        "难度": DIFF_MID,
        "路径": "向不动产登记中心查询权属 → 申请查封 → 评估 → 司法拍卖；"
                "住宅拍卖周期约 6-12 个月，商业/工业地产更难变现。",
    },
    "车辆/设备/货物": {
        "难度": DIFF_HIGH,
        "路径": "查车管所登记/实地走访 → 扣押 → 评估 → 拍卖/变卖；"
                "贬值快、保管成本高，需尽快处置；货物需确认权属与保管人。",
    },
    "林权/矿权/租赁权": {
        "难度": DIFF_EXTREME,
        "路径": "向自然资源/林业部门核实权属登记 → 查封登记 → 评估 → 拍卖；"
                "涉及行政审批、评估机构少、处置周期极长（1 年以上），且需专业评估机构。",
    },
}

# 线下查询指引（公开企业数据查不到、必须线下核实的资产类型）
OFFLINE_QUERY_GUIDE: list[dict[str, str]] = [
    {
        "类型": "银行存款/网络资金",
        "渠道": "法院网络查控系统（总对总）",
        "说明": "个人/企业账户只能由法院依职权查询；债权人在执行立案时申请即可，无需自己跑银行。",
    },
    {
        "类型": "房产/车辆/船舶",
        "渠道": "不动产登记中心、车管所、海事局",
        "说明": "需凭法院调查令或由法院依职权查询；债权人可提供已知线索（地址/车牌）协助定位。",
    },
    {
        "类型": "知识产权（专利/商标/著作权）",
        "渠道": "国家知识产权局专利检索系统、中国商标网、版权登记系统",
        "说明": "均免费公开可查：专利 cnipa 检索、商标 sbj.cnipa.gov.cn、著作权 版权中心。按企业名称/法人名称检索即可。",
    },
    {
        "类型": "林权",
        "渠道": "县级自然资源局（林业）林权登记档案",
        "说明": "林权证登记在不动产登记系统；需提供具体县区，凭调查令或律师持令查询。",
    },
    {
        "类型": "矿权",
        "渠道": "自然资源部全国矿业权登记信息公示系统",
        "说明": "矿业权（探矿权/采矿权）在国家自然资源部系统公开可查，按企业名称检索。",
    },
    {
        "类型": "租赁权/经营权",
        "渠道": "不动产登记（租赁备案）、特许经营合同",
        "说明": "租赁权一般无公开登记，需现场走访或从财务资料中发现；经营性租赁可执行租金收益。",
    },
    {
        "类型": "对外债权/应收款",
        "渠道": "企业财务报表、合同台账、裁判文书",
        "说明": "公开数据只能提示线索（如本企业作为原告的胜诉判决），具体应收款金额需凭财务资料或执行到期债权程序查明。",
    },
]


def _first_array(obj: Any) -> list | None:
    """递归找第一个非空数组"""
    if isinstance(obj, list):
        return obj if obj else None
    if isinstance(obj, dict):
        for v in obj.values():
            r = _first_array(v)
            if r:
                return r
    return None


def _reg_name(deep: dict) -> str:
    return (deep.get("base", {}).get("biz", {}).get("get_company_registration_info")
            or {}).get("data", {}).get("企业名称") or deep.get("company", "")


def _active_investments(deep: dict) -> list[dict]:
    """对外投资中存续/在业的（可执行股权目标）"""
    data = deep.get("base", {}).get("biz", {}).get("get_external_investments") or {}
    arr = _first_array(data.get("data"))
    out = []
    for item in arr or []:
        st = str(item.get("状态") or "")
        if "存续" in st or "在业" in st or "开业" in st:
            out.append(item)
    return out


def _party_names(item: dict) -> tuple[list[str], list[str]]:
    """从文书/开庭数据中取原告、被告名单。

    企查查实际结构：当事人: {"原告": [...], "被告": [...]}（对象形式）。
    兼容旧式字符串标题："XX诉YY" 形态做兜底。
    """
    parties = item.get("当事人")
    plaintiffs: list[str] = []
    defendants: list[str] = []
    if isinstance(parties, dict):
        for p in parties.get("原告") or []:
            plaintiffs.append(str(p))
        for d in parties.get("被告") or []:
            defendants.append(str(d))
    if not plaintiffs and not defendants:
        title = str(item.get("案件名称") or item.get("标题") or item.get("文书标题") or "")
        if "诉" in title:
            before, after = title.split("诉", 1)
            if "原告" in before:
                before = before.split("原告", 1)[-1]
            plaintiffs = [before.strip("（()） 　")]
            if "被告" in after:
                after = after.split("被告", 1)[-1]
            defendants = [after.strip("（()） 　")]
    return plaintiffs, defendants


def _plaintiff_judgments(deep: dict) -> list[dict]:
    """裁判文书中本企业作为原告/申请人的案件（对外债权/应收款线索）"""
    data = deep.get("risk_details", {}).get("get_judicial_documents") or {}
    arr = _first_array(data.get("data"))
    name = deep.get("company", "")
    out = []
    for item in arr or []:
        plaintiffs, _ = _party_names(item)
        if any(name and (name in p or p in name) for p in plaintiffs):
            out.append(item)
    return out[:20]


def _defendant_judgments(deep: dict) -> list[dict]:
    """裁判文书中本企业作为被告的案件（债务压力信号，辅助判断追索难度）"""
    data = deep.get("risk_details", {}).get("get_judicial_documents") or {}
    arr = _first_array(data.get("data"))
    name = deep.get("company", "")
    out = []
    for item in arr or []:
        _, defendants = _party_names(item)
        if any(name and (name in d or d in name) for d in defendants):
            out.append(item)
    return out[:20]


def _pending_claims(deep: dict) -> list[dict]:
    """立案/开庭中本企业作为原告的（未来可能的胜诉收入）"""
    name = deep.get("company", "")
    out = []
    for tool in ("get_case_filing_info", "get_hearing_notice"):
        data = deep.get("risk_details", {}).get(tool) or {}
        arr = _first_array(data.get("data"))
        for item in arr or []:
            plaintiffs, _ = _party_names(item)
            if any(name and (name in p or p in name) for p in plaintiffs):
                out.append(item)
    return out[:20]


def _dict_items(data: dict) -> list[dict]:
    arr = _first_array(data.get("data"))
    return arr or []


def build_deep_report(deep: dict, calls_used: int) -> dict:
    """把深度调查原始数据组织为结构化报告"""
    company = _reg_name(deep)
    base_biz = deep.get("base", {}).get("biz", {})
    scan = deep.get("base", {}).get("risk", {}).get("scan") or {}
    details = deep.get("risk_details", {})

    dimensions: list[dict] = []

    # ---- 1. 对外投资股权（可执行股权目标）----
    inv = _active_investments(deep)
    if inv:
        guide = ASSET_PATH_GUIDE["对外投资股权"]
        dimensions.append({
            "name": "对外投资股权（存续/在业子公司）",
            "difficulty": guide["难度"],
            "path": guide["路径"],
            "summary": f"持有 {len(inv)} 家存续/在业企业的股权，可冻结并拍卖变现",
            "items": inv[:15],
        })

    # ---- 2. 实物资产：动产抵押 / 土地抵押 / 司法拍卖 ----
    for tool, key, label in (
        ("get_chattel_mortgage_info", "动产抵押资产", "动产抵押"),
        ("get_land_mortgage_info", "土地抵押资产", "土地抵押"),
        ("get_judicial_auction", "司法拍卖/处置资产", "司法拍卖/处置"),
    ):
        data = base_biz.get(tool) or {}
        items = _dict_items(data)
        if items:
            guide = ASSET_PATH_GUIDE[key]
            dimensions.append({
                "name": label,
                "difficulty": guide["难度"],
                "path": guide["路径"],
                "summary": f"发现 {len(items)} 条{label}记录",
                "items": items[:15],
            })

    # ---- 3. 询价评估 / 财产悬赏（资产处置进行时信号）----
    for tool, key, label in (
        ("get_valuation_inquiry", "询价评估资产", "询价/评估"),
        ("get_property_asset_announcement", "对外应收债权", "财产悬赏公告"),
    ):
        data = details.get(tool) or {}
        items = _dict_items(data)
        if items:
            guide = ASSET_PATH_GUIDE[key]
            dimensions.append({
                "name": label,
                "difficulty": guide["难度"],
                "path": guide["路径"],
                "summary": f"{label}有 {len(items)} 条记录，说明资产处置/查找正在进行",
                "items": items[:15],
            })

    # ---- 4. 对外应收债权（债务人作为原告 → 未来收入）----
    pl = _plaintiff_judgments(deep)
    pc = _pending_claims(deep)
    if pl or pc:
        guide = ASSET_PATH_GUIDE["对外应收债权"]
        dimensions.append({
            "name": "对外应收债权/未来收入（本企业作为原告）",
            "difficulty": guide["难度"],
            "path": guide["路径"],
            "summary": (
                f"疑似作为原告/申请人的案件 {len(pl)} 条（裁判文书），"
                f"涉诉(立案/开庭) {len(pc)} 条——这些案件胜诉后形成对外债权，可申请执行到期债权"
            ),
            "items": (pl + pc)[:20],
        })

    # ---- 5. 司法风险因子明细（被执行/失信/终本等，提示追索难度）----
    risk_items = []
    for tool, label in (
        ("get_equity_freeze", "股权冻结"),
        ("get_equity_pledge_info", "股权出质"),
        ("get_stock_pledge_info", "股权质押"),
        ("get_guarantee_info", "担保信息"),
        ("get_terminated_cases", "终本案件"),
    ):
        data = details.get(tool) or {}
        items = _dict_items(data)
        if items:
            risk_items.append({"label": label, "count": len(items)})
    if risk_items:
        dimensions.append({
            "name": "司法风险因子明细",
            "difficulty": DIFF_VERY_HIGH,
            "path": "存在股权冻结/出质/担保/终本记录：说明资产可能已被查封或有优先权负担，"
                    "追偿时需向执行法院确认查封顺位与优先受偿情况，必要时申请参与分配。",
            "summary": "；".join(f"{i['label']} {i['count']} 条" for i in risk_items),
            "items": risk_items,
        })

    # ---- 6. 经营状况（年报/财务/发票：判断"活企业"还是"空壳"）----
    biz_items = []
    for tool, label in (
        ("get_annual_reports", "企业年报"),
        ("get_financial_data", "财务数据"),
        ("get_tax_invoice_info", "发票信息"),
    ):
        data = deep.get("extra_biz", {}).get(tool) or {}
        if data.get("ok") and _first_array(data.get("data")):
            biz_items.append(label)
    if biz_items:
        dimensions.append({
            "name": "经营活跃度（年报/财务/发票）",
            "difficulty": DIFF_LOW,
            "path": "有经营记录说明企业仍在运转，可能有现金流或可变现资产；"
                    "若同时无抵押/无涉诉，则需优先查银行存款与应收款（见线下指引）。",
            "summary": f"存在 {'、'.join(biz_items)} 等经营记录，企业疑似仍在经营",
            "items": [{"维度": b} for b in biz_items],
        })

    # ---- 汇总 ----
    found = [d for d in dimensions if d["name"] not in ("司法风险因子明细",)]
    if not found:
        summary = "公开数据未发现明确可执行资产，建议按线下查询指引逐项核实（重点：法院查控、不动产、知识产权）。"
    else:
        best = sorted(found, key=lambda d: {"低": 0, "中": 1, "中高": 2, "高": 3, "极高": 4}[d["difficulty"]])
        summary = (
            f"发现 {len(found)} 类资产线索。最易变现的是「{best[0]['name']}」（难度：{best[0]['difficulty']}）；"
            f"对外应收债权等虽难变现，但若债务人作为原告的案件胜诉，可形成未来收入，值得跟进。"
        )

    return {
        "company": company,
        "summary": summary,
        "dimensions": dimensions,
        "offline_guides": OFFLINE_QUERY_GUIDE,
        "scan_summary": scan.get("data", {}).get("摘要", "") if scan.get("ok") else "",
        "calls_used": calls_used,
        "reminders": build_risk_reminders(deep),
    }


def build_risk_reminders(deep: dict) -> list[dict]:
    """根据尽调数据特征匹配知识库案例场景，生成风险提醒（供报告附注使用）。

    场景匹配基于关键词（抵押物/房产占用、终本、拒执、一人公司、应收债权等），
    命中即返回对应案例的提醒摘要与处理思路。
    """
    from ..api.knowledge import _match_keywords
    from ..database import SessionLocal
    from ..models import KnowledgeCase

    features = _feature_text(deep)
    if not features:
        return []

    db = SessionLocal()
    try:
        cases = db.query(KnowledgeCase).all()
        hits = []
        for c in cases:
            kw = f"{c.keywords or ''},{c.tags or ''},{c.scenario or ''}"
            if _match_keywords(features, kw):
                hits.append({
                    "scenario": c.scenario,
                    "title": c.title,
                    "summary": c.summary or "",
                    "approach": c.approach or "",
                    "result": c.result or "",
                })
        return hits
    except Exception:
        # 知识库表不存在（测试/未建表环境）时静默降级，不影响报告主体
        logger.debug("knowledge reminders unavailable", exc_info=True)
        return []
    finally:
        db.close()


def _feature_text(deep: dict) -> str:
    """把尽调数据转成用于场景匹配的特征文本"""
    parts = []
    base_biz = deep.get("base", {}).get("biz", {})
    scan = deep.get("base", {}).get("risk", {}).get("scan") or {}
    details = deep.get("risk_details", {})
    extra = deep.get("extra_biz", {})

    # 司法风险
    if scan.get("ok") and isinstance(scan.get("data"), dict):
        for f in scan["data"].get("风险因子扫描") or []:
            if (f.get("条目数") or 0) > 0:
                parts.append(f["风险因子"])
    # 抵押/拍卖/评估
    for tool, label in (
        ("get_chattel_mortgage_info", "动产抵押"),
        ("get_land_mortgage_info", "土地抵押"),
        ("get_judicial_auction", "司法拍卖"),
    ):
        if (base_biz.get(tool) or {}).get("ok"):
            parts.append(label)
    # 司法因子明细
    for tool in ("get_terminated_cases", "get_equity_freeze", "get_equity_pledge_info", "get_guarantee_info"):
        if (details.get(tool) or {}).get("ok"):
            parts.append({"get_terminated_cases": "终本", "get_equity_freeze": "股权冻结",
                          "get_equity_pledge_info": "股权出质", "get_guarantee_info": "担保"}[tool])
    # 应收债权
    if (details.get("get_judicial_documents") or {}).get("ok") or (details.get("get_case_filing_info") or {}).get("ok"):
        parts.append("应收债权")
    # 对外投资（一人公司提示：100% 持股子公司）
    inv = deep.get("base", {}).get("biz", {}).get("get_external_investments") or {}
    if inv.get("ok"):
        arr = _first_array(inv.get("data"))
        if any("100%" in str(it.get("持股比例") or "") for it in arr or []):
            parts.append("一人公司")
    # 股权结构（股东信息：唯一股东→一人公司）
    shr = deep.get("base", {}).get("biz", {}).get("get_shareholder_info") or {}
    if shr.get("ok"):
        arr = _first_array(shr.get("data"))
        if arr and len(arr) == 1:
            parts.append("一人公司")
    # 年报/经营
    for tool in ("get_annual_reports", "get_financial_data", "get_tax_invoice_info"):
        if (extra.get(tool) or {}).get("ok"):
            parts.append("经营")
    return " ".join(parts)
