"""财产线索辅助接口：判决书主体识别 + 名称校验

POST /api/clues/parse-judgment  上传判决书(Word/PDF/TXT) → 自动识别债务人/保证人/关联人
POST /api/clues/verify-names    名称规则校验（免费离线，避免把错误名称发给企查查浪费积分）
"""
import json
import logging
import os
import re

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..schemas.common import ApiResponse, err, ok
from ..services.judgment_parser import extract_entities, verify_names
from ..services.supplement_parser import extract_text_from_file
from .deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clues", tags=["clues"])
settings = get_settings()

ALLOWED = {".docx", ".doc", ".pdf", ".txt", ".md", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@router.post("/parse-judgment", response_model=ApiResponse)
async def parse_judgment(files: list[UploadFile] = File(...)):
    """上传材料（判决书/裁定书/情况说明/尽调说明等，支持多文件、多页、图片），自动识别债务人/保证人/关联人"""
    if not files:
        raise err("请选择文件")
    if len(files) > 20:
        raise err("文件过多（最多 20 个）")

    all_text: list[str] = []
    for file in files:
        filename = file.filename or "upload"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED:
            raise err(f"不支持的文件格式 {ext or '(无扩展名)'}，支持 Word/PDF/TXT/图片(jpg/png)")

        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise err(f"{filename} 文件过大（超过 10MB）")

        # 保存临时文件再解析（复用补充材料解析器）
        os.makedirs(settings.upload_dir, exist_ok=True)
        safe = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", filename)
        path = os.path.join(settings.upload_dir, f"judgment_{safe}")
        with open(path, "wb") as fp:
            fp.write(data)
        try:
            text = extract_text_from_file(path, ext.lstrip(".")) or ""
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if text and len(text.strip()) >= 5:
            all_text.append(text)

    text = "\n".join(all_text)
    if not text or len(text.strip()) < 10:
        raise err("未能从文件中提取到文本（图片可能过糊/倾斜，或为扫描件 PDF，建议用清晰图片重试）")

    result = await extract_entities(text)
    entities = result["entities"]
    if not entities:
        raise err("未识别到主体，请检查文件内容或尝试文本输入")

    # 名称规则校验（识别结果先自查一遍）
    checks = verify_names([e["name"] for e in entities])
    check_map = {c["name"]: c for c in checks}
    for e in entities:
        c = check_map.get(e["name"])
        e["warnings"] = c["warnings"] if c else []
        e["ok"] = bool(c and c["ok"])

    return ok({
        "entities": entities,
        "method": result["method"],
        "note": result["note"],
        "char_count": len(text),
        "file_count": len(files),
    }, f"识别到 {len(entities)} 个主体（{result['method']}）")


class VerifyNamesRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=50)


@router.post("/verify-names", response_model=ApiResponse)
def verify_names_api(req: VerifyNamesRequest):
    """规则校验一批名称（免费离线）：返回每个名称的 ok 与告警"""
    return ok({"results": verify_names([n.strip() for n in req.names if n.strip()])})


class CaseReportEntity(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(default="相关主体", max_length=20)


class ResolveNameRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)


def _name_variants(name: str) -> list[str]:
    """生成常见名称变体（曾用名/现名互相转换的常见形态），命中即停，最多 6 个"""
    vs = [name]
    reps = [
        ("股份有限公司", "有限公司"),
        ("有限公司", "股份有限公司"),
        ("集团", ""),
        ("有限责任公司", "有限公司"),
        ("有限公司", "有限责任公司"),
    ]
    for old, new in reps:
        if old in name:
            vs.append(name.replace(old, new, 1))
    seen: set[str] = set()
    out: list[str] = []
    for v in vs:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out[:6]


