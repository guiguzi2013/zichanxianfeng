"""债权路由：输入通道（文本/Excel/材料文档）+ CRUD"""
import json
import os
import re

from fastapi import APIRouter, Depends, File, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, User
from ..schemas.claim import ClaimOut, ClaimUpdate, ImportTextRequest
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


# ---------- 材料识别任务（2026-09-05：改任务制，避免大文件/OCR 长等待时前端无反馈） ----------
# POST /claims/import-doc 立即返回 job_id；前端轮询 GET /claims/import-doc/{job_id}/status。
# 多文件文本提取并行（asyncio.to_thread），OCR/PDF 解析不再串行阻塞。
import asyncio as _asyncio
import uuid as _uuid
import time as _time

DOC_JOBS: dict[str, dict] = {}  # job_id -> {status, progress, label, result?, error?, created_at}
_JOB_LOCKS: dict[str, object] = {}  # job_id -> threading.Lock（不进 DOC_JOBS，防序列化报错）


def _doc_job_cleanup() -> None:
    """清理超过 30 分钟的旧任务记录（防内存膨胀）"""
    now = _time.time()
    stale = [k for k, v in DOC_JOBS.items() if now - v.get("created_at", 0) > 1800]
    for k in stale:
        DOC_JOBS.pop(k, None)
        _JOB_LOCKS.pop(k, None)


async def _run_doc_job(job_id: str, user_id: int, paths: list[tuple[str, str, str]]) -> None:
    """后台执行：逐文件提取文本（并行）→ 合并 → LLM 识别 → 落库。paths: (safe_name, ext, abs_path)
    进度反馈：file_states = [{name, status, percent}]，供前端逐文件进度条。
    2026-09-05：锁用模块级 _JOB_LOCKS 管理，不存进 DOC_JOBS（避免 status 端点序列化 Lock 报 500）。"""
    from ..services.supplement_parser import extract_text_from_file
    from ..services.duplicate_check import _norm_name, detect_duplicates
    from ..services.input_quality import analyze_claims, analyze_text

    import threading
    lock = threading.Lock()
    _JOB_LOCKS[job_id] = lock

    total = len(paths)
    file_parts: list[str] = []
    names: list[str] = []
    # 进度状态存 DOC_JOBS 内，配合模块级锁原位更新（多线程不再互相覆盖）
    DOC_JOBS[job_id] = {**DOC_JOBS[job_id],
                        "file_states": [{"name": p[0], "status": "未开始", "percent": 0} for p in paths]}

    def _set_file(i: int, **kw) -> None:
        with lock:
            DOC_JOBS[job_id]["file_states"][i] = {**DOC_JOBS[job_id]["file_states"][i], **kw}

    try:
        # 1) 并行提取全文（OCR/PDF 解析放线程池）；每份通过进度回调更新 percent（前端逐文件进度条）
        def _one(i):
            safe, ext, p = paths[i]
            _set_file(i, status="读取中", percent=5)

            def _cb(pct: int, _phase: str = "") -> None:
                _set_file(i, status="读取中", percent=min(pct, 99))

            try:
                text = extract_text_from_file(p, ext, progress=_cb)
            except Exception:
                text = None
            ok = bool(text and len(text.strip()) >= 3)
            _set_file(i, status="已完成" if ok else "无有效内容", percent=100)
            if ok:
                file_parts.append(text)
                names.append(paths[i][0])
            with lock:
                st = DOC_JOBS[job_id]["file_states"]
                done = sum(1 for s in st if s["status"] in ("已完成", "无有效内容"))
            DOC_JOBS[job_id]["progress"] = round(10 + 55 * done / total)
            DOC_JOBS[job_id]["label"] = f"正在读取材料（{done}/{total} 份已完成）"

        await _asyncio.gather(*(_asyncio.to_thread(_one, i) for i in range(total)))
        if not file_parts:
            DOC_JOBS[job_id]["status"] = "error"
            DOC_JOBS[job_id]["error"] = "未能从文件中提取到文本（图片可能过糊/倾斜，或为扫描件 PDF，建议用清晰图片/文字版 PDF 重试）"
            return

        # 2) 合并 + LLM 综合识别（含 债权记录/抵押物清单归属/无关文件分类）
        combined = "\n".join(
            f"===== 材料{i + 1}/{len(file_parts)}：{names[i]} =====\n{file_parts[i]}"
            for i in range(len(file_parts))
        )
        DOC_JOBS[job_id] = {**DOC_JOBS[job_id], "progress": 72, "label": "AI 正在分析材料（债权要素/抵押物归属/无关文件）…"}
        try:
            from ..services.extractor import extract_doc_material as _extract_doc_material

            doc_result = await _extract_doc_material(combined)
            fields = doc_result["claims"]
            ignored_files = doc_result.get("ignored_files") or []
            file_classes = doc_result.get("file_classes") or []
        except LLMError as e:
            DOC_JOBS[job_id]["status"] = "error"
            DOC_JOBS[job_id]["error"] = f"材料已读取但识别失败：{e}"
            return

        # 3) 去重 + 落库
        seen: set[str] = set()
        dedup_fields = []
        for f in fields:
            key = _norm_name(f.get("debtor_name"))
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            dedup_fields.append(f)
        if not dedup_fields:
            DOC_JOBS[job_id]["status"] = "error"
            DOC_JOBS[job_id]["error"] = "未能从材料中识别出有效的债务人/本金/抵押物信息"
            return

        DOC_JOBS[job_id] = {**DOC_JOBS[job_id], "progress": 90, "label": "正在生成债权记录…"}
        from ..database import SessionLocal
        db = SessionLocal()
        try:
            user = db.get(User, user_id)
            claims = _save_claims(db, user, dedup_fields, "doc", f"{'；'.join(names)}\n{combined[:2000]}")
            for c in claims:
                c.source_raw = "；".join(names)
            db.commit()
            warnings = analyze_text(combined) + analyze_claims(dedup_fields)
            dup = detect_duplicates(db, user_id, [_claim_to_out(c).model_dump() for c in claims])
        finally:
            db.close()

        DOC_JOBS[job_id] = {
            **DOC_JOBS[job_id], "status": "done", "progress": 100, "label": "识别完成",
            "result": {
                "claims": [_claim_to_out(c).model_dump() for c in claims],
                "file_names": names,
                "ignored_files": ignored_files,  # 与本债权无关的文件（前端提示，可让用户说明关联性）
                "file_classes": file_classes,    # 每份文件重要等级 1/2/3 + 类型（上传页展示核对）
                "input_warnings": warnings,
                "dedup": {"removed": len(fields) - len(dedup_fields), **dup},
                "char_count": len(combined),
                "is_single": len(dedup_fields) == 1,
            },
        }
    except Exception as e:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger(__name__).exception("doc job %s failed", job_id)
        DOC_JOBS[job_id] = {**DOC_JOBS[job_id], "status": "error", "error": f"识别过程出错：{e}"}


