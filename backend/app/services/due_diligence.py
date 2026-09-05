"""尽调引擎（对应设计文档第6章 + 《尽调引擎节点设计.md》）

执行顺序：②工商/司法 → ③法律（尽力）→ ④估值 → ⑤本息(纯代码) → 规则引擎 → ⑥LLM综合分析
P0 阶段：数据源为免费源，多数会降级为"需人工核实"，报告仍可生成（标注来源与缺失）。
"""
import json
import logging
from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..config import get_settings
from ..datasources.factory import get_enterprise_source, get_judicial_source
from ..models import Claim, Report, ReportVersion, Task, TaskItem
from .interest import calculate_interest
from .llm import LLMError, chat_json
from .reminder_engine import ReminderEngine
from .usage import record_usage

logger = logging.getLogger(__name__)
settings = get_settings()
reminder_engine = ReminderEngine()

# 节点顺序（进度显示用）
NODES = ["信息提取", "工商/司法查询", "法律检索", "抵押物估值", "本息计算", "综合分析"]


class NodeProgress:
    def __init__(self, task_id: int, db: Session, progress_cb: Callable[[int, str, int], None]) -> None:
        self.task_id = task_id
        self.db = db
        self.progress_cb = progress_cb

    async def step(self, node: str, percent: int) -> None:
        # progress_cb 为同步回调（FastAPI 后台任务线程池中执行），直接调用
        self.progress_cb(self.task_id, node, percent)


def _build_claim_dict(claim: Claim) -> dict:
    extra = {}
    try:
        extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
    except Exception:
        extra = {}
    # 重要文件下载链接（2026-09-01：详情页一键尽调带入 source_raw，如 /api/feed/366/attachments/0）
    attachment_links: list[str] = []
    if claim.source_raw:
        import re as _re2
        for m in _re2.finditer(r'/api/feed/(\d+)/attachments/(\d+)', claim.source_raw):
            url = m.group(0)
            if url not in attachment_links:
                attachment_links.append(url)
    return {
        "debtor_name": claim.debtor_name,
        "debtor_type": claim.debtor_type or "enterprise",
        "principal_cents": claim.principal_cents,
        "interest_cents": claim.interest_cents,
        "fees_cents": claim.fees_cents,
        "guaranty_type": claim.guaranty_type,
        "guarantor": claim.guarantor,
        "collateral": claim.collateral,
        "collateral_type": extra.get("collateral_type"),
        "mortgagor": extra.get("mortgagor"),
        "region": extra.get("region"),
        "judicial_status": claim.judicial_status,
        "listing_price_cents": claim.listing_price_cents,
        "interest_base_date": extra.get("interest_base_date"),
        "batch": extra.get("batch"),
        "loan_bank": extra.get("loan_bank"),
        # 2026-09-04 材料识别新增字段（回填展示：债权人/债权类型/计息方式/是否胜诉）
        "creditor": extra.get("creditor"),
        "debt_type": extra.get("debt_type"),
        "interest_method": extra.get("interest_method"),
        "judgment_result": extra.get("judgment_result"),
        "lease_equipment": extra.get("lease_equipment") == "1",
        "mortgage_amount": extra.get("mortgage_amount"),
        "mortgage_rank": extra.get("mortgage_rank"),
        "seizure": extra.get("seizure"),
        "collateral_status": extra.get("collateral_status"),
        "case_number": extra.get("case_number"),
        "case_cause": extra.get("case_cause"),
        # 房产证/抵押物明细（2026-09-02：证上有的字段全部提取并在报告展示）
        "land_area_sqm": extra.get("land_area_sqm"),
        "building_area_sqm": extra.get("building_area_sqm"),
        "build_year": extra.get("build_year"),
        "structure_type": extra.get("structure_type"),
        "property_cert_no": extra.get("property_cert_no"),
        "property_owner": extra.get("property_owner"),
        "property_use": extra.get("property_use"),
        "mortgage_reg_no": extra.get("mortgage_reg_no"),
        "completeness": claim.completeness,
        "missing_fields": json.loads(claim.missing_fields) if claim.missing_fields else [],
        "attachment_links": attachment_links,
    }


def _build_kyb_summary(reg_data: dict) -> dict:
    """KYB 式主体核验摘要（借鉴企查查官方 SKILL 工作流）：企业名称/信用代码/登记状态/法人/成立日期"""
    def _get(*keys):
        for k in keys:
            if isinstance(reg_data, dict) and reg_data.get(k):
                return reg_data[k]
        return None
    return {
        "company_name": _get("企业名称", "名称", "companyName"),
        "uscc": _get("统一社会信用代码", "信用代码", "uscc", "creditCode"),
        "reg_status": _get("登记状态", "状态", "regStatus"),
        "legal_rep": _get("法定代表人", "法人", "legalPerson", "legalRep"),
        "reg_capital": _get("注册资本", "regCapital"),
        "established": _get("成立日期", "成立时间", "establishedDate"),
        "note": "主体信息来自企查查工商登记（公示系统 T+3 更新），用于核验债权主体真实性；如需更强核验可补充统一社会信用代码比对。",
    }


async def _node2_judicial(claim: Claim) -> dict:
    """节点② 工商/司法风险

    配置企查查 QCC_TOKEN 时优先走企查查（工商登记 + 股东 + 变更 + 只扫命中清单；
    query_engine_summary 已含股东/变更，2026-09-04 用户确认主动查，三功能共享缓存复用），
    失败/未配置时回退免费源（gsxt 公示系统 + 执行信息公开网），并如实标注来源。
    """
    result: dict = {"type": claim.debtor_type or "enterprise", "source_status": {}}

    # ---- 企查查优先（企业债务人）----
    if settings.qcc_token and claim.debtor_type == "enterprise" and claim.debtor_name:
        try:
            from ..api.qcc import query_engine_summary

            q = await query_engine_summary(claim.debtor_name)
            reg = q.get("reg") or {}
            if reg.get("ok") and isinstance(reg.get("data"), dict):
                result["basic"] = reg["data"]
                result["source_status"]["qcc"] = "ok"

                shr = q.get("shareholders") or {}
                # 股东信息来自 eng 共享缓存（2026-09-04 尽调主动查，进工具缓存供画像/线索复用）；
                # 有数据才展示股东区块
                if shr.get("ok") and shr.get("data"):
                    result["shareholders"] = shr.get("data")

                # KYB 式主体核验摘要（企查查官方 SKILL 工作流借鉴）
                result["kyb"] = _build_kyb_summary(reg["data"])

                # 数据截至年份（共享缓存 1 年有效；2026-08-31 用户确认：基本信息变化小，
                # 报告只标注年份，不逐日刷新；利息另行实时计算到报告当日）
                qa = q.get("queried_at") or ""
                result["data_as_of"] = qa[:4] + "年" if qa else None

                scan = q.get("risk", {}).get("scan") or {}
                # 只扫不钻（2026-09-04）：命中清单 risk.hits（label/count + 缓存已有明细的示例案号，
                # 零积分）；旧缓存无 hits 时回退从 scan 因子折算，保证兼容
                hits = q.get("risk", {}).get("hits") or []
                if hits:
                    risk_factors = [
                        {"label": h.get("label") or "", "count": h.get("count") or 0,
                         **({"sample": h["sample"]} if h.get("sample") else {})}
                        for h in hits
                    ]
                else:
                    factors = scan.get("data", {}).get("风险因子扫描") or [] if scan.get("ok") else []
                    risk_factors = [
                        {"label": f["风险因子"], "count": f.get("条目数") or 0}
                        for f in factors if (f.get("条目数") or 0) > 0
                    ]
                result["risk_factors"] = risk_factors
                factor_count = {f["label"]: f["count"] for f in risk_factors}
                result["judicial_risk"] = {
                    "source": "企查查",
                    "execution_found": factor_count.get("被执行人", 0) > 0,
                    "dishonest_found": factor_count.get("失信信息", 0) > 0,
                    "factors": factor_count,
                    "note": scan.get("data", {}).get("摘要") or "未发现司法风险记录",
                    "need_manual_verify": False,
                }
                return result
        except Exception as e:  # noqa: BLE001
            logger.warning("QCC node2 failed for %s, fallback free sources: %s", claim.debtor_name, e)
            result["source_status"]["qcc"] = "需人工核实"

    # ---- 回退：免费源 ----
    judicial = get_judicial_source()

    if claim.debtor_type == "enterprise":
        ent = get_enterprise_source()
        basic = await ent.get_basic_info(claim.debtor_name or "")
        result["basic"] = basic.data if basic.success else None
        result["source_status"]["gsxt"] = "ok" if basic.success else basic.note

    exec_r = await judicial.search_execution(claim.debtor_name or "")
    dishon_r = await judicial.search_dishonest(claim.debtor_name or "")
    note = ""
    if exec_r.success or dishon_r.success:
        note = "已查询司法公开信息，未见明确风险记录" if not (exec_r.success and dishon_r.success) else ""
    result["judicial_risk"] = {
        "execution_found": exec_r.success,
        "dishonest_found": dishon_r.success,
        "source": judicial.name,
        "note": note or "暂未获取到司法信息，建议人工核实",
        "need_manual_verify": not (exec_r.success and dishon_r.success),
    }
    result["source_status"]["zxgk"] = "ok" if (exec_r.success or dishon_r.success) else "需人工核实"
    return result