@router.post("/resolve-name", response_model=ApiResponse)
async def resolve_name(req: ResolveNameRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """名称变体解析：材料中的名称查无此名时，依次尝试常见变体（缓存优先），找到现用名即停。

    每个变体约 8 积分（轻量模式，未缓存时），命中即停，最多 6 个变体。
    优化：先对所有变体做一次缓存扫描（含负缓存跳过），任何变体命中缓存即 0 积分返回。
    """
    from ..api.qcc import cache_get, neg_cache_get, query_property_clues

    name = req.name.strip()
    variants = _name_variants(name)

    def _reg_name(data: dict) -> str | None:
        reg = data.get("biz", {}).get("get_company_registration_info") or {}
        if reg.get("ok"):
            rn = (reg.get("data") or {}).get("企业名称")
            if rn:
                return rn
        return None

    # 第一遍：全部变体先查缓存，命中即停（0 新增调用）
    for v in variants:
        cached = cache_get(f"clues:{v}") or cache_get(v)
        if cached:
            rn = _reg_name(cached)
            if rn:
                _record_name_resolve(db, user.id, name, rn, v, 0)
                return ok({
                    "matched_name": v,
                    "registered_name": rn,
                    "data": cached,
                    "tried": [{"name": v, "used_cache": True}],
                    "calls_used": 0,
                }, f"已找到匹配的现用名称：{rn}（缓存命中，新增 0 次调用）")

    # 第二遍：负缓存（1h 内查过且查无此名）直接跳过，其余变体按序实查，命中即停
    tried: list[dict] = []
    calls_used = 0
    for v in variants:
        if neg_cache_get(v):
            tried.append({"name": v, "used_cache": False, "negative": True})
            continue
        data = await query_property_clues(v)
        calls_used += 1
        rn = _reg_name(data)
        if rn:
            _record_name_resolve(db, user.id, name, rn, v, calls_used)
            return ok({
                "matched_name": v,
                "registered_name": rn,
                "data": data,
                "tried": tried + [{"name": v, "used_cache": False}],
                "calls_used": calls_used,
            }, f"已找到匹配的现用名称：{rn}（尝试 {len(tried) + 1} 个变体，新增 {calls_used} 次调用）")
        tried.append({"name": v, "used_cache": False})

    return ok({"matched_name": None, "tried": tried, "calls_used": calls_used}, "尝试全部常见变体均未找到，请人工核对准确名称")


class DeepInvestigationRequest(BaseModel):
    company: str = Field(min_length=2, max_length=100)


@router.post("/deep-investigation", response_model=ApiResponse)
async def deep_investigation(req: DeepInvestigationRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """深度调查（付费进阶）：在财产线索基础上追加工商增量 + 司法因子明细，输出资产维度/变现难度/变现路径。

    积分：clues 缓存命中时只花增量（约 7 + 有记录因子数），未命中约 15-22；同企业 24h 内重复查询零新增。
    """
    from ..api.qcc import cache_get, deep_credit_estimate, neg_cache_get, query_deep_investigation
    from ..services.deep_investigation import build_deep_report

    company = req.company.strip()
    if neg_cache_get(company):
        return ok({
            "company": company,
            "matched": False,
            "reason": "该名称 1 小时内查过且查无此名（或企查查无有效数据），深度调查无法进行，请先核对准确工商名称（可用'名称变体解析'）。",
        }, "名称未确认，未消耗积分")

    # 若 clues 缓存已存且工商登记为空（名称与工商不符，name_ok=false），直接拦截，不再实查浪费积分
    clues_cached = cache_get(f"clues:{company}")
    if clues_cached:
        reg = clues_cached.get("biz", {}).get("get_company_registration_info") or {}
        reg_data = reg.get("data") if reg.get("ok") else None
        if not (reg_data and reg_data.get("企业名称")):
            return ok({
                "company": company,
                "matched": False,
                "reason": "该名称与工商登记不符（曾用名/简称等），深度调查无意义。请先'尝试名称变体解析'核对准确名称后再调查。",
            }, "名称与工商不符，未消耗积分")

    cached = cache_get(f"deep:{company}")
    if cached:
        report = build_deep_report(cached, calls_used=0)
        _record_clue_activity(db, user.id, company, report)
        _save_clue_report(db, user.id, "deep", f"深挖：{company}", [company], report)
        return ok({"company": company, "matched": True, "report": report, "cached": True}, "深度调查报告（缓存命中，新增 0 次调用）")

    # 预估积分（用于前端确认弹窗提示；实际消耗在查询后回填）
    base = cache_get(f"clues:{company}")
    scan_data = (base or {}).get("risk", {}).get("scan", {}).get("data") if base else None
    estimate = deep_credit_estimate(scan_data)

    try:
        deep = await query_deep_investigation(company)
    except Exception as e:
        logger.exception("deep investigation failed for %s", company)
        raise err(f"深度调查失败：{e}")

    reg_ok = bool((deep.get("base", {}).get("biz", {}).get("get_company_registration_info") or {}).get("ok"))
    if not reg_ok:
        return ok({
            "company": company,
            "matched": False,
            "reason": "未找到该企业的工商登记信息（可能名称有误/已变更），本次调用不保留，请用'名称变体解析'核对后再试。",
        }, "名称未确认，已消耗部分积分（查询失败不缓存）")

    report = build_deep_report(deep, calls_used=estimate)
    _record_clue_activity(db, user.id, company, report)
    _save_clue_report(db, user.id, "deep", f"深挖：{company}", [company], report)
    return ok({"company": company, "matched": True, "report": report, "cached": False, "estimate": estimate}, f"深度调查报告完成（预估消耗约 {estimate} 积分）")


def _record_clue_activity(db: Session, user_id: int, company: str, report: dict) -> None:
    """财产线索查询留痕（活动记录 kind=clue）"""
    try:
        from ..services.activity import add_activity

        summary = ""
        total = report.get("total_assets") if isinstance(report, dict) else None
        if isinstance(report, dict):
            assets = report.get("assets") or []
            found = sum(1 for a in assets if a.get("found"))
            total = len(assets)
            summary = f"资产维度 {found}/{total} 项有线索"
        add_activity(
            db, user_id, "clue",
            title=f"财产线索：{company}",
            summary=summary or "深度调查完成",
            detail={"company": company, "report_keys": list(report.keys()) if isinstance(report, dict) else None},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("clue activity record failed: %s", e)


def _save_clue_report(db: Session, user_id: int, report_type: str, title: str, subject_names: list[str], content: dict) -> None:
    """财产线索/深度调查报告落库（2026-09-01 用户确认：需留存，供管理后台查看与单条清缓存）"""
    try:
        from ..models import ClueReport

        db.add(ClueReport(
            user_id=user_id,
            report_type=report_type,  # case=综合分析 / deep=深度调查(深挖)
            title=title[:290],
            subject_names=json.dumps([n for n in subject_names if n], ensure_ascii=False),
            content=json.dumps(content, ensure_ascii=False, default=str),
        ))
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("clue report save failed: %s", e)
        db.rollback()


def _record_name_resolve(db: Session, user_id: int, input_name: str, matched: str, variant: str, calls_used: int) -> None:
    """名称变体解析留痕（活动记录 kind=clue）"""
    try:
        from ..services.activity import add_activity

        add_activity(
            db, user_id, "clue",
            title=f"名称解析：{input_name}",
            summary=f"匹配现用名：{matched}（新增 {calls_used} 次调用）",
            detail={"input": input_name, "matched": matched, "variant": variant, "calls_used": calls_used},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("name resolve activity record failed: %s", e)


class CaseReportRequest(BaseModel):
    entities: list[CaseReportEntity] = Field(min_length=1, max_length=50)


# 自然人名称启发式（与前端一致）：短名称且不带企业后缀
_PERSON_TAIL = ("公司", "集团", "中心", "银行", "支行", "分行", "事务所", "厂",
                "合作社", "工作室", "有限", "股份", "控股", "汽车")


def _is_person_name(name: str) -> bool:
    t = name.strip()
    if len(t) > 4:
        return False
    return not t.endswith(_PERSON_TAIL)


@router.post("/case-report", response_model=ApiResponse)
async def build_case_report_api(req: CaseReportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """综合分析报告：批量查询（缓存优先，自然人跳过企查查）并融合生成案件级追索报告（落库留存）"""
    from ..api.qcc import cache_get, query_property_clues
    from ..services.case_analyzer import build_case_report

    results: dict = {}
    new_calls = 0
    cached_hits = 0
    skipped_persons = 0

    for e in req.entities:
        name = e.name.strip()
        if not name:
            continue
        if _is_person_name(name):
            skipped_persons += 1
            continue  # 自然人跳过企查查（个人无企业数据），由前端交叉验证处理
        # 先查轻量缓存，再查全量缓存（全量含所需工具，结构兼容）
        cached = cache_get(f"clues:{name}") or cache_get(name)
        if cached:
            cached_hits += 1
            results[name] = cached
            continue
        try:
            r = await query_property_clues(name)
            results[name] = r
            new_calls += 1
        except Exception:  # noqa: BLE001
            logger.warning("case-report query failed: %s", name)

    report = build_case_report(
        [{"name": e.name.strip(), "role": e.role} for e in req.entities if e.name.strip()],
        results,
    )
    report["stats"] = {
        "new_calls": new_calls,
        "cached_hits": cached_hits,
        "skipped_persons": skipped_persons,
    }
    # 落库留存（2026-09-01 用户确认）：综合分析报告供管理后台查看/清缓存
    _save_clue_report(
        db, user.id, "case",
        f"财产线索综合分析（{len(req.entities)} 个主体）",
        [e.name.strip() for e in req.entities],
        report,
    )
    return ok(report, f"综合分析完成：新增调用 {new_calls} 次，缓存命中 {cached_hits} 次，自然人跳过 {skipped_persons} 人")


@router.post("/case-report-deep", response_model=ApiResponse)
async def build_case_report_deep_api(req: CaseReportRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """深度对比版综合分析报告：原版财产追踪 + 每家企业深度调查，输出对比结论（落库留存）。

    积分：原版部分缓存优先（同 case-report）；深度部分对每家非自然人企业跑 query_deep_investigation
    （clues 缓存命中时基底 0 新增，只花增量 7 + 有记录因子明细 ≈ 10-17 分/家）。
    """
    from ..api.qcc import cache_get, deep_credit_estimate, query_deep_investigation
    from ..services.case_analyzer import build_case_report
    from ..services.deep_investigation import build_deep_report

    entities = [{"name": e.name.strip(), "role": e.role} for e in req.entities if e.name.strip()]

    # ---- 1. 原版：财产追踪（与 /case-report 相同逻辑）----
    results: dict = {}
    new_calls = 0
    cached_hits = 0
    skipped_persons = 0
    for e in entities:
        name = e["name"]
        if _is_person_name(name):
            skipped_persons += 1
            continue
        cached = cache_get(f"clues:{name}") or cache_get(name)
        if cached:
            cached_hits += 1
            results[name] = cached
            continue
        try:
            r = await query_property_clues(name)
            results[name] = r
            new_calls += 1
        except Exception:  # noqa: BLE001
            logger.warning("case-report-deep standard query failed: %s", name)

    standard = build_case_report(entities, results)
    standard["stats"] = {"new_calls": new_calls, "cached_hits": cached_hits, "skipped_persons": skipped_persons}

    # ---- 2. 深度版：每家非自然人企业深度调查（缓存优先）----
    deep_reports: dict = {}
    deep_estimates: dict = {}
    deep_cached = 0
    deep_calls = 0
    for e in entities:
        name = e["name"]
        if _is_person_name(name):
            continue
        if not (results.get(name) or {}).get("name_ok", True):
            deep_reports[name] = {"matched": False, "reason": "名称与工商不符，跳过深度调查"}
            continue
        cached_deep = cache_get(f"deep:{name}")
        if cached_deep:
            deep_reports[name] = {"matched": True, "cached": True, "report": build_deep_report(cached_deep, calls_used=0)}
            deep_cached += 1
            deep_estimates[name] = 0
            continue
        base = cache_get(f"clues:{name}")
        scan_data = (base or {}).get("risk", {}).get("scan", {}).get("data") if base else None
        est = deep_credit_estimate(scan_data)
        deep_estimates[name] = est
        try:
            deep = await query_deep_investigation(name)
            reg_ok = bool((deep.get("base", {}).get("biz", {}).get("get_company_registration_info") or {}).get("ok"))
            if reg_ok:
                deep_reports[name] = {"matched": True, "cached": False, "estimate": est, "report": build_deep_report(deep, calls_used=est)}
                deep_calls += 1
            else:
                deep_reports[name] = {"matched": False, "reason": "未找到工商登记信息（名称可能不符），未保留结果"}
        except Exception:  # noqa: BLE001
            logger.warning("case-report-deep deep query failed: %s", name)
            deep_reports[name] = {"matched": False, "reason": "深度调查失败（企查查接口异常）"}

    # ---- 3. 对比结论：深度调查相比原版新增了哪些价值 ----
    diff_items: list[dict] = []
    for name, dr in deep_reports.items():
        if not dr.get("matched"):
            continue
        dims = dr.get("report", {}).get("dimensions") or []
        dim_names = [d["name"] for d in dims]
        # 原版能看到：对外投资/抵押/拍卖/风险因子（clue_count 覆盖）；深度新增：应收债权/询价评估/悬赏/司法因子明细/经营活跃度
        new_dims = [d for d in dims if d["name"] not in (
            "对外投资股权（存续/在业子公司）", "动产抵押", "土地抵押", "司法拍卖/处置资产")]
        if new_dims:
            diff_items.append({
                "name": name,
                "added": [d["name"] for d in new_dims],
                "summary": "；".join(d["summary"] for d in new_dims)[:200],
                "best_difficulty": min((d["difficulty"] for d in new_dims), default=""),
            })
    n_deep_matched = sum(1 for dr in deep_reports.values() if dr.get("matched"))
    n_deep_positive = sum(1 for d in diff_items if d.get("added"))
    if n_deep_positive == 0:
        deep_summary = "深度调查未发现原版之外的显著新增线索（各企业资产维度与原版覆盖一致），可暂不重复付费。"
    else:
        deep_summary = (
            f"深度调查在 {n_deep_positive}/{n_deep_matched} 家企业中发现原版之外的线索，"
            f"主要包括：{('、'.join(sorted({d for it in diff_items for d in it['added']}))[:120])} 等。"
            f"其中「对外应收债权/未来收入」若存在，是原版无法覆盖的追偿突破口，建议重点跟进。"
        )

    # 落库留存（2026-09-01 用户确认）：深度对比版综合分析报告供管理后台查看/清缓存
    _save_clue_report(
        db, user.id, "case",
        f"财产线索综合分析·深度版（{len(entities)} 个主体）",
        [e["name"] for e in entities],
        {
            "standard": standard,
            "deep": {
                "reports": deep_reports,
                "estimates": deep_estimates,
                "deep_cached": deep_cached,
                "deep_calls": deep_calls,
                "diff": diff_items,
                "summary": deep_summary,
            },
            "stats": {
                "standard": standard.get("stats", {}),
                "deep_cached": deep_cached,
                "deep_calls": deep_calls,
                "deep_estimate_total": sum(deep_estimates.values()),
            },
        },
    )
    return ok({
        "standard": standard,
        "deep": {
            "reports": deep_reports,
            "estimates": deep_estimates,
            "deep_cached": deep_cached,
            "deep_calls": deep_calls,
            "diff": diff_items,
            "summary": deep_summary,
        },
        "stats": {
            "standard": standard.get("stats", {}),
            "deep_cached": deep_cached,
            "deep_calls": deep_calls,
            "deep_estimate_total": sum(deep_estimates.values()),
        },
    }, f"深度对比报告完成：原版新增 {new_calls} 次调用；深度调查 {deep_cached} 家缓存命中 + {deep_calls} 家新查（预估约 {sum(deep_estimates.values())} 积分）")
