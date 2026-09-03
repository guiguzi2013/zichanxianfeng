"""债权路由：三种输入通道 + CRUD"""
import json

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, User
from ..schemas.claim import ClaimOut, ClaimUpdate, ImportLinkRequest, ImportTextRequest
from ..schemas.common import ApiResponse, err, ok
from ..services.excel_parser import parse_excel
from ..services.extractor import evaluate_completeness, extract_from_excel_row, extract_from_text
from ..services.llm import LLMError
from .deps import get_current_user

router = APIRouter(prefix="/claims", tags=["claims"])


def _claim_to_out(claim: Claim) -> ClaimOut:
    """ORM → Pydantic。missing_fields/extra_fields 在 DB 里是 JSON 字符串，
    需先解析为 list/dict 再校验（否则 Pydantic 类型不匹配报 500）。"""
    data = {
        "id": claim.id,
        "source_type": claim.source_type,
        "debtor_name": claim.debtor_name,
        "principal_cents": claim.principal_cents,
        "interest_cents": claim.interest_cents,
        "fees_cents": claim.fees_cents,
        "guaranty_type": claim.guaranty_type,
        "guarantor": claim.guarantor,
        "collateral": claim.collateral,
        "judicial_status": claim.judicial_status,
        "listing_price_cents": claim.listing_price_cents,
        "deadline": claim.deadline,
        "debtor_type": claim.debtor_type,
        "completeness": claim.completeness,
        "missing_fields": json.loads(claim.missing_fields) if claim.missing_fields else None,
        "extra_fields": json.loads(claim.extra_fields) if claim.extra_fields else None,
    }
    return ClaimOut(**data)


def _save_claims(db: Session, user: User, claims_fields: list[dict], source_type: str, source_raw: str | None) -> list[Claim]:
    saved = []
    for f in claims_fields:
        extra: dict = {}
        if f.get("extra_notes"):
            extra["extra_notes"] = f["extra_notes"]
        if f.get("synthesized_description"):
            extra["description"] = f["synthesized_description"]
        # 扩展字段（抵押人/类型/地区/批次/贷款行/查封/计息日等）
        if f.get("extra_fields") and isinstance(f["extra_fields"], dict):
            for k, v in f["extra_fields"].items():
                if v not in (None, ""):
                    extra[k] = v
        claim = Claim(
            user_id=user.id,
            source_type=source_type,
            source_raw=source_raw,
            debtor_name=f.get("debtor_name"),
            principal_cents=f.get("principal_cents"),
            interest_cents=f.get("interest_cents"),
            fees_cents=f.get("fees_cents"),
            guaranty_type=f.get("guaranty_type"),
            guarantor=f.get("guarantor"),
            collateral=f.get("collateral"),
            judicial_status=f.get("judicial_status"),
            listing_price_cents=f.get("listing_price_cents"),
            deadline=f.get("deadline"),
            debtor_type=f.get("debtor_type"),
            completeness=f.get("completeness"),
            missing_fields=json.dumps(f.get("missing_fields", []), ensure_ascii=False),
            extra_fields=json.dumps(extra, ensure_ascii=False) if extra else None,
        )
        db.add(claim)
        saved.append(claim)
    db.commit()
    for c in saved:
        db.refresh(c)
    return saved