async def _node3_legal(claim: Claim) -> dict:
    """节点③ 法律检索（P0 尽力而为，降级标注）

    法规依据：从知识库（LegalDoc）按债权场景匹配**具体法条**（如《民诉法》第232/234条、
    《执行异议复议规定》等），展示"依据《XX法》"字样；无匹配则不输出——
    绝不写"法规依据由系统生成"（易被误读为系统凭空造法）。
    """
    # 2026-09-05：用户上传过判决书/裁判材料时，不写"未检索到相关判决书"（那条针对企查查检索，
    # 与用户材料无关，会自相矛盾）；改按用户材料说明
    extra = {}
    try:
        extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
    except Exception:
        extra = {}
    has_user_doc = bool(extra.get("case_number") or extra.get("judgment_result") or claim.source_type == "doc")
    if has_user_doc:
        case_no = extra.get("case_number")
        jr = extra.get("judgment_result")
        note = []
        if case_no:
            note.append(f"已根据您上传的判决书（案号 {case_no}）分析")
        elif jr:
            note.append(f"已根据您上传的裁判材料分析（{jr}）")
        else:
            note.append("已根据您上传的判决书/裁定书等材料分析")
        if not extra.get("interest_method"):
            note.append("材料中未见明确的利息计算条款，如需精确计息可在报告页补充")
        note_text = "；".join(note)
        result = {
            "documents": {
                "found": True,
                "items": [{"item": "用户上传判决书/材料", "status": "已采用",
                           "note": f"案号：{case_no}" if case_no else "已作为本息与案情分析依据"}],
                "not_found_note": note_text,
            },
        }
    else:
        result = {
            "documents": {
                "found": False,
                "not_found_note": "未检索到相关判决书，本息为估算，建议上传补充材料",
            },
        }
    statutes = _match_statutes(claim)
    if statutes:
        result["statutes"] = statutes  # [{name, doc_no, summary}]
    return result


def _match_statutes(claim: Claim) -> list[dict]:
    """按债权场景从知识库匹配具体法规依据（匹配关键词命中即引用）。

    规则：司法状态/担保/抵押物/计息等特征命中 LegalDoc.keywords 时引用该法，
    引用的是真实现行法规（含文号），展示"依据《XX》"；命中多条并列展示。
    """
    from ..database import SessionLocal
    from ..models import LegalDoc

    extra = {}
    try:
        import json as _json
        extra = _json.loads(claim.extra_fields) if claim.extra_fields else {}
    except Exception:
        extra = {}

    # 债权特征关键词集合（用于命中知识库 keywords）
    features = []
    text = " ".join(filter(None, [
        claim.judicial_status or "",
        claim.guaranty_type or "",
        claim.guarantor or "",
        claim.collateral or "",
        extra.get("mortgage_rank") or "",
        extra.get("seizure") or "",
        extra.get("case_cause") or "",
        extra.get("debt_type") or "",  # 2026-09-04：融资租赁等债权类型参与法规匹配
        "执行异议" if extra.get("seizure") or "执行" in (claim.judicial_status or "") else "",
        "司法拍卖" if "拍卖" in (claim.judicial_status or "") else "",
    ]))

    # 结构化的命中规则（比关键词更稳）：司法状态/担保/抵押物/自然人等
    rules = []
    j = claim.judicial_status or ""
    if "执行" in j or "判决" in j:
        rules += ["执行异议", "民诉法,保全,执行", "拍卖款"]
    if claim.guarantor or claim.guaranty_type:
        rules += ["保证,连带责任保证", "担保制度"]
    if claim.collateral:
        rules += ["执行异议,复议,唯一住房", "司法拍卖"] if "住宅" in claim.collateral else ["司法拍卖"]
    if extra.get("seizure") or "轮候" in (claim.collateral or ""):
        rules += ["执行异议"]
    if (claim.debtor_type or "") == "person":
        # 唯一住房：仅单套住宅可能触发，且为条件式提示（未确认不能下定论）
        from .reminder_engine import _is_single_residence_maybe
        coll = claim.collateral or ""
        if "唯一住房" in coll or _is_single_residence_maybe(coll):
            rules += ["唯一住房执行条件（满足条件可执行：提供安置住房或扣除5-8年租金；未确认唯一住房前仅作提示）"]

    db = SessionLocal()
    try:
        docs = db.query(LegalDoc).filter(LegalDoc.status == "现行有效").all()
        matched = []
        used = set()
        for d in docs:
            if d.id in used or not d.keywords:
                continue
            kw = d.keywords.split(",")
            # 内部经验/行业常识类不展示为"法规依据"
            if d.doc_no == "内部经验":
                continue
            hit = False
            for r in rules:
                if all(k.strip() in (d.keywords or "") for k in r.split(",") if k.strip()):
                    hit = True
                    break
            if not hit:
                # 兜底：债权特征文本直接命中关键词
                for k in kw:
                    if k.strip() and len(k.strip()) > 1 and k.strip() in text:
                        hit = True
                        break
            if hit:
                matched.append({
                    "name": d.title,
                    "doc_no": d.doc_no or "",
                    "summary": (d.summary or "")[:120],
                })
                used.add(d.id)
        # 去重（按标题）
        seen = set()
        out = []
        for m in matched:
            if m["name"] not in seen:
                seen.add(m["name"])
                out.append(m)
        return out[:5]
    finally:
        db.close()


