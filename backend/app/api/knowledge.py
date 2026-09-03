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
    category: str | None = None
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
    category: str | None = None
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
        "category": d.category,
        "source_type": d.source_type or "manual",
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
        "category": c.category,
        "source_type": c.source_type or "manual",
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

# 知识自动分类关键词表（统一粘贴文字框录入时按内容识别分类）
_LEGAL_CAT_RULES = [
    ("术语词典", ["术语", "名词解释", "什么是", "词典"]),
    ("尽调规则", ["评级", "评分标准", "分档", "覆盖比例", "处置关注点", "尽调框架", "输出格式"]),
    ("土地估价", ["M0", "M1", "M2", "M3", "工业用地", "土地性质", "划拨", "出让金", "容积率", "建安造价"]),
    ("商业估价", ["商业房产", "商铺", "写字楼", "商业氛围", "地段", "商圈", "出租率"]),
    ("平台规范", ["禁止编造", "平台铁律", "内部规范", "法规引用"]),
    ("行业常识", ["覆盖", "倒找", "倒挂", "计量单位", "计息", "追偿", "清偿顺位", "优先受偿", "以物抵债"]),
    ("尽调法规", ["第", "条", "规定", "解释", "法", "民诉", "民法典", "刑法", "破产法"]),
]
_CASE_CAT_RULES = [
    ("财产线索", ["财产线索", "线索", "资产", "应收", "到期债权", "调查"]),
    ("尽调案例", ["案例", "执行", "终本", "拒执", "抵押", "保证", "一人公司", "流拍", "占用"]),
]


def _classify_text(text: str, is_case: bool = False) -> str:
    """按关键词自动识别知识分类（用于统一粘贴框录入）"""
    rules = _CASE_CAT_RULES if is_case else _LEGAL_CAT_RULES
    for cat, kws in rules:
        for kw in kws:
            if kw in text:
                return cat
    return "其他"


@router.post("/knowledge/classify", response_model=ApiResponse)
def classify_knowledge(payload: dict, admin: User = Depends(require_admin)):
    """自动识别粘贴文本所属知识分类（仅管理员）"""
    text = str(payload.get("text") or "")
    is_case = bool(payload.get("is_case"))
    if not text.strip():
        raise err("请输入内容")
    return ok({"category": _classify_text(text, is_case)})


@router.get("/knowledge/categories", response_model=ApiResponse)

@router.get("/knowledge/categories", response_model=ApiResponse)
def list_categories(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """知识分类清单（动态聚合，含各分类条目数）；仅管理员可访问"""
    from sqlalchemy import func

    legal_rows = db.execute(
        select(LegalDoc.category, func.count()).group_by(LegalDoc.category)
    ).all()
    case_rows = db.execute(
        select(KnowledgeCase.category, func.count()).group_by(KnowledgeCase.category)
    ).all()
    return ok({
        "legal_categories": [
            {"name": c, "count": n} for c, n in legal_rows if c
        ],
        "case_categories": [
            {"name": c, "count": n} for c, n in case_rows if c
        ],
    })


@router.put("/admin/knowledge/categories", response_model=ApiResponse)
def rename_category(req: dict, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """重命名知识分类（旧名 → 新名，应用于 legal_docs 与 knowledge_cases 两表）"""
    old = (req.get("old") or "").strip()
    new = (req.get("new") or "").strip()
    if not old or not new:
        raise err("请提供旧分类名与新分类名")
    if old == new:
        raise err("新旧分类名相同")
    # 统计受影响条目
    n_legal = db.query(LegalDoc).filter(LegalDoc.category == old).count()
    n_case = db.query(KnowledgeCase).filter(KnowledgeCase.category == old).count()
    if n_legal == 0 and n_case == 0:
        raise err(f"分类「{old}」不存在")
    db.query(LegalDoc).filter(LegalDoc.category == old).update({"category": new})
    db.query(KnowledgeCase).filter(KnowledgeCase.category == old).update({"category": new})
    write_audit_log(db, admin.id, "knowledge_category", "rename",
                    entity_id=None, change_summary={"old": old, "new": new})
    db.commit()
    return ok({"renamed": n_legal + n_case}, f"分类「{old}」已重命名为「{new}」（{n_legal + n_case} 条）")


@router.delete("/admin/knowledge/categories/{name}", response_model=ApiResponse)
def delete_category(name: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """删除知识分类（仅允许删除空分类；非空需先重命名或迁移条目）"""
    from urllib.parse import unquote
    name = unquote(name).strip()
    n_legal = db.query(LegalDoc).filter(LegalDoc.category == name).count()
    n_case = db.query(KnowledgeCase).filter(KnowledgeCase.category == name).count()
    if n_legal + n_case > 0:
        raise err(f"分类「{name}」下有 {n_legal + n_case} 条知识，不能直接删除（可重命名或先移动条目）")
    write_audit_log(db, admin.id, "knowledge_category", "delete",
                    entity_id=None, change_summary={"name": name})
    db.commit()
    return ok(None, f"分类「{name}」已删除（空分类）")


@router.get("/knowledge/legal-docs", response_model=ApiResponse)
def list_legal_docs(category: str | None = None, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(LegalDoc)
    if category:
        q = q.where(LegalDoc.category == category)
    docs = db.scalars(q.order_by(LegalDoc.id.desc()).limit(500)).all()
    return ok({"docs": [_legal_to_dict(d) for d in docs]})


@router.post("/admin/legal-docs", response_model=ApiResponse)
def create_legal_doc(req: LegalDocCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = req.model_dump()
    data["source_type"] = "manual"  # 文字录入 → 可编辑
    doc = LegalDoc(**data)
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
    # 文档上传的条目只读：仅可删除，不可修改
    if (doc.source_type or "manual") == "upload":
        raise err("该条录为文档上传生成（只读），不可编辑；如需修改请删除后重新录入/上传")
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
def list_cases(category: str | None = None, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(KnowledgeCase)
    if category:
        q = q.where(KnowledgeCase.category == category)
    cases = db.scalars(q.order_by(KnowledgeCase.id.desc()).limit(500)).all()
    return ok({"cases": [_case_to_dict(c) for c in cases]})


@router.post("/admin/knowledge-cases", response_model=ApiResponse)
def create_case(req: CaseCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = req.model_dump()
    data["source_type"] = "manual"  # 文字录入 → 可编辑
    c = KnowledgeCase(**data)
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
    # 文档上传的条目只读：仅可删除，不可修改
    if (c.source_type or "manual") == "upload":
        raise err("该条录为文档上传生成（只读），不可编辑；如需修改请删除后重新录入/上传")
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
        source_type="upload",  # 文档上传 → 只读（仅可删）
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
        source_type="upload",  # 文档上传 → 只读（仅可删）
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
