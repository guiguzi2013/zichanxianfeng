# -*- coding: utf-8 -*-
"""回收站 API(2026-09-08 用户批准: 我的任务/我的报告删除 + 回收站)

对象: task(债权尽调任务, 连坐其全部报告) / report(单份尽调报告) /
      profile(企业速览) / clue(财产线索报告)。土地厂房估价不在回收站范围(仅任务记录)。
规则:
- 删除=软删(deleted_at); 删除任务连带软删其全部报告; PDF 文件保留(恢复可用)
- 恢复/重新生成 均校验同名冲突(见 _conflict_reason), 有同名 → 只能清空
- 清空=物理删除(连带 PDF); 清空任务连带清空其报告
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import PropertyClueReport, QccProfile, Report, Task
from ..models.user import User
from ..schemas.common import ApiResponse, err, ok
from .deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trash", tags=["trash"])

BACKEND_ROOT = Path(__file__).resolve().parent.parent  # backend/


def _pdf_abs(pdf_path: str | None) -> str | None:
    """'./data/pdf/x.pdf' → 绝对路径; 异常返回 None"""
    if not pdf_path:
        return None
    p = pdf_path.replace("\\", "/")
    if p.startswith("./"):
        p = str(BACKEND_ROOT / p[2:])
    return p if os.path.exists(p) else None


def _name_of(content_json: str | None, fallback: str) -> str:
    """从报告 content 提取债务人名(前端展示用)"""
    if content_json:
        try:
            c = json.loads(content_json)
            if isinstance(c, dict):
                meta = c.get("report_meta") or {}
                return meta.get("debtor_name") or fallback
        except Exception:
            pass
    return fallback


# ---------- 同名冲突校验(恢复/重新生成前) ----------

def _conflict_reason(user_id: int, kind: str, row, db) -> str | None:
    """已存在同名未删对象 → 返回冲突原因; 无冲突返回 None"""
    if kind == "profile":
        other = db.scalar(select(QccProfile).where(
            QccProfile.user_id == user_id, QccProfile.company == row.company,
            QccProfile.deleted_at.is_(None), QccProfile.id != row.id))
        return "同名企业速览报告已存在（恢复会造成重复），只能清空。" if other else None
    if kind == "clue":
        other = db.scalar(select(PropertyClueReport).where(
            PropertyClueReport.user_id == user_id, PropertyClueReport.company == row.company,
            PropertyClueReport.deleted_at.is_(None), PropertyClueReport.id != row.id))
        return "同名财产线索报告已存在（恢复会造成重复），只能清空。" if other else None
    if kind == "task":
        claim_set = set(json.loads(row.claim_ids or "[]"))
        others = db.scalars(select(Task).where(
            Task.user_id == user_id, Task.deleted_at.is_(None), Task.id != row.id)).all()
        for o in others:
            if set(json.loads(o.claim_ids or "[]")) == claim_set:
                return "相同债权组合的尽调任务已存在（恢复会造成重复），只能清空。"
        # 若该任务存在对应未删报告? 任务重建视为整组; 无
        return None
    if kind == "report":
        # 同一债权(claim)已有未删报告
        other = db.scalar(select(Report).where(
            Report.claim_id == row.claim_id, Report.deleted_at.is_(None), Report.id != row.id))
        return "该债权已有尽调报告（恢复会造成重复），只能清空。" if other else None
    return None


# ---------- 对象装载 ----------

def _load(user_id: int, kind: str, rid: int, db, require_deleted: bool = True):
    """装载回收站对象(校验归属与软删状态); 返回 (row, extra)"""
    if kind == "task":
        row = db.get(Task, rid)
        extra = {}
        if row and (row.user_id != user_id or (require_deleted and row.deleted_at is None)):
            return None, {}
        if row:
            # 名称 = 首份报告债务人
            rep = db.scalar(select(Report).where(Report.task_id == rid).order_by(Report.id))
            extra["name"] = _name_of(rep.content if rep else None, f"尽调任务 #{rid}") if rep else f"尽调任务 #{rid}"
        return row, extra
    if kind == "report":
        row = db.get(Report, rid)
        if row:
            t = db.get(Task, row.task_id)
            if t is None or t.user_id != user_id or (require_deleted and row.deleted_at is None):
                return None, {}
        return row, {"name": _name_of(row.content if row else None, f"报告 #{rid}") if row else None}
    if kind == "profile":
        row = db.get(QccProfile, rid)
        if row and (row.user_id != user_id or (require_deleted and row.deleted_at is None)):
            return None, {}
        return row, {"name": row.company if row else None}
    if kind == "clue":
        row = db.get(PropertyClueReport, rid)
        if row and (row.user_id != user_id or (require_deleted and row.deleted_at is None)):
            return None, {}
        return row, {"name": row.company if row else None}
    return None, {}


class KindIdRequest(BaseModel):
    kind: str  # task/report/profile/clue
    id: int


# ---------- 列表 ----------

@router.get("/list", response_model=ApiResponse)
def list_trash(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """当前用户回收站: 全部已删条目(含任务连坐的报告)"""
    out = []
    for t in db.scalars(select(Task).where(Task.user_id == user.id, Task.deleted_at.is_not(None)).order_by(Task.deleted_at.desc())).all():
        rep = db.scalar(select(Report).where(Report.task_id == t.id).order_by(Report.id))
        out.append({"kind": "task", "id": t.id,
                    "name": _name_of(rep.content if rep else None, f"尽调任务 #{t.id}") if rep else f"尽调任务 #{t.id}",
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "deleted_at": t.deleted_at.isoformat() if t.deleted_at else None})
    for r in db.scalars(select(Report).where(
            Report.id.in_(select(Report.id).join(Task, Report.task_id == Task.id)
                          .where(Task.user_id == user.id, Task.deleted_at.is_(None),
                                 Report.deleted_at.is_not(None))))
            .order_by(Report.deleted_at.desc())).all():
        out.append({"kind": "report", "id": r.id, "name": _name_of(r.content, f"报告 #{r.id}"),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None})
    for p in db.scalars(select(QccProfile).where(
            QccProfile.user_id == user.id, QccProfile.deleted_at.is_not(None))
            .order_by(QccProfile.deleted_at.desc())).all():
        out.append({"kind": "profile", "id": p.id, "name": p.company,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "deleted_at": p.deleted_at.isoformat() if p.deleted_at else None})
    for c in db.scalars(select(PropertyClueReport).where(
            PropertyClueReport.user_id == user.id, PropertyClueReport.deleted_at.is_not(None))
            .order_by(PropertyClueReport.deleted_at.desc())).all():
        out.append({"kind": "clue", "id": c.id, "name": c.company,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None})
    out.sort(key=lambda x: x.get("deleted_at") or "", reverse=True)
    return ok({"items": out})


# ---------- 删除 ----------

@router.post("/delete", response_model=ApiResponse)
def delete_item(req: KindIdRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, _ = _load(user.id, req.kind, req.id, db, require_deleted=False)
    if row is None:
        raise err("对象不存在或无权操作", http_status=404)
    now = datetime.now()
    if req.kind == "task":
        row.deleted_at = now
        for r in db.scalars(select(Report).where(Report.task_id == row.id)).all():
            r.deleted_at = now
    else:
        row.deleted_at = now
    db.commit()
    return ok(None, "已移入回收站（可恢复或清空）")


# ---------- 恢复 ----------

@router.post("/restore", response_model=ApiResponse)
def restore_item(req: KindIdRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, _ = _load(user.id, req.kind, req.id, db)
    if row is None:
        raise err("回收站条目不存在或无权操作", http_status=404)
    reason = _conflict_reason(user.id, req.kind, row, db)
    if reason:
        raise err(reason)
    if req.kind == "task":
        row.deleted_at = None
        for r in db.scalars(select(Report).where(Report.task_id == row.id)).all():
            r.deleted_at = None
    else:
        row.deleted_at = None
    db.commit()
    return ok(None, "已恢复")


# ---------- 重新尽调/生成(提示扣分由前端负责) ----------

@router.post("/regenerate", response_model=ApiResponse)
async def regenerate_item(req: KindIdRequest, user: User = Depends(get_current_user)):
    """回收站条目重新尽调/生成: task=逐报告重新尽调(缓存/LLM); report=重新尽调;
    profile/clue=重新查询企查查(真扣积分, 前端须提示)。成功后条目回到列表(内容更新为新版)。"""
    row, extra = _load(user.id, req.kind, req.id, SessionLocal())
    if row is None:
        raise err("回收站条目不存在或无权操作", http_status=404)
    from ..database import SessionLocal as _SL
    db = _SL()
    try:
        reason = _conflict_reason(user.id, req.kind, row, db)
        if reason:
            raise err(reason)
        now = datetime.now()
        if req.kind == "task":
            # 恢复任务并对其每份报告重新尽调(regenerate_report: 走缓存/LLM, 升版本)
            from ..services.due_diligence import regenerate_report
            row.deleted_at = None
            row.status = "done"
            db.commit()
            reports = db.scalars(select(Report).where(Report.task_id == row.id)).all()
            for r in reports:
                r.deleted_at = None
                db.commit()
                await regenerate_report(r.id)
            return ok(None, "重新尽调完成")
        if req.kind == "report":
            from ..services.due_diligence import regenerate_report
            await regenerate_report(row.id)
            r2 = db.get(Report, row.id)
            if r2:
                r2.deleted_at = None
                db.commit()
            return ok(None, "已重新尽调并恢复")
        if req.kind == "profile":
            db.close()
            _ok, err_msg = await _regenerate_profile(row)
            return ok(None, "已重新生成并恢复") if _ok else err(err_msg or "重新生成失败")
        if req.kind == "clue":
            db.close()
            _ok, err_msg = await _regenerate_clue(row)
            return ok(None, "已重新生成并恢复") if _ok else err(err_msg or "重新生成失败")
    finally:
        db.close()
    return ok(None)


async def _regenerate_profile(row) -> tuple[bool, str | None]:
    """企业速览重新查询(真扣积分): 行保持同 id, 内容/PDF 更新, deleted_at=None"""
    try:
        from ..api.qcc import query_debtor_profile
        from ..api.debtor_profile import _build_sections, _summary_of
        from ..services.profile_pdf import generate_profile_pdf
        from ..services.advice_writer import build_context, polish_report
        from ..config import get_settings

        result = await query_debtor_profile(row.company)
        reg = (result.get("biz") or {}).get("get_company_registration_info", {}) or {}
        reg_d = reg.get("data") if reg.get("ok") else None
        if not (reg.get("ok") and isinstance(reg_d, dict) and str(reg_d.get("企业名称") or "").strip()):
            return False, "未查询到该名称的企业登记信息，未能重新生成。"
        sections = _build_sections(result)
        sections = await polish_report(sections, build_context(result), kind="profile")
        summary = _summary_of(result)
        content = {"sections": sections, "summary": summary,
                   "raw": {k: v for k, v in (result.get("biz") or {}).items()},
                   "risk": result.get("risk")}
        settings = get_settings()
        pdf_path = f"{settings.pdf_dir}/profile_{row.id}.pdf"
        meta = {"queried_at": result.get("queried_at") or "",
                "sources": "企查查（实时接口）",
                "report_no": f"QS{datetime.now():%Y%m%d}-{row.id}",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        generate_profile_pdf(row.company, sections, meta, pdf_path)
        db = SessionLocal()
        try:
            r = db.get(QccProfile, row.id)
            r.content = json.dumps(content, ensure_ascii=False)
            r.pdf_path = pdf_path
            r.search_name = result.get("search_name") or row.company
            r.queried_at = result.get("queried_at")
            r.deleted_at = None
            db.commit()
        finally:
            db.close()
        return True, None
    except Exception as e:  # noqa: BLE001
        logger.exception("trash regenerate profile %s failed", row.id)
        return False, f"重新生成失败：{e}"


async def _regenerate_clue(row) -> tuple[bool, str | None]:
    try:
        from ..api.qcc import query_company_ipr, query_property_clues
        from ..services.clue_report_builder import build_sections, build_summary
        from ..services.clue_report_pdf import generate_clue_report_pdf
        from ..services.advice_writer import build_context, polish_report
        from ..config import get_settings

        result = await query_property_clues(row.company)
        reg = (result.get("biz") or {}).get("get_company_registration_info", {}) or {}
        reg_d = reg.get("data") if reg.get("ok") else None
        if not (reg.get("ok") and isinstance(reg_d, dict) and str(reg_d.get("企业名称") or "").strip()):
            return False, "未查询到该名称的企业登记信息，未能重新生成。"
        uscc = reg_d.get("统一社会信用代码") if isinstance(reg_d, dict) else None
        ipr = await query_company_ipr(result.get("search_name") or row.company, uscc)
        if ipr:
            result["ipr"] = ipr
        sections = build_sections(result)
        sections = await polish_report(sections, build_context(result), kind="clue")
        summary = build_summary(result)
        content = {"sections": sections, "summary": summary,
                   "raw": {k: v for k, v in (result.get("biz") or {}).items()},
                   "risk": result.get("risk"), "ipr": result.get("ipr")}
        settings = get_settings()
        pdf_path = f"{settings.pdf_dir}/clue_{row.id}.pdf"
        meta = {"queried_at": result.get("queried_at") or "",
                "sources": "企查查（实时接口）",
                "report_no": f"CS{datetime.now():%Y%m%d}-{row.id}",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        generate_clue_report_pdf(row.company, sections, meta, pdf_path)
        db = SessionLocal()
        try:
            r = db.get(PropertyClueReport, row.id)
            r.content = json.dumps(content, ensure_ascii=False)
            r.pdf_path = pdf_path
            r.search_name = result.get("search_name") or row.company
            r.queried_at = result.get("queried_at")
            r.deleted_at = None
            db.commit()
        finally:
            db.close()
        return True, None
    except Exception as e:  # noqa: BLE001
        logger.exception("trash regenerate clue %s failed", row.id)
        return False, f"重新生成失败：{e}"


# ---------- 清空(物理删除 + PDF) ----------

def _physical_delete(db, kind: str, row) -> None:
    """物理删除行与 PDF; task 连坐其 reports"""
    pdfs: list[str] = []
    if kind == "task":
        for r in db.scalars(select(Report).where(Report.task_id == row.id)).all():
            if r.pdf_path:
                pdfs.append(r.pdf_path)
            db.delete(r)
    elif kind == "report":
        if row.pdf_path:
            pdfs.append(row.pdf_path)
        db.delete(row)
    elif kind in ("profile", "clue"):
        if row.pdf_path:
            pdfs.append(row.pdf_path)
        db.delete(row)
    for p in pdfs:
        fp = _pdf_abs(p)
        if fp:
            try:
                os.remove(fp)
            except OSError:
                pass


@router.post("/clear", response_model=ApiResponse)
def clear_item(req: KindIdRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, _ = _load(user.id, req.kind, req.id, db)
    if row is None:
        raise err("回收站条目不存在或无权操作", http_status=404)
    _physical_delete(db, req.kind, row)
    db.commit()
    return ok(None, "已彻底删除")


@router.post("/clear-all", response_model=ApiResponse)
def clear_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """清空该用户整个回收站: 任务连坐报告; PDF 物理删除"""
    deleted_tasks = db.scalars(select(Task).where(
        Task.user_id == user.id, Task.deleted_at.is_not(None))).all()
    deleted_report_ids = set()
    for t in deleted_tasks:
        _physical_delete(db, "task", t)
        deleted_report_ids.add(t.id)
    # 单删的报告(其任务未删)
    for r in db.scalars(select(Report).join(Task, Report.task_id == Task.id)
                       .where(Task.user_id == user.id, Task.deleted_at.is_(None),
                              Report.deleted_at.is_not(None))).all():
        _physical_delete(db, "report", r)
    for p in db.scalars(select(QccProfile).where(
            QccProfile.user_id == user.id, QccProfile.deleted_at.is_not(None))).all():
        _physical_delete(db, "profile", p)
    for c in db.scalars(select(PropertyClueReport).where(
            PropertyClueReport.user_id == user.id, PropertyClueReport.deleted_at.is_not(None))).all():
        _physical_delete(db, "clue", c)
    db.commit()
    return ok(None, "回收站已清空")