@router.post("/import-text", response_model=ApiResponse)
async def import_text(req: ImportTextRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        fields = await extract_from_text(req.text)
    except LLMError as e:
        raise err(str(e))
    # 批量粘贴去重：同名债务人只保留第一条（用户确认：剔除重复，其余继续）
    seen: set[str] = set()
    dedup_fields = []
    for f in fields:
        from ..services.duplicate_check import _norm_name
        key = _norm_name(f.get("debtor_name"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        dedup_fields.append(f)
    claims = _save_claims(db, user, dedup_fields, "text", req.text)
    from ..services.input_quality import analyze_claims, analyze_text

    warnings = analyze_text(req.text) + analyze_claims(dedup_fields)
    # 重复检测（与历史记录/同批）
    from ..services.duplicate_check import detect_duplicates
    dup = detect_duplicates(db, user.id, [_claim_to_out(c).model_dump() for c in claims])
    return ok({
        "claims": [_claim_to_out(c).model_dump() for c in claims],
        "input_warnings": warnings,
        "dedup": {"removed": len(fields) - len(dedup_fields), **dup},
    })


@router.post("/import-link", response_model=ApiResponse)
async def import_link(req: ImportLinkRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from ..scrapers.registry import fetch_url_text
    from ..services.extractor import extract_from_text

    result = await fetch_url_text(req.url)
    if not result.success:
        raise err(result.note)
    try:
        fields = await extract_from_text(result.text)
    except LLMError as e:
        raise err(f"页面已抓取但提取失败：{e}")
    # 批量去重（同名只保留第一条）
    from ..services.duplicate_check import _norm_name
    seen: set[str] = set()
    dedup_fields = []
    for f in fields:
        key = _norm_name(f.get("debtor_name"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        dedup_fields.append(f)
    claims = _save_claims(db, user, dedup_fields, "link", result.text[:2000])
    from ..services.input_quality import analyze_claims, analyze_text

    warnings = analyze_text(result.text) + analyze_claims(dedup_fields)
    from ..services.duplicate_check import detect_duplicates
    dup = detect_duplicates(db, user.id, [_claim_to_out(c).model_dump() for c in claims])
    return ok({
        "claims": [_claim_to_out(c).model_dump() for c in claims],
        "scrape_note": result.note,
        "input_warnings": warnings,
        "dedup": {"removed": len(fields) - len(dedup_fields), **dup},
    })


class ImportPackageRequest(BaseModel):
    """资产包拆分导入：详情页"一键尽调"对多户资产包按表格拆分为多条债权（2026-09-02 用户确认）"""
    headers: list[str]
    rows: list[list]
    title: str = ""
    source_url: str = ""


@router.post("/import-package", response_model=ApiResponse)
async def import_package(req: ImportPackageRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """资产包表格(announce_table)按户拆分 → 多条 claim。

    规则（用户确认 2026-09-02）：
    - 包中任意一条资产满足条件即可发起尽调；到"信息预处理确认"页让用户勾选哪条（符合条件的可选）
    - 每户独立：债务人/本金/利息/抵押物(担保情况列)，跳过合计/总计/小计行
    - 字段不足的户照常生成（完整度标红，PreviewPage 禁勾选），不编造
    """
    from ..services.extractor import parse_amount_to_cents as _pac
    from ..services.extractor import clean_empty as _ce
    from ..scrapers.text_extract import (
        classify_collateral as _cc,
        extract_guarantors_from_text as _extract_guarantors_from_text,
        extract_property_metrics as _extract_property_metrics,
    )

    headers = [str(h or "").strip() for h in req.headers]

    def _col(*keys):
        for i, h in enumerate(headers):
            if any(k in h for k in keys):
                return i
        return None

    d_i = _col("债务人", "借款企业", "借款人", "单位名称", "企业名称", "项目")
    p_i = _col("本金余额", "贷款本金", "本金", "债权本金")
    i_i = _col("结欠利息", "利息余额", "利息", "重组收益")
    t_i = _col("债权总额", "债权合计", "本息合计", "合计金额", "转让标的额", "合计")
    g_i = _col("担保情况", "担保措施", "抵押情况", "抵质押", "保证情况", "担保", "抵押")
    r_i = _col("序号", "编号")

    fields_list: list[dict] = []
    for row in req.rows:
        if not row or not any(str(c or "").strip() for c in row):
            continue
        # 跳过 合计/总计/小计 行（首列可能是空、合计在第2列，故查前2列）
        if any(k in str(c or "").replace(" ", "").replace("\u3000", "") for c in row[:2]
               for k in ("合计", "总计", "小计")):
            continue
        if d_i is not None and len(row) > d_i and str(row[d_i]).strip() in ("债务人", "债务人名称"):
            continue
        debtor = _ce(row[d_i]) if d_i is not None and len(row) > d_i else None
        if not debtor:
            continue
        principal = _pac(str(row[p_i])) if p_i is not None and len(row) > p_i else None
        interest = _pac(str(row[i_i])) if i_i is not None and len(row) > i_i else None
        collateral = _ce(row[g_i]) if g_i is not None and len(row) > g_i else None
        # 担保类型识别（抵押/保证/质押）
        gt_parts = []
        for kw, label in (("抵押", "抵押"), ("保证", "保证"), ("质押", "质押")):
            if collateral and kw in collateral and label not in gt_parts:
                gt_parts.append(label)
        guaranty_type = "、".join(gt_parts) if gt_parts else None
        # 保证人（从担保描述提取）
        guarantor = _extract_guarantors_from_text(collateral or "")
        extra = {}
        ctype = _cc(collateral or "")
        if ctype:
            extra["collateral_type"] = ctype
        # 2026-09-02 自动预填：从抵押物描述提取 面积/建成年份/结构（已知信息填入对应位置）
        extra.update(_extract_property_metrics(collateral or ""))
        if req.title:
            import re as _re
            mb = _re.search(r'【([\u4e00-\u9fa5]{2,8})】', req.title)
            if mb:
                extra["region"] = mb.group(1)
        fields = {
            "debtor_name": debtor,
            "debtor_type": None,
            "principal_cents": principal,
            "interest_cents": interest,
            "fees_cents": None,
            "guaranty_type": guaranty_type,
            "guarantor": guarantor,
            "collateral": collateral,
            "judicial_status": None,
            "listing_price_cents": None,
            "deadline": None,
            "extra_notes": None,
            "extra_fields": extra,
            "batch": req.title[:50],
        }
        from ..services.extractor import evaluate_completeness as _ev
        _level, missing = _ev(fields)
        fields["completeness"] = _level
        fields["missing_fields"] = missing
        fields_list.append(fields)

    if not fields_list:
        raise err("未能从表格中拆分出有效债权（缺少债务人/本金/抵押物列）")
    claims = _save_claims(db, user, fields_list, "package", f"{req.title}\n{req.source_url}")
    return ok({
        "claims": [_claim_to_out(c).model_dump() for c in claims],
        "split_count": len(fields_list),
    })


@router.post("/import-excel", response_model=ApiResponse)
async def import_excel(file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    content = await file.read()
    try:
        rows, mapping, unmapped = parse_excel(content, file.filename or "upload.xlsx")
    except Exception as e:  # noqa: BLE001
        raise err(f"Excel 解析失败：{e}")

    if not rows:
        raise err("未解析到有效数据行，请检查表头格式")

    # 文件重复检测（同名 + 指纹）：提醒已上传过
    from ..services.file_validate import compute_fingerprint
    from ..services.duplicate_check import check_file_duplicate

    filename = file.filename or "upload.xlsx"
    fingerprint = compute_fingerprint(filename, len(content), getattr(file, "last_modified", None))
    file_dup = check_file_duplicate(db, user.id, filename, fingerprint)

    # 表内去重：同名债务人只保留第一条（用户确认：同表重复只能勾选一个）
    from ..services.duplicate_check import _norm_name
    seen: set[str] = set()
    dedup_fields = []
    for f in (extract_from_excel_row(r) for r in rows):
        key = _norm_name(f.get("debtor_name"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        dedup_fields.append(f)

    # 规范映射直接转 claim；缺字段（如担保类型/司法状态）保持 null，由完整度标识
    claims = _save_claims(db, user, dedup_fields, "excel", filename)

    # 补写 source_raw + 文件指纹（供重复文件检测）
    for c in claims:
        c.source_raw = filename
        import json as _json
        extra = {}
        try:
            extra = _json.loads(c.extra_fields) if c.extra_fields else {}
        except Exception:
            extra = {}
        extra["file_fingerprint"] = fingerprint
        c.extra_fields = _json.dumps(extra, ensure_ascii=False)
    db.commit()

    from ..services.input_quality import analyze_claims, analyze_excel_rows

    warnings = analyze_excel_rows(rows) + analyze_claims(dedup_fields)
    from ..services.duplicate_check import detect_duplicates
    dup = detect_duplicates(db, user.id, [_claim_to_out(c).model_dump() for c in claims])
    return ok({
        "claims": [_claim_to_out(c).model_dump() for c in claims],
        "column_mapping": mapping,
        "unmapped_columns": unmapped,
        "input_warnings": warnings,
        "dedup": {"removed": len(rows) - len(dedup_fields), "file_duplicate": file_dup, **dup},
    })


@router.put("/{claim_id}", response_model=ApiResponse)
def update_claim(claim_id: int, req: ClaimUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    claim = db.get(Claim, claim_id)
    if claim is None or claim.user_id != user.id:
        raise err("记录不存在", http_status=status.HTTP_404_NOT_FOUND)
    data = req.model_dump(exclude_unset=True)
    # extra_fields 需要合并存储（dict → JSON 字符串），并剔除空值
    if "extra_fields" in data:
        extra_fields = data.pop("extra_fields") or {}
        existing = {}
        try:
            existing = json.loads(claim.extra_fields) if claim.extra_fields else {}
        except Exception:
            existing = {}
        merged = {**existing, **{k: v for k, v in extra_fields.items() if v not in (None, "")}}
        merged["user_edited"] = True  # 用户编辑过标记（用于"已尽调债权修改后重新尽调"）
        claim.extra_fields = json.dumps(merged, ensure_ascii=False) if merged else None
    for field, value in data.items():
        setattr(claim, field, value)
    # 重算完整度（关键字段规则：债务人/本金/抵押物；extra_fields 供抵押物合格判定用）
    extra_for_comp = {}
    try:
        extra_for_comp = json.loads(claim.extra_fields) if claim.extra_fields else {}
    except Exception:
        extra_for_comp = {}
    completeness, missing = evaluate_completeness({
        "debtor_name": claim.debtor_name,
        "principal_cents": claim.principal_cents,
        "collateral": claim.collateral,
        "interest_cents": claim.interest_cents,
        "guaranty_type": claim.guaranty_type,
        "judicial_status": claim.judicial_status,
        "extra_fields": extra_for_comp,
    })
    claim.completeness = completeness
    claim.missing_fields = json.dumps(missing, ensure_ascii=False)
    db.commit()
    db.refresh(claim)
    return ok(_claim_to_out(claim).model_dump(), "已更新")


@router.post("/check-existed", response_model=ApiResponse)
def check_existed_claims(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """勾选尽调前检查：债务人是否已有任务/报告（已尽调）。返回 [{debtor_name, task_id, report_id}]。
    前端据此阻止重复尽调并提示跳转任务列表。"""
    from sqlalchemy import select
    from ..models import Report, Task
    from .tasks import _task_source_ids
    from ..services.duplicate_check import _norm_name

    names = [str(n).strip() for n in (payload.get("debtor_names") or []) if str(n).strip()]
    if not names:
        return ok({"existed": []})
    # 用户全部报告（claim_id -> 最新报告所属任务）
    all_reports = db.scalars(
        select(Report).join(Task).where(Task.user_id == user.id)
    ).all()
    claim_report: dict[int, tuple[int, int]] = {}
    for rp in sorted(all_reports, key=lambda x: x.created_at or __import__("datetime").datetime.min, reverse=True):
        if rp.claim_id not in claim_report:
            claim_report[rp.claim_id] = (rp.task_id, rp.id)
    # 用户全部债权（含 deleted？只查有效）
    claims = db.scalars(select(Claim).where(Claim.user_id == user.id)).all()
    existed = []
    for n in names:
        key = _norm_name(n)
        if not key:
            continue
        for c in claims:
            if _norm_name(c.debtor_name) == key or (_norm_name(c.debtor_name) and key in _norm_name(c.debtor_name) or _norm_name(c.debtor_name) in key):
                loc = claim_report.get(c.id)
                if loc:
                    existed.append({"debtor_name": n, "task_id": loc[0], "report_id": loc[1]})
                    break
    return ok({"existed": existed})


@router.get("", response_model=ApiResponse)
def list_claims(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    claims = db.scalars(select(Claim).where(Claim.user_id == user.id).order_by(Claim.id.desc())).all()
    return ok({"claims": [_claim_to_out(c).model_dump() for c in claims]})


@router.delete("/{claim_id}", response_model=ApiResponse)
def delete_claim(claim_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    claim = db.get(Claim, claim_id)
    if claim is None or claim.user_id != user.id:
        raise err("记录不存在", http_status=status.HTTP_404_NOT_FOUND)
    db.delete(claim)
    db.commit()
    return ok(None, "已删除")
