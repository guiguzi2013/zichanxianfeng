"""知识库路由：规范性文件 + 典型案例（人工维护 CRUD + 文件上传）＋ 报告场景匹配

- 规范性文件：规范报告用词与法条引用；效力状态人工维护（现行有效/已修改/已废止/需复核），
  库内到期/废止文件在管理界面标红提醒。
- 案例：按场景标签/关键词与尽调数据特征匹配，报告生成时附加风险提醒。
- 上传：管理员可上传法规原文/案例文档（Word/PDF/TXT/图片），自动提取文本填入摘要。
"""
import os
import re

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import KnowledgeCase, LegalDoc, User
from ..schemas.common import ApiResponse, err, ok
from ..services.audit import write_audit_log
from .deps import require_admin

router = APIRouter(tags=["knowledge"])
settings = get_settings()

ALLOWED_EXTS = {".docx", ".doc", ".pdf", ".txt", ".md", ".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class LegalDocCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    doc_no: str | None = None
    issuer: str | None = None
    effect_date: str | None = None
    status: str = "现行有效"
    latest_version: str | None = None
    tags: str | None = None
    keywords: str | None = None
    summary: str | None = None
    note: str | None = None


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    scenario: str | None = None
    tags: str | None = None
    keywords: str | None = None
    summary: str | None = None
    approach: str | None = None
    result: str | None = None
    source: str | None = None


def _legal_to_dict(d: LegalDoc) -> dict:
    return {
        "id": d.id,
        "title": d.title,
        "doc_no": d.doc_no,
        "issuer": d.issuer,
        "effect_date": d.effect_date,
        "status": d.status,
        "latest_version": d.latest_version,
        "tags": d.tags,
        "keywords": d.keywords,
        "summary": d.summary,
        "note": d.note,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _case_to_dict(c: KnowledgeCase) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "scenario": c.scenario,
        "tags": c.tags,
        "keywords": c.keywords,
        "summary": c.summary,
        "approach": c.approach,
        "result": c.result,
        "source": c.source,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


# ---------------- 规范性文件 ----------------

@router.get("/knowledge/legal-docs", response_model=ApiResponse)
def list_legal_docs(db: Session = Depends(get_db)):
    docs = db.scalars(select(LegalDoc).order_by(LegalDoc.id.desc()).limit(500)).all()
    return ok({"docs": [_legal_to_dict(d) for d in docs]})


@router.post("/admin/legal-docs", response_model=ApiResponse)
def create_legal_doc(req: LegalDocCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    doc = LegalDoc(**req.model_dump())
    db.add(doc)
    write_audit_log(db, admin.id, "legal_doc", "create", entity_id=None, change_summary={"title": req.title, "status": req.status})
    db.commit()
    db.refresh(doc)
    return ok(_legal_to_dict(doc), "规范性文件已添加")


@router.put("/admin/legal-docs/{doc_id}", response_model=ApiResponse)
def update_legal_doc(doc_id: int, req: LegalDocCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    doc = db.get(LegalDoc, doc_id)
    if doc is None:
        raise err("规范性文件不存在", http_status=404)
    before = {"title": doc.title, "status": doc.status}
    for k, v in req.model_dump().items():
        setattr(doc, k, v)
    write_audit_log(db, admin.id, "legal_doc", "update", entity_id=doc_id, change_summary={"before": before, "after": {"title": req.title, "status": req.status}})
    db.commit()
    db.refresh(doc)
    return ok(_legal_to_dict(doc), "规范性文件已更新")


@router.delete("/admin/legal-docs/{doc_id}", response_model=ApiResponse)
def delete_legal_doc(doc_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    doc = db.get(LegalDoc, doc_id)
    if doc is None:
        raise err("规范性文件不存在", http_status=404)
    write_audit_log(db, admin.id, "legal_doc", "delete", entity_id=doc_id, change_summary={"title": doc.title})
    db.delete(doc)
    db.commit()
    return ok(None, "规范性文件已删除")


# ---------------- 案例 ----------------

@router.get("/knowledge/cases", response_model=ApiResponse)
def list_cases(db: Session = Depends(get_db)):
    cases = db.scalars(select(KnowledgeCase).order_by(KnowledgeCase.id.desc()).limit(500)).all()
    return ok({"cases": [_case_to_dict(c) for c in cases]})


@router.post("/admin/knowledge-cases", response_model=ApiResponse)
def create_case(req: CaseCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = KnowledgeCase(**req.model_dump())
    db.add(c)
    write_audit_log(db, admin.id, "knowledge_case", "create", entity_id=None, change_summary={"title": req.title, "scenario": req.scenario})
    db.commit()
    db.refresh(c)
    return ok(_case_to_dict(c), "案例已添加")


@router.put("/admin/knowledge-cases/{case_id}", response_model=ApiResponse)
def update_case(case_id: int, req: CaseCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(KnowledgeCase, case_id)
    if c is None:
        raise err("案例不存在", http_status=404)
    before = {"title": c.title, "scenario": c.scenario}
    for k, v in req.model_dump().items():
        setattr(c, k, v)
    write_audit_log(db, admin.id, "knowledge_case", "update", entity_id=case_id, change_summary={"before": before, "after": {"title": req.title, "scenario": req.scenario}})
    db.commit()
    db.refresh(c)
    return ok(_case_to_dict(c), "案例已更新")


@router.delete("/admin/knowledge-cases/{case_id}", response_model=ApiResponse)
def delete_case(case_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(KnowledgeCase, case_id)
    if c is None:
        raise err("案例不存在", http_status=404)
    write_audit_log(db, admin.id, "knowledge_case", "delete", entity_id=case_id, change_summary={"title": c.title})
    db.delete(c)
    db.commit()
    return ok(None, "案例已删除")


# ---------------- 场景匹配（报告用） ----------------

def _match_keywords(text: str, keywords: str | None) -> bool:
    """文本命中案例/规范关键词之一即视为匹配（关键词逗号分隔）"""
    if not keywords or not text:
        return False
    for kw in keywords.split(","):
        kw = kw.strip()
        if kw and kw in text:
            return True
    return False


@router.post("/knowledge/match", response_model=ApiResponse)
def match_knowledge(payload: dict, db: Session = Depends(get_db)):
    """根据尽调特征文本匹配知识库：返回命中的案例提醒 + 相关规范性文件

    payload: {"features": "被执行 失信 抵押物 房产 自然人保证人 一人公司 股权 ..."}
    """
    text = str(payload.get("features") or "")
    cases = db.scalars(select(KnowledgeCase)).all()
    docs = db.scalars(select(LegalDoc)).all()
    matched_cases = [
        _case_to_dict(c) for c in cases
        if _match_keywords(text, c.keywords) or _match_keywords(text, c.tags) or _match_keywords(text, c.scenario)
    ]
    matched_docs = [
        _legal_to_dict(d) for d in docs
        if d.status not in ("已废止",) and (_match_keywords(text, d.keywords) or _match_keywords(text, d.tags))
    ]
    return ok({"cases": matched_cases, "docs": matched_docs})


# ---------------- 文件上传（法规原文/案例文档） ----------------

def _save_upload(kind: str, file: UploadFile) -> tuple[str, str]:
    """保存上传文件到知识库目录，返回 (path, text)"""
    filename = file.filename or "file"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise err(f"不支持的文件格式 {ext or '(无扩展名)'}，支持 Word/PDF/TXT/图片")
    data = file.read() if hasattr(file, "read") else b""
    if len(data) > 15 * 1024 * 1024:
        raise err("文件过大（超过 15MB）")
    kb_dir = os.path.join(settings.upload_dir, "knowledge")
    os.makedirs(kb_dir, exist_ok=True)
    safe = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", filename)
    path = os.path.join(kb_dir, f"{kind}_{int(__import__('time').time() * 1000)}_{safe}")
    with open(path, "wb") as fp:
        fp.write(data)
    text = ""
    try:
        from ..services.supplement_parser import extract_text_from_file
        text = extract_text_from_file(path, ext.lstrip(".")) or ""
    except Exception:  # noqa: BLE001
        pass
    return path, text


@router.post("/admin/legal-docs/upload", response_model=ApiResponse)
async def upload_legal_doc(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """上传法规原文 → 自动提取文本创建规范性文件条目（标题取文件名）"""
    path, text = _save_upload("legal", file)
    filename = (file.filename or "法规文件").rsplit(".", 1)[0][:120]
    doc = LegalDoc(
        title=filename,
        summary=(text or "")[:4000],
        note="由上传文件自动提取文本生成，请人工核对版本、文号、施行日期与效力状态。",
        tags="",
        keywords="",
        status="需复核",
    )
    db.add(doc)
    write_audit_log(db, admin.id, "legal_doc", "create_upload", entity_id=None,
                    change_summary={"title": filename, "path": path})
    db.commit()
    db.refresh(doc)
    return ok(_legal_to_dict(doc), "法规文件已上传并提取文本，请在列表中核对补全元信息")


@router.post("/admin/knowledge-cases/upload", response_model=ApiResponse)
async def upload_case_doc(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """上传案例文档 → 自动提取文本创建案例条目（标题取文件名，摘要=提取文本）"""
    path, text = _save_upload("case", file)
    filename = (file.filename or "案例文档").rsplit(".", 1)[0][:120]
    c = KnowledgeCase(
        title=filename,
        scenario="待归类",
        tags="",
        keywords="",
        summary=(text or "")[:6000],
        source="管理员上传",
        result="",
        approach="",
    )
    db.add(c)
    write_audit_log(db, admin.id, "knowledge_case", "create_upload", entity_id=None,
                    change_summary={"title": filename, "path": path})
    db.commit()
    db.refresh(c)
    return ok(_case_to_dict(c), "案例文档已上传并提取文本，请补全场景标签与关键词（用于报告自动匹配提醒）")