async def _node4_valuation(claim: Claim) -> dict:
    """节点④ 抵押物分析：估值区间（粗估）+ 覆盖本息判断

    估值口径（用户确认 2026-08-25）：
    - 工业类（土地/厂房）：成本法 = 土地出让价 + 厂房建安造价×折旧（20年/残值5%），
      只有土地算土地，有土地+厂房则合计；数据精度后期按真实公示数据细化。
    - 非工业类（住宅/商铺/写字楼等）：维持市场价区间粗估。
    平台边界：只做抵押物评估（处置依据，非债权定价），估值区间+本息合计并列展示，
    不做7折/8折情景表、不算账、不做买入建议。市场价格无法确定，明确标注为粗估。
    融资租赁债权（2026-09-04 用户确认）：设备充当担保物，视同有抵押物、不做设备估价、
    不写覆盖率；抵押物区块展示设备清单原文或"设备租赁"。
    """
    extra = {}
    try:
        extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
    except Exception:
        extra = {}

    # 融资租赁设备债权：视同有抵押物，但不做设备估价与覆盖率分析
    if extra.get("lease_equipment") == "1":
        lease_note = ("本债权为融资租赁（设备租赁）：租赁物（设备）作为担保物视同抵押物，"
                      "平台暂不对设备估价，也不计算抵押物对债权的覆盖率。"
                      "回收主要依赖设备处置或承租方继续履约，建议结合设备成新率/二手市场另行评估。")
        return {
            "present": True,
            "lease_equipment": True,
            "collateral_desc": claim.collateral or "设备租赁",
            "collateral_type": extra.get("collateral_type") or "设备（租赁物）",
            "valuation": None,
            "valuation_method": "融资租赁：不做设备估价",
            "valuation_notes": [],
            "coverage_vs_interest": None,
            "coverage_note": "融资租赁设备债权：不计算覆盖率",
            "liquidity": lease_note,
            "note": lease_note,
        }

    if not claim.collateral:
        return {
            "present": False,
            "note": "无抵押物信息（待补充）",
            "valuation": None,
            "coverage_vs_interest": None,
        }

    from .land_factory_valuation import estimate_land_factory

    # 评估报告（2026-09-01 用户规则）：2 年内评估值直接采用；超 2 年走成本法，报告仍展示
    # 信息来自详情页附件（startDD 时随 sourceText 传入，LLM 提取至 extra_fields.valuation_report）
    val_report = extra.get("valuation_report")
    if isinstance(val_report, str):
        try:
            import json as _json
            val_report = _json.loads(val_report)
        except Exception:
            val_report = None
    current_year = datetime.now().year
    if val_report and isinstance(val_report, dict):
        year = val_report.get("year")
        value_cents = val_report.get("value_cents")
        if year and value_cents:
            age = current_year - int(year)
            if 0 <= age <= 2:
                # 2 年内：直接采用评估值（房产近年降价大，仅近年评估可信）
                valuation = {
                    "conservative_cents": value_cents,
                    "neutral_cents": value_cents,
                    "optimistic_cents": value_cents,
                    "reference_cents": value_cents,
                    "reference_label": f"评估报告（{year}年）",
                    "method": "评估报告",
                    "data_insufficient": False,
                    "unit_price_range": "",
                    "area_sqm": None,
                }
                result = {"valuation": valuation, "method": "评估报告", "notes": [f"依据{year}年评估报告，评估价值 {val_report.get('value_text')}，2年内直接采用"]}
            else:
                # 超 2 年：走成本法，但标注报告存在
                result = estimate_land_factory(claim.collateral or "", extra)
                if result.get("notes") is None:
                    result["notes"] = []
                result["notes"].append(
                    f"存在{year}年评估报告（{val_report.get('value_text')}），已超过2年（房产近年降价大），仅作参考，按成本法估值"
                )
        else:
            result = estimate_land_factory(claim.collateral or "", extra)
    else:
        result = estimate_land_factory(claim.collateral or "", extra)
    valuation = result.get("valuation")

    # 覆盖判断（用户确认口径 2026-08-26）：覆盖率 = 本息合计 ÷ 抵押物估值
    # ≥100% 覆盖（本息≥抵押物：处置无需倒找债务人，差额可追偿）；<100% 未覆盖（处置后可能退还债务人多余款项）
    coverage = None
    if valuation and valuation.get("reference_cents"):
        total_interest_cents = None
        if claim.principal_cents is not None:
            total_interest_cents = claim.principal_cents + (claim.interest_cents or 0)
        if total_interest_cents and total_interest_cents > 0:
            collateral_cents = valuation["reference_cents"]
            ratio = total_interest_cents / collateral_cents
            covered = ratio >= 1.0
            coverage = {
                "collateral_cents": collateral_cents,
                "collateral_label": valuation.get("reference_label") or "抵押物主参考估值",
                "interest_total_cents": total_interest_cents,
                "coverage_ratio": round(ratio * 100, 1),
                "covered": covered,
                # 未覆盖：处置/以物抵债后可能须退还债务人多余款项（平台核心规则）
                "note": (
                    f"抵押物{valuation.get('reference_label') or '估值'}与债权本息对照：本息对抵押物覆盖比例约 {ratio * 100:.1f}%。"
                    + ("覆盖充足：处置抵押物所得可全部抵债，本息超出抵押物的差额可继续向债务人追偿。"
                       if covered else
                       "未覆盖：本息低于抵押物估值，若处置或以物抵债，超出债权本息的部分可能需要退还债务人。"),
                ),
            }

    liquidity = "数据不足，建议专业评估机构出具正式评估报告；需核实抵押物占用/租赁/清场情况"
    # 房产证/抵押物明细（2026-09-02：证上有的字段全部提取并在抵押物版块展示）
    result_dict = {
        "present": True,
        "collateral_desc": claim.collateral,
        "collateral_type": extra.get("collateral_type"),
        "property_cert_no": extra.get("property_cert_no"),
        "property_owner": extra.get("property_owner"),
        "property_use": extra.get("property_use"),
        "mortgage_reg_no": extra.get("mortgage_reg_no"),
        "land_area_sqm": extra.get("land_area_sqm"),
        "building_area_sqm": extra.get("building_area_sqm"),
        "build_year": extra.get("build_year"),
        "structure_type": extra.get("structure_type"),
        "valuation": valuation,
        "valuation_method": result.get("method"),
        "valuation_notes": result.get("notes", []),
        "coverage_vs_interest": coverage,
        "liquidity": liquidity,
    }
    # AI 抵押物解读（可选增强，失败降级为无解读；数字一律引用系统数据，禁止 AI 编造）
    ai_note = await _ai_collateral_note(claim, valuation, coverage)
    if ai_note:
        result_dict["ai_note"] = ai_note
    return result_dict