@router.post("/import-doc", response_model=ApiResponse)
async def import_doc(files: list[UploadFile] = File(...), user: User = Depends(get_current_user)):
    """上传材料（Word/PDF/Excel/图片，可多份）→ 立即返回任务号，后台提取+识别（前端轮询进度）。

    2026-09-04 用户确认：①不留原件；②识别 债务人/债权人/本息/利息计算方式/是否胜诉/抵押物；
    ③一份债权可多份材料合并；④按内容识别拆分（单份=一条、清单=多条）；⑤图片走 OCR。
    2026-09-05 改任务制：大文件/扫描件识别可达分钟级，同步等待会让用户误判"没点成功/死机"。
    2026-09-05 用户补充：Excel 不一定=债权列表（可能是抵押物清单/无关表），全部文件统一按内容
    识别——债权清单拆多条、抵押物清单并入对应债权、无关文件列入 ignored_files 由用户确认。
    """
    from ..config import get_settings as _gs

    ALLOWED = {".docx", ".doc", ".pdf", ".txt", ".md", ".jpg", ".jpeg", ".png", ".webp", ".bmp",
               ".xlsx", ".xls", ".csv"}
    if not files:
        raise err("请选择文件")
    if len(files) > 20:
        raise err("一次最多上传 20 份材料")

    _settings = _gs()
    os.makedirs(_settings.upload_dir, exist_ok=True)

    paths: list[tuple[str, str, str]] = []
    for idx, file in enumerate(files):
        filename = file.filename or f"材料{idx + 1}"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED:
            raise err(f"不支持的文件格式 {ext or '(无扩展名)'}：{filename}，支持 Word/PDF/Excel/图片(jpg/png)")
        content = await file.read()
        if not content:
            continue
        if len(content) > 20 * 1024 * 1024:
            raise err(f"文件过大（超过 20MB）：{filename}")
        safe = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", filename)
        path = os.path.join(_settings.upload_dir, f"claimdoc_{_uuid.uuid4().hex[:8]}_{safe}")
        with open(path, "wb") as fp:
            fp.write(content)
        paths.append((safe, ext.lstrip("."), path))

    if not paths:
        raise err("没有可识别的文件（文件可能为空）")

    _doc_job_cleanup()
    job_id = _uuid.uuid4().hex
    DOC_JOBS[job_id] = {"status": "running", "progress": 2, "label": "任务已接收，正在开始…",
                        "created_at": _time.time()}
    _asyncio.get_event_loop().create_task(_run_doc_job(job_id, user.id, paths))
    return ok({"job_id": job_id, "file_count": len(paths)})


@router.get("/import-doc/{job_id}/status", response_model=ApiResponse)
def doc_job_status(job_id: str, user: User = Depends(get_current_user)):
    """轮询材料识别任务状态：{status: running/done/error, progress, label, result?, error?}"""
    job = DOC_JOBS.get(job_id)
    if job is None:
        raise err("任务不存在或已过期，请重新上传")
    return ok({k: v for k, v in job.items() if k != "created_at"})


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
