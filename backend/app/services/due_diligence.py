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
    return {
        "debtor_name": claim.debtor_name,
        "debtor_type": claim.debtor_type or "enterprise",
        "principal_cents": claim.principal_cents,
        "interest_cents": claim.interest_cents,
        "guaranty_type": claim.guaranty_type,
        "guarantor": claim.guarantor,
        "collateral": claim.collateral,
        "judicial_status": claim.judicial_status,
        "listing_price_cents": claim.listing_price_cents,
    }


async def _node2_judicial(claim: Claim) -> dict:
    """节点② 工商/司法风险

    配置企查查 QCC_TOKEN 时优先走企查查（工商登记 + 股东 + 高危风险因子），
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
                if shr.get("ok"):
                    result["shareholders"] = shr.get("data")
                else:
                    result["shareholders"] = {"note": shr.get("error") or "股东信息查询失败"}

                scan = q.get("risk", {}).get("scan") or {}
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
            result["source_status"]["qcc"] = "查询失败，已回退免费源"

    # ---- 回退：免费源 ----
    judicial = get_judicial_source()

    if claim.debtor_type == "enterprise":
        ent = get_enterprise_source()
        basic = await ent.get_basic_info(claim.debtor_name or "")
        result["basic"] = basic.data if basic.success else None
        result["source_status"]["gsxt"] = "ok" if basic.success else basic.note

    exec_r = await judicial.search_execution(claim.debtor_name or "")
    dishon_r = await judicial.search_dishonest(claim.debtor_name or "")
    result["judicial_risk"] = {
        "execution_found": exec_r.success,
        "dishonest_found": dishon_r.success,
        "source": judicial.name,
        "note": exec_r.note or dishon_r.note or "",
        "need_manual_verify": not (exec_r.success and dishon_r.success),
    }
    result["source_status"]["zxgk"] = "ok" if (exec_r.success or dishon_r.success) else "需人工核实"
    return result


async def _node3_legal(claim: Claim) -> dict:
    """节点③ 法律检索（P0 尽力而为，降级标注）"""
    return {
        "documents": {
            "found": False,
            "not_found_note": "未检索到相关判决书（免费渠道反爬限制），本息为估算，建议上传补充材料",
        },
        "statutes_note": "法规依据由AI生成，需人工核验",
    }


async def _node4_valuation(claim: Claim) -> dict:
    """节点④ 抵押物估值（P0 无外部价格源时降级）"""
    if not claim.collateral:
        return {"present": False, "note": "无抵押物信息"}
    return {
        "present": True,
        "items": [{
            "description": claim.collateral,
            "valuation": {
                "conservative": None, "neutral": None, "optimistic": None,
                "data_insufficient": True,
            },
            "coverage": None,
            "liquidity": "数据不足，建议专业评估机构出具正式评估报告",
        }],
    }


def _node5_interest(claim: Claim) -> dict:
    """节点⑤ 本息计算（纯代码）"""
    principal = claim.principal_cents
    if principal is None:
        return {"mode": "none", "note": "本金缺失，无法计算"}
    start = date(2020, 5, 1)  # P0 默认起算日，后续由判决书/尽调数据确定
    result = calculate_interest(principal, start, date.today(), has_judgment=False)
    return {
        "mode": result.calculation_mode,
        "items": result.items,
        "total_cents": result.total_cents,
        "basis_note": result.basis_note,
    }


async def _node6_summary(claim: Claim, nodes: dict) -> dict:
    """节点⑥ LLM 综合分析（P0 无 API Key 时生成降级摘要）"""
    if not settings.deepseek_api_key:
        return _fallback_summary(claim, nodes)
    system = """你是不良资产尽调分析专家。基于提供的尽调数据，生成报告摘要与风控评估。
要求：
1. 严格按 JSON 输出：{"summary": {"rating": "★~★★★★★", "core_logic": [..], "suggested_buy_ratio": ".."},
   "risk": {"favorable": [..], "risk": [..], "need_manual_verify": [..]}}
2. 所有结论必须来自给定数据，数据缺失标"需人工核实"，禁止编造。
3. 评级规则：★★★★★ 抵押物覆盖>150%且司法清晰；★★★★ 100%~150%；★★★ 70%~100%；★★ <70%或司法风险高；★ 重大不确定。"""
    user = json.dumps({"claim": _build_claim_dict(claim), "nodes": nodes}, ensure_ascii=False)
    try:
        return await chat_json(system, user, temperature=0.3)
    except LLMError:
        logger.warning("node6 LLM failed, fallback summary")
        return _fallback_summary(claim, nodes)


def _fallback_summary(claim: Claim, nodes: dict) -> dict:
    """无 API Key / LLM 失败时的降级摘要"""
    principal_wan = (claim.principal_cents or 0) / 100 / 10000
    principal_text = f"{principal_wan:.2f}万元" if claim.principal_cents else "未知"
    return {
        "summary": {
            "rating": "★★★",
            "core_logic": [f"债务人：{claim.debtor_name or '未知'}；本金：{principal_text}（详见报告）"],
            "suggested_buy_ratio": "需人工核实",
        },
        "risk": {
            "favorable": ["抵押物信息已录入（待估值）"] if claim.collateral else [],
            "risk": ["司法状态需人工核实"],
            "need_manual_verify": ["本息计算基准日", "判决书", "抵押物估值", "税费成本"],
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
            "data_sources": ["国家企业信用信息公示系统", "中国执行信息公开网", "用户提供"],
            "version": 1,
            "report_style": "full" if (claim.debtor_type or "enterprise") == "enterprise" else "simplified",
        },
        "sections": {
            "summary": summary.get("summary", {}),
            "reminders": {"items": [r.__dict__ for r in reminders], "matched_count": len(reminders)},
            "claim_basic": {
                "basic_table": _build_claim_dict(claim),
                "interest_detail": nodes["interest"],
            },
            "debtor": nodes["debtor"],
            "guarantor": {"present": bool(claim.guarantor), "note": "担保人详情需人工核实" if claim.guarantor else None},
            "collateral": nodes["collateral"],
            "legal": nodes["legal"],
            "risk": summary.get("risk", {}),
            "disposal": _build_disposal_section(claim, nodes),
        },
        "disclaimer": "本报告由资产先锋平台基于公开信息和AI分析自动生成，仅供参考，不构成投资建议。报告中的估值基于公开市场数据粗估，不替代专业评估机构出具的正式评估报告。投资决策请结合专业律师意见和实地尽调结果。",
    }
    return content


def _build_disposal_section(claim: Claim, nodes: dict) -> dict:
    """处置建议版块：追索行动方案（中心思想：追回钱款，告诉用户怎么做）。"""
    from .recovery_planner import build_recovery_plan

    plan = build_recovery_plan(claim, nodes)
    return {
        "plan": plan,
        "note": "以上行动方案由系统根据尽调数据自动生成，供参考；具体诉讼/保全策略请结合专业律师意见。",
    }


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

        # 补充材料信息合并进报告
        supplements = json.loads(report.supplements) if report.supplements else []
        if supplements:
            content["supplements"] = supplements
            content["sections"]["legal"]["supplement_note"] = (
                f"已上传补充材料 {len(supplements)} 份，请结合材料内容核实报告数据"
            )

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