async def _ai_collateral_note(claim: Claim, valuation: dict | None, coverage: dict | None) -> str | None:
    """AI 抵押物解读：基于估值数据生成一段客观解读（不引入新数字）。

    约束：只解读系统已算出的估值/面积/覆盖数字，缺失信息标「需人工核实」，禁止编造。
    失败/无 Key 时返回 None（前端降级为无解读，不阻塞）。
    """
    if not valuation or not settings.deepseek_api_key:
        return None
    try:
        system = (
            "你是不良资产抵押物分析专家。请基于给定的抵押物估值数据，用 2-4 句话客观解读抵押物的"
            "价值特点、与债权的覆盖关系、处置时需关注的要点。\n"
            "铁律：只能引用系统给出的数字（估值区间、面积、单价、参考估值、本息合计、覆盖比例）；"
            "禁止编造任何数字、面积、地址、权属信息；数据缺失标「需人工核实」；"
            "不输出买入建议、不预测成交价、不输出 7 折/8 折折算；不用\"AI\"字样。\n"
            "覆盖口径（用户确认的行业规则）：覆盖率 = 本息合计 ÷ 抵押物估值。≥100% 为覆盖（处置抵押物所得全部抵债、无需倒找债务人、差额可追偿，覆盖越多越好）；"
            "<100% 为未覆盖（处置/以物抵债后可能须退还债务人多余款项，买家一般不买或暂缓处置等利息覆盖）。"
            "解读时站在债权人/不良资产从业者角度表述覆盖情况。\n"
            "必须严格按以下 JSON 格式输出（只输出 JSON，不要多余文字）：{\"note\": \"你的解读文字\"}"
        )
        user = json.dumps({
            "抵押物描述": claim.collateral,
            "估值区间(万元)": {
                "保守": (valuation.get("conservative_cents") or 0) / 100 / 10000,
                "乐观": (valuation.get("optimistic_cents") or 0) / 100 / 10000,
            },
            "主参考估值(万元)": (valuation.get("reference_cents") or 0) / 100 / 10000,
            "参考口径": valuation.get("reference_label"),
            "单价参考": valuation.get("unit_price_range"),
            "面积": valuation.get("area_sqm"),
            "本息合计(万元)": (coverage or {}).get("interest_total_cents", 0) / 100 / 10000 if coverage else None,
            "覆盖比例(%)": (coverage or {}).get("coverage_ratio") if coverage else None,
            "是否覆盖": "覆盖" if (coverage or {}).get("covered") else ("未覆盖" if coverage else None),
        }, ensure_ascii=False)
        r = await chat_json(system, user, temperature=0.3)
        note = str(r.get("note") or r.get("analysis") or "").strip()
        return note if len(note) >= 10 else None
    except LLMError:
        logger.warning("AI collateral note failed, skip")
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("AI collateral note error: %s", e)
        return None


def _interest_validation(principal_cents: int | None, interest_cents: int | None) -> dict | None:
    """本息校验（从业常识，用户传授 2026-08-25；仅内部防明显错误，不展示年限推断）。

    - 利息异常小（< 本金 0.5%）且本金存在 → 疑似利息漏加/单位错误
    """
    if not principal_cents or principal_cents <= 0:
        return None
    validation = {}
    if interest_cents is not None and interest_cents > 0:
        ratio = interest_cents / principal_cents
        if ratio < 0.005:
            validation["interest_suspicious"] = (
                "利息金额异常小（不足本金的 0.5%），疑似利息未计入或计量单位错误（同表单位应一致），请核对原始数据"
            )
    else:
        validation["interest_suspicious"] = "未录入利息，本息合计仅为本金；如有利息请补充（同表单位需一致）"
    return validation or None


