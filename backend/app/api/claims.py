"""债权路由：三种输入通道 + CRUD"""
import json

from fastapi import APIRouter, Depends, File, UploadFile, status
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
    claims = _save_claims(db, user, fields, "text", req.text)
    from ..services.input_quality import analyze_claims, analyze_text

    warnings = analyze_text(req.text) + analyze_claims(fields)
    return ok({
        "claims": [_claim_to_out(c).model_dump() for c in claims],
        "input_warnings": warnings,
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
    claims = _save_claims(db, user, fields, "link", result.text[:2000])
    from ..services.input_quality import analyze_claims, analyze_text

    warnings = analyze_text(result.text) + analyze_claims(fields)
    return ok({
        "claims": [_claim_to_out(c).model_dump() for c in claims],
        "scrape_note": result.note,
        "input_warnings": warnings,
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

    # 规范映射直接转 claim；缺字段（如担保类型/司法状态）保持 null，由完整度标识
    fields_list = [extract_from_excel_row(r) for r in rows]
    claims = _save_claims(db, user, fields_list, "excel", file.filename)

    # 补写 source_raw（Excel 原文无法保留，存文件名）
    for c in claims:
        c.source_raw = file.filename
    db.commit()

    from ..services.input_quality import analyze_claims, analyze_excel_rows

    warnings = analyze_excel_rows(rows) + analyze_claims(fields_list)
    return ok({
        "claims": [_claim_to_out(c).model_dump() for c in claims],
        "column_mapping": mapping,
        "unmapped_columns": unmapped,
        "input_warnings": warnings,
    })


@router.put("/{claim_id}", response_model=ApiResponse)
def update_claim(claim_id: int, req: ClaimUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    claim = db.get(Claim, claim_id)
    if claim is None or claim.user_id != user.id:
        raise err("记录不存在", http_status=status.HTTP_404_NOT_FOUND)
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(claim, field, value)
    # 重算完整度（关键字段规则：债务人/本金/抵押物）
    completeness, missing = evaluate_completeness({
        "debtor_name": claim.debtor_name,
        "principal_cents": claim.principal_cents,
        "collateral": claim.collateral,
        "interest_cents": claim.interest_cents,
        "guaranty_type": claim.guaranty_type,
        "judicial_status": claim.judicial_status,
    })
    claim.completeness = completeness
    claim.missing_fields = json.dumps(missing, ensure_ascii=False)
    db.commit()
    db.refresh(claim)
    return ok(_claim_to_out(claim).model_dump(), "已更新")


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