def _node5_interest(claim: Claim) -> dict:
    """节点⑤ 本息计算（纯代码）

    计息到报告生成当日，三种情况（用户确认 2026-08-25）：
    ① 有利息截止日（表头/描述标注，如 截至2025/4/20利息XX万）：截止日利息(录入值) + 截止日→报告当日按 LPR 续算
    ② 有判决书（含计算日期和利率）：按判决书日期、利率精确算到报告当日
    ③ 无任何计息信息：直接用录入的利息数额，写明『计息至本债权首次发布日期』（权威机构发布日，非本站）
    """
    principal = claim.principal_cents
    if principal is None:
        return {"mode": "none", "note": "本金缺失，无法计算本息", "total_cents": None}

    extra = {}
    try:
        extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
    except Exception:
        extra = {}

    known_interest = claim.interest_cents  # 用户录入/表内利息（截止日时点或发布时点）
    today = date.today()

    def _parse_date(s) -> date | None:
        if not s:
            return None
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    # 判决书利率（情况②）
    judgment_rate = extra.get("judgment_rate")
    penalty_per_day = extra.get("penalty_per_day")
    # 2026-09-05：用户上传了判决书/裁判材料（有案号/裁判结果/利率）→ 提示语与估算口径随之调整，
    # 不再写"未检索到判决书"（那是对应企查查扫描，与用户上传材料无关）
    has_uploaded_judgment = bool(
        extra.get("case_number") or extra.get("judgment_result") or judgment_rate
        or (claim.source_type == "doc")
    )
    has_judgment = bool(judgment_rate and float(judgment_rate) > 0)

    if has_judgment:
        # ② 判决书：起算日（判决书写的计息起始）→ 报告当日，按判决利率
        start = _parse_date(extra.get("interest_base_date"))
        if start is None:
            # 无起算日，尝试从 source_raw 提取
            import re as _re
            m = _re.search(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?", claim.source_raw or "")
            if m:
                try:
                    start = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except Exception:
                    start = None
        if start:
            try:
                result = calculate_interest(
                    principal, start, today,
                    has_judgment=True,
                    judgment_rate=float(judgment_rate),
                    judgment_penalty_per_day=float(penalty_per_day) if penalty_per_day else None,
                )
                return {
                    "mode": result.calculation_mode,
                    "items": result.items,
                    "total_cents": result.total_cents,
                    # 依据用户上传判决书计算（rate 在 items note 中体现）
                    "basis_note": f"按您上传判决书确定的利率（年 {float(judgment_rate) * 100:g}%）计至 {today.isoformat()}（报告生成当日）",
                    "basis_label": "截止今日",
                    "start_date": start.isoformat(),
                    "end_date": today.isoformat(),
                    "has_judgment": True,
                    "source_judgment": True,
                    "validation": _interest_validation(principal, result.total_cents - principal),
                }
            except Exception as e:  # noqa: BLE001
                logger.warning("judgment interest calc failed: %s", e)
        else:
            # 有判决书利率但缺起算日 → 说明情况，给估算口径（不按无信息处理）
            rate_days_note = f"已识别判决书年利率 {float(judgment_rate) * 100:g}%，但未识别出计息起算日"
            if known_interest:
                return {
                    "mode": "no_info",
                    "items": [
                        {"name": "本金", "amount_cents": principal, "note": ""},
                        {"name": "利息", "amount_cents": known_interest, "note": "判决书载明利息"},
                    ],
                    "total_cents": principal + known_interest,
                    "basis_note": f"{rate_days_note}，暂按判决书载明利息列示；如需精确续算请在报告页补充计息起算日",
                    "basis_label": "判决书载明",
                    "has_judgment": True,
                    "source_judgment": True,
                    "validation": _interest_validation(principal, known_interest),
                }
            return {
                "mode": "none",
                "note": f"{rate_days_note}，无法计算截止今日利息",
                "total_cents": None,
                "has_judgment": True,
                "source_judgment": True,
            }

    # ① 有利息截止日 → 截止日利息 + 截止日→当日按 LPR 续算
    cutoff = _parse_date(extra.get("interest_base_date"))
    if cutoff is None:
        # 尝试从描述/原始文本提取『截至X年X月X日利息』
        import re as _re
        m = _re.search(r"(?:截至|截止|截止到|至)\s*(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})日?", claim.source_raw or "")
        if m:
            try:
                cutoff = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                cutoff = None
    if cutoff:
        if cutoff >= today:
            # 截止日不早于当日：直接用录入利息
            total = principal + (known_interest or 0) if known_interest else principal
            return {
                "mode": "cutoff_no_continue",
                "items": [
                    {"name": "本金", "amount_cents": principal, "note": ""},
                    {"name": "利息", "amount_cents": known_interest or 0, "note": f"计息至 {cutoff.isoformat()}"},
                ],
                "total_cents": total,
                "basis_note": f"利息计至 {cutoff.isoformat()}（表中截止日）",
                "basis_label": "截止今日",
                "cutoff_date": cutoff.isoformat(),
                "end_date": today.isoformat(),
                "has_judgment": False,
                "validation": _interest_validation(principal, known_interest),
            }
        # 续算：截止日利息 + 截止日→当日 LPR
        base_interest = known_interest or 0
        extra_days = (today - cutoff).days
        extra_interest = int(round(principal * 0.0345 * extra_days / 365)) if extra_days > 0 else 0
        total_interest = base_interest + extra_interest
        items = [
            {"name": "本金", "amount_cents": principal, "note": ""},
            {"name": "利息（截止日累计）", "amount_cents": base_interest, "note": f"计至 {cutoff.isoformat()}"},
        ]
        if extra_interest > 0:
            items.append({"name": "利息（续算）", "amount_cents": extra_interest,
                          "note": f"{cutoff.isoformat()} 至 {today.isoformat()}，按 LPR 3.45%/年（{extra_days}天）"})
        return {
            "mode": "cutoff_continue",
            "items": items,
            "total_cents": principal + total_interest,
            "basis_note": "利息是按 LPR 计的，如有详细信息请在报告底部补充",
            "basis_label": "截止今日",
            "cutoff_date": cutoff.isoformat(),
            "end_date": today.isoformat(),
            "has_judgment": False,
            "validation": _interest_validation(principal, total_interest),
        }

    # ③ 无任何计息信息：直接用录入利息
    total = principal + (known_interest or 0) if known_interest else principal
    # 2026-09-05：用户上传了判决书但未能识别出利率/起算日 → 明确说明，不再写笼统"无计息信息"
    if has_uploaded_judgment:
        return {
            "mode": "no_info",
            "items": [
                {"name": "本金", "amount_cents": principal, "note": ""},
                {"name": "利息", "amount_cents": known_interest or 0,
                 "note": "判决书载明利息" if known_interest else ""},
            ] if known_interest else [{"name": "本金", "amount_cents": principal, "note": ""}],
            "total_cents": total,
            "basis_note": ("已识别您上传的判决书（案号 %s），但未识别出明确的利率/计息起算信息，"
                           "暂按判决书载明利息列示；如需按利率精确续算，请在报告页补充计息条款后重新生成。"
                           % extra.get("case_number")) if extra.get("case_number")
                          else "已识别您上传的判决书，但未识别出明确的利率/计息起算信息，暂按 LPR 估算；可在报告页补充判决书计息条款后重新生成",
            "basis_label": "判决书载明" if extra.get("case_number") else "估算",
            "end_date": today.isoformat(),
            "has_judgment": False,
            "source_judgment": True,
            "validation": _interest_validation(principal, known_interest),
        }
    return {
        "mode": "no_info",
        "items": [
            {"name": "本金", "amount_cents": principal, "note": ""},
            {"name": "利息", "amount_cents": known_interest or 0, "note": "计息至债权发布日（权威机构/银行/AMC 发布时点）"},
        ] if known_interest else [{"name": "本金", "amount_cents": principal, "note": ""}],
        "total_cents": total,
        "basis_note": "因无计息信息，截止今日利息无法估算，可以本页底部补充",
        "basis_label": "截止债权发布日",
        "end_date": today.isoformat(),
        "has_judgment": False,
        "validation": _interest_validation(principal, known_interest),
    }


async def _node6_summary(claim: Claim, nodes: dict) -> dict:
    """节点⑥ LLM 综合分析（P0 无 API Key 时生成降级摘要）

    平台边界：综合评级只给星（不给文字建议）；不做买入建议/利润测算。
    """
    lease = False
    try:
        _extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
        lease = _extra.get("lease_equipment") == "1"
    except Exception:
        lease = False
    if not settings.deepseek_api_key:
        return _fallback_summary(claim, nodes)
    system = """你是不良资产尽调分析专家。基于提供的尽调数据，生成报告摘要与风控评估。
要求：
0. 输出内容中严禁出现"AI"字样（AI生成/AI分析等一律禁用）；涉及系统能力表述时使用"平台"二字。
1. 严格按 JSON 输出：{"summary": {"rating": "★~★★★★★", "core_logic": [..]},
   "risk": {"favorable": [..], "risk": [..], "need_manual_verify": [..]}}
2. 所有结论必须来自给定数据，数据缺失标"需人工核实"，禁止编造。
3. 覆盖口径（用户确认的行业规则，务必遵守）：覆盖率 = 本息合计 ÷ 抵押物估值。
   ≥100% 为覆盖（处置抵押物所得全部抵债、无需倒找债务人、差额可继续追偿，覆盖越多越好）；
   <100% 为未覆盖（处置/以物抵债后可能须退还债务人多余款项）。
   站在债权人/不良资产从业者角度分析：覆盖越多，回收保障越强。
4. 评级规则（只给星，不下买入建议）：★★★★★ 覆盖>150%且司法清晰；★★★★ 覆盖100%~150%；
   ★★★ 覆盖70%~100%（接近覆盖）；★★ 覆盖40%~70%（未覆盖，处置可能须退还多余款项）；
   ★ 覆盖<40%或重大不确定。
5. 严禁输出：建议买入价、收益率、利润测算、买入决策。"""
    if lease:
        # 融资租赁设备债权（2026-09-04 用户确认）：不做设备估价与覆盖率分析，评级改按司法/主体情况
        system += (
            "\n6. 本条为融资租赁设备债权：设备（租赁物）充当担保物，平台不做设备估价、不计算覆盖率，"
            "因此第 3/4 条的覆盖口径与覆盖率评级一律不适用，禁止输出任何覆盖比例与'覆盖/未覆盖'结论；"
            "评级请综合司法状态（是否胜诉/执行进展）、债务人经营状况、租金回收可能、设备残值可处置性给出，"
            "并仅在 core_logic 说明评级依据。"
        )
    user = json.dumps({"claim": _build_claim_dict(claim), "nodes": nodes}, ensure_ascii=False)
    try:
        result = await chat_json(system, user, temperature=0.3)
        # 安全兜底：删除任何越界的建议买入字段
        result.get("summary", {}).pop("suggested_buy_ratio", None)
        result.get("summary", {}).pop("suggested_buy_price", None)
        return result
    except LLMError:
        logger.warning("node6 LLM failed, fallback summary")
        return _fallback_summary(claim, nodes)


def _fallback_summary(claim: Claim, nodes: dict) -> dict:
    """无 API Key / LLM 失败时的降级摘要（只给星，不给建议）

    覆盖口径（用户确认 2026-08-26）：覆盖率 = 本息合计 ÷ 抵押物估值。
    ≥100% 覆盖（处置抵押物所得全部抵债、差额可追偿，覆盖越多越好）；<100% 未覆盖。
    """
    principal_wan = (claim.principal_cents or 0) / 100 / 10000
    principal_text = f"{principal_wan:.2f}万元" if claim.principal_cents else "未知"
    lease = False
    try:
        _extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
        lease = _extra.get("lease_equipment") == "1"
    except Exception:
        lease = False
    # 按抵押物覆盖情况给星（覆盖率 = 本息 ÷ 抵押物估值）；融资租赁设备债权不做覆盖率评级
    rating = "★★★"
    coverage_ratio = None
    covered = None
    if not lease:
        try:
            val = nodes.get("collateral", {}).get("valuation") or {}
            coverage = nodes.get("collateral", {}).get("coverage_vs_interest") or {}
            collateral = coverage.get("collateral_cents") or val.get("reference_cents") or val.get("neutral_cents")
            total = coverage.get("interest_total_cents")
            if collateral and total and collateral > 0:
                ratio = total / collateral  # 本息 ÷ 抵押物
                coverage_ratio = round(ratio * 100, 1)
                covered = ratio >= 1.0
                if ratio >= 1.5:
                    rating = "★★★★★"
                elif ratio >= 1.0:
                    rating = "★★★★"
                elif ratio >= 0.7:
                    rating = "★★★"
                elif ratio >= 0.4:
                    rating = "★★"
                else:
                    rating = "★"
        except Exception:
            pass
    logic = [f"债务人：{claim.debtor_name or '未知'}；本金：{principal_text}（详见报告）"]
    risk_items = ["司法状态需人工核实"]
    if coverage_ratio is not None:
        logic.append(f"抵押物对债权本息覆盖比例约 {coverage_ratio}%（本息合计对抵押物估值）")
        if covered is False:
            risk_items.append("未覆盖：本息低于抵押物估值，处置或以物抵债后可能存在退还债务人多余款项的问题")
    if lease:
        logic.append("本债权为融资租赁设备债权：设备（租赁物）充当担保物，平台不做设备估价与覆盖率分析")
    return {
        "summary": {
            "rating": rating,
            "core_logic": logic,
        },
        "risk": {
            "favorable": (["融资租赁设备债权：设备（租赁物）作为担保物视同有抵押物"]
                          if lease else (["抵押物信息已录入（估值见抵押物分析）"] if claim.collateral else [])),
            "risk": risk_items,
            "need_manual_verify": (["租金支付/逾期记录", "设备现状与成新率", "承租人经营状况"]
                                   if lease else ["本息计算基准日", "判决书", "抵押物估值", "抵押物占用/租赁情况"]),
        },
    }


async def build_report_content(claim: Claim, progress: NodeProgress) -> dict:
    """对单个债权执行完整尽调，返回 9 版块报告 JSON。"""
    nodes: dict[str, Any] = {}

    await progress.step(NODES[1], 20)
    nodes["debtor"] = await _node2_judicial(claim)

    await progress.step(NODES[2], 35)
    nodes["legal"] = await _node3_legal(claim)

    await progress.step(NODES[3], 50)
    nodes["collateral"] = await _node4_valuation(claim)

    await progress.step(NODES[4], 65)
    nodes["interest"] = _node5_interest(claim)

    await progress.step(NODES[5], 80)
    dd_result = {
        "legal_documents": nodes["legal"].get("documents", {}).get("items", []),
        "execution_cases": 0,
        "disposal_path": "司法拍卖",
    }
    reminders = reminder_engine.match(claim, dd_result)

    summary = await _node6_summary(claim, nodes)

    now = datetime.now()
    content = {
        "report_meta": {
            "report_no": f"ZXF-{now:%Y%m%d}-{claim.id}-v1",
            "debtor_name": claim.debtor_name,
            "debtor_type": claim.debtor_type or "enterprise",
            "generated_at": now.isoformat(),
            "data_sources": ["用户输入", "企查查", "国家企业信用信息公示系统", "中国执行信息公开网"],
            "version": 1,
            "report_style": "full" if (claim.debtor_type or "enterprise") == "enterprise" else "simplified",
        },
        # 顶部结论条：综合评级（只给星）+ 关键数字
        "conclusion_bar": {
            "rating": summary.get("summary", {}).get("rating", "★★★"),
            "principal_text": _cents_to_wan(claim.principal_cents),
            "interest_total_text": _cents_to_wan(nodes.get("interest", {}).get("total_cents")),
            "interest_basis_label": nodes.get("interest", {}).get("basis_label") or "截止今日",
            "collateral_valuation_text": ("设备租赁（不做估价）"
                                          if nodes.get("collateral", {}).get("lease_equipment")
                                          else _format_valuation(nodes.get("collateral", {}).get("valuation"))),
            "recovery_cycle_estimate": nodes.get("collateral", {}).get("liquidity") or "待核实",
        },
        "sections": {
            "summary": summary.get("summary", {}),
            "reminders": {"items": [r.__dict__ for r in reminders], "matched_count": len(reminders)},
            "claim_basic": {
                "basic_table": _build_claim_dict(claim),
                "interest_detail": nodes["interest"],
            },
            "legal_completeness": _build_legal_completeness(claim),  # 法律文件完备性（新）
            "debtor": nodes["debtor"],
            "guarantor": {"present": bool(claim.guarantor), "note": "担保人详情需人工核实" if claim.guarantor else None},
            "collateral": nodes["collateral"],
            "legal": nodes["legal"],
            "execution_recovery": await _build_execution_recovery(claim, nodes),  # 司法执行与受偿（新）
            "risk": summary.get("risk", {}),
            "disposal": await _build_disposal_section(claim, nodes),  # 多路径处置方案
            "pending_supplements": _build_pending_supplements(claim, nodes),  # 待补充信息清单
        },
        "disclaimer": "本报告由 NPL CN 平台基于公开信息和系统分析自动生成，仅供参考，不构成投资建议。报告中的估值基于公开市场数据粗估，不替代专业评估机构出具的正式评估报告。投资决策请结合专业律师意见和实地尽调结果。",
    }
    return content


def _cents_to_wan(cents) -> str:
    if cents is None:
        return "未知"
    return f"{cents / 100 / 10000:.4f}万元"


def _format_valuation(val) -> str:
    if not val:
        return "待评估"
    if val.get("data_insufficient"):
        return "需现场评估"
    ref = val.get("reference_cents")
    lo = val.get("conservative_cents")
    hi = val.get("optimistic_cents")
    if ref:
        ref_wan = ref / 100 / 10000
        label = val.get("reference_label") or "主参考估值"
        if lo and hi:
            return f"{ref_wan:.4f}万元（{label}；区间{lo / 100 / 10000:.4f}~{hi / 100 / 10000:.4f}万元）"
        return f"{ref_wan:.4f}万元（{label}）"
    if lo and hi:
        return f"{lo / 100 / 10000:.4f}~{hi / 100 / 10000:.4f}万元（粗估）"
    return "待评估"


def _build_legal_completeness(claim: Claim) -> dict:
    """法律文件完备性：合同/担保/抵押登记/催收 是否齐全（Word 清单第6类）"""
    extra = {}
    try:
        extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
    except Exception:
        extra = {}
    items = []
    checks = [
        ("借款合同", bool(claim.source_raw or extra.get("has_loan_contract"))),
        ("担保合同/保证文件", bool(claim.guarantor or extra.get("has_guarantee_contract"))),
        ("抵押登记证明", bool(extra.get("mortgage_cert") or claim.collateral)),
        ("催收通知/债权转让通知", bool(extra.get("has_notice"))),
        ("诉讼时效", "待核实" if not extra.get("limitation_verified") else "已核实"),
    ]
    for name, ok in checks:
        if ok is True:
            items.append({"item": name, "status": "已具备", "note": ""})
        elif ok is False:
            items.append({"item": name, "status": "待补充", "note": "缺文件或信息，请在补充材料中上传"})
        else:
            items.append({"item": name, "status": "待核实", "note": "需人工核实"})
    return {"present": True, "items": items, "note": "法律文件完备性影响债权有效性与追偿可行性，缺失项请在补充材料中补齐"}


async def _build_execution_recovery(claim: Claim, nodes: dict) -> dict:
    """司法执行与受偿分析（独立成章）：清偿顺序/轮候查封受偿/执行异议风险 + AI 解读"""
    extra = {}
    try:
        extra = json.loads(claim.extra_fields) if claim.extra_fields else {}
    except Exception:
        extra = {}
    debtor = nodes.get("debtor", {})
    risk_factors = debtor.get("judicial_risk", {}).get("factors", {}) or {}
    result = {
        "judicial_status": claim.judicial_status or "待补充",
        "mortgage_rank": extra.get("mortgage_rank") or "待核实（是否首封/抵押顺位）",
        "seizure": extra.get("seizure") or "待核实（是否有轮候查封）",
        "execution_records": {
            "executed": risk_factors.get("被执行人", 0),
            "dishonest": risk_factors.get("失信信息", 0),
            "limited_consumption": risk_factors.get("限制高消费", 0),
        },
        "repayment_priority_note": "清偿顺序：抵押担保债权优先受偿；普通债权按比例参与分配（民诉法解释第508-510条）。",
        "execution_objection_risk": {
            "risk": "债务人/案外人可能提出执行异议（民诉法第232/234条：15日审查+复议+可能执行异议之诉），处置周期可能显著拉长",
            "law_ref": "《民事诉讼法》第232条、第234条；《执行异议复议规定》",
        },
    }
    # AI 司法风险解读（可选增强，失败降级；只解读系统数据，禁止编造司法记录/案号）
    ai_note = await _ai_judicial_note(claim, result)
    if ai_note:
        result["ai_note"] = ai_note
    return result


async def _ai_judicial_note(claim: Claim, er: dict) -> str | None:
    """AI 司法风险解读：基于司法状态/执行记录客观解读（不引入新数字/案号）。"""
    if not settings.deepseek_api_key:
        return None
    try:
        system = (
            "你是不良资产司法执行分析专家。请基于给定的司法状态数据，用 2-4 句话客观解读当前司法执行形势："
            "清偿顺位、执行障碍、周期风险、下一步建议。\n"
            "铁律：只能引用系统给出的司法状态、抵押顺位、查封情况、执行记录条数；"
            "禁止编造案号、判决结果、法院名称、任何数字；缺失标「需人工核实」；"
            "不输出买入建议、不预测执行结果；不用\"AI\"字样。\n"
            "必须严格按以下 JSON 格式输出（只输出 JSON，不要多余文字）：{\"note\": \"你的解读文字\"}"
        )
        user = json.dumps({
            "司法状态": er.get("judicial_status"),
            "抵押顺位": er.get("mortgage_rank"),
            "查封情况": er.get("seizure"),
            "执行记录": er.get("execution_records"),
            "清偿顺序说明": er.get("repayment_priority_note"),
            "执行异议风险": (er.get("execution_objection_risk") or {}).get("risk"),
        }, ensure_ascii=False)
        r = await chat_json(system, user, temperature=0.3)
        note = str(r.get("note") or r.get("analysis") or "").strip()
        return note if len(note) >= 10 else None
    except LLMError:
        logger.warning("AI judicial note failed, skip")
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("AI judicial note error: %s", e)
        return None


def _build_pending_supplements(claim: Claim, nodes: dict) -> list[dict]:
    """待补充信息清单：引导用户上传什么、怎么触发重生成"""
    items = []
    interest = nodes.get("interest", {})
    if interest.get("mode") == "missing_start_date":
        items.append({"field": "计息起始日", "reason": "有利息但无开始日期无法计算，请补充计息日或上传判决书"})
    if not nodes.get("collateral", {}).get("valuation") or nodes.get("collateral", {}).get("valuation", {}).get("data_insufficient"):
        items.append({"field": "抵押物评估报告", "reason": "抵押物估值数据不足，建议上传专业评估报告"})
    if claim.missing_fields:
        try:
            for f in json.loads(claim.missing_fields):
                items.append({"field": f, "reason": "关键字段缺失"})
        except Exception:
            pass
    items.append({"field": "判决书/裁定书", "reason": "用于精确计算本息并核实司法状态"})
    items.append({"field": "抵押物占用/租赁情况", "reason": "影响清场难度与变现周期，建议实地核实"})
    return items


async def _build_disposal_section(claim: Claim, nodes: dict) -> dict:
    """处置方案版块：多路径并列对比（形式A，不替用户决策）。

    路径并列展示：司法拍卖 / 以物抵债 / 其他（协商转让/继续追偿），
    各含预计周期/成功率/风险，用户自行判断选择。
    AI 增强：对每条路径的 detail/risk 做基于数据的客观润色（不引入新数字/新路径，不标记推荐）。
    """
    from .recovery_planner import build_recovery_plan

    plan = build_recovery_plan(claim, nodes)

    # 多路径并列（形式A）：把 plan.paths 组织为并列数组，加上执行异议周期提示
    paths = []
    if "auction" in plan.get("paths", {}):
        p = plan["paths"]["auction"]
        paths.append({
            "name": "司法拍卖",
            "feasibility": p.get("feasibility", ""),
            "detail": p.get("detail", ""),
            "risk": p.get("risk", ""),
            "cycle_estimate": "评估→拍卖→过户，预计6-12个月；如遇执行异议（民诉法232/234条）周期可能延长",
        })
    if "debt_in_kind" in plan.get("paths", {}):
        p = plan["paths"]["debt_in_kind"]
        paths.append({
            "name": "以物抵债",
            "feasibility": p.get("feasibility", ""),
            "detail": p.get("detail", ""),
            "risk": p.get("risk", ""),
            "cycle_estimate": "流拍后申请，需法院认可+过户，周期视异议情况",
        })
    if "worst" in plan.get("paths", {}):
        p = plan["paths"]["worst"]
        paths.append({
            "name": "其他途径（协商转让/继续追偿）",
            "feasibility": "视情况",
            "detail": p.get("detail", ""),
            "risk": p.get("risk", ""),
            "cycle_estimate": "不确定",
        })

    result = {
        "paths": paths,  # 多路径并列，不标记"推荐"，用户自选
        "actions": plan.get("actions", []),  # 操作步骤指引
        "priority_text": plan.get("priority_text", "中"),
        "note": "以上处置路径由系统根据尽调数据自动生成，并列供参考；具体策略请结合专业律师意见，不构成投资建议。",
    }
    # 覆盖联动（平台核心规则）：未覆盖时提示退还债务人多余款项的问题
    coverage = (nodes.get("collateral") or {}).get("coverage_vs_interest") or {}
    if coverage.get("covered") is False:
        result["coverage_warning"] = (
            "本债权未覆盖（本息低于抵押物估值）：若处置抵押物或以物抵债，超出债权本息的部分可能需要退还债务人。"
            "建议暂缓处置，等利息与罚息累积到覆盖水平后再处置，避免倒找债务人款项。"
        )
    # AI 处置方案解读（可选增强，失败降级；不新增路径、不标记推荐、不引入新数字）
    ai_note = await _ai_disposal_note(claim, result, nodes)
    if ai_note:
        result["ai_note"] = ai_note
    return result


async def _ai_disposal_note(claim: Claim, disposal: dict, nodes: dict) -> str | None:
    """AI 处置方案解读：基于系统生成的路径客观补充操作要点（不新增路径/不推荐单一/不编数字）。"""
    if not settings.deepseek_api_key:
        return None
    try:
        system = (
            "你是不良资产处置专家。请基于系统给出的处置路径，用 3-5 句话客观补充每条路径的"
            "关键操作要点与注意事项（并列陈述，不标记哪条更好）。\n"
            "铁律：只能引用系统给出的路径名称/可行性/周期/风险；禁止新增处置路径、禁止建议'首选/推荐'某一路径、"
            "禁止编造金额/税费比例/法律条文号/案号；缺失标「需人工核实」；"
            "不输出买入建议、不预测成交价；不用\"AI\"字样。\n"
            "必须严格按以下 JSON 格式输出（只输出 JSON，不要多余文字）：{\"note\": \"你的解读文字\"}"
        )
        paths_brief = [
            {"名称": p.get("name"), "可行性": p.get("feasibility"), "风险": p.get("risk"), "周期": p.get("cycle_estimate")}
            for p in disposal.get("paths", [])
        ]
        user = json.dumps({
            "债务人": claim.debtor_name,
            "处置路径": paths_brief,
            "操作步骤": [{"步骤": a.get("step"), "标题": a.get("title")} for a in (disposal.get("actions") or [])],
            "司法状态": claim.judicial_status,
        }, ensure_ascii=False)
        r = await chat_json(system, user, temperature=0.3)
        note = str(r.get("note") or r.get("analysis") or "").strip()
        return note if len(note) >= 10 else None
    except LLMError:
        logger.warning("AI disposal note failed, skip")
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("AI disposal note error: %s", e)
        return None


async def regenerate_report(report_id: int) -> None:
    """补充材料后重新生成报告（后台任务）。

    读取报告对应债权 + 现有补充材料 → 重新跑尽调 → 更新 report.content（version+1），
    并在 report_versions 表留存上一版本快照。
    """
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        report = db.get(Report, report_id)
        if report is None:
            return
        claim = db.get(Claim, report.claim_id)
        if claim is None:
            return
        task = db.get(Task, report.task_id)

        # 生成前先存档当前版本快照
        if report.content:
            db.add(ReportVersion(
                report_id=report.id,
                version=report.version or 1,
                content=report.content,
                source="ai",
            ))

        progress = NodeProgress(report.task_id, db, lambda *a: None)  # 静默进度
        content = await build_report_content(claim, progress)

        # 补充信息合并进报告：文件材料 + 用户补充文字
        supplements = json.loads(report.supplements) if report.supplements else []
        if supplements:
            content["supplements"] = supplements
            notes = [s["text"] for s in supplements if s.get("type") == "note" and s.get("text")]
            file_count = sum(1 for s in supplements if s.get("type") != "note")
            # 新增"补充信息"章节（用户补充的文字 + 上传材料清单）
            content["sections"]["supplement_info"] = {
                "user_notes": notes,
                "file_count": file_count,
                "summary": "用户补充信息已纳入本次分析" if (notes or file_count) else None,
            }
            content["sections"]["legal"]["supplement_note"] = (
                f"已上传补充材料 {file_count} 份" + (f"，补充文字 {len(notes)} 条" if notes else "") + "，请结合补充信息核实报告数据"
            )
            # 摘要核心逻辑追加一条：体现补充信息已纳入
            if notes:
                logic = content["sections"]["summary"].get("core_logic") or []
                logic.append(f"用户补充信息已纳入分析（{len(notes)} 条补充文字）")
                content["sections"]["summary"]["core_logic"] = logic

        report.content = json.dumps(content, ensure_ascii=False)
        report.version = (report.version or 1) + 1
        report.pdf_path = None  # 旧 PDF 失效
        if task:
            task.status = "done"
        db.commit()
        logger.info("report %s regenerated to v%s", report_id, report.version)
    except Exception as e:  # noqa: BLE001
        logger.exception("regenerate report %s failed", report_id)
        db.rollback()
    finally:
        db.close()


async def run_task_due_diligence(task_id: int, progress_cb: Callable[[int, str, int], None]) -> None:
    """任务级尽调编排：对任务内每个债权顺序执行（后台任务入口，独立 Session）"""
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return
        task.status = "running"
        db.commit()

        progress = NodeProgress(task_id, db, progress_cb)
        claim_ids = json.loads(task.claim_ids or "[]")

        # 创建子任务记录（task_items）
        items: dict[int, TaskItem] = {}
        for claim_id in claim_ids:
            item = TaskItem(task_id=task.id, claim_id=claim_id, status="pending")
            db.add(item)
            db.flush()
            items[claim_id] = item
        db.commit()

        for claim_id in claim_ids:
            claim = db.get(Claim, claim_id)
            if claim is None:
                continue
            try:
                content = await build_report_content(claim, progress)
                report = Report(task_id=task.id, claim_id=claim.id, version=1, content=json.dumps(content, ensure_ascii=False))
                db.add(report)
                db.flush()
                # 报告首版快照（v1）
                db.add(ReportVersion(report_id=report.id, version=1, content=report.content, source="ai"))
                # 用量记账（LLM 综合分析一次）
                record_usage(
                    db, user_id=task.user_id, task_id=task.id,
                    provider="deepseek", action="diligence_analyze",
                    cost_estimate=0, detail={"claim_id": claim.id},
                )
                if claim_id in items:
                    items[claim_id].status = "success"
                    items[claim_id].finished_at = datetime.now()
            except Exception as e:  # noqa: BLE001
                logger.exception("claim %s diligence failed", claim_id)
                if claim_id in items:
                    items[claim_id].status = "failed"
                    items[claim_id].error = str(e)
            db.commit()
        # 成功：立即提交 done 状态（否则 finally 的 rollback 会回滚）
        task.status = "done"
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("task %s failed", task_id)
        db.rollback()
        task = db.get(Task, task_id)
        if task:
            task.status = "failed"
            task.error = str(e)
            db.commit()
    finally:
        # 补进度与完成时间（不改变 status）
        task = db.get(Task, task_id)
        if task:
            task.progress = 100
            task.finished_at = datetime.now()
            db.commit()
        db.close()
