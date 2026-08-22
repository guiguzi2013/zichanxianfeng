"""报告路由：查询/PDF生成/补充材料/版块备注"""
import json
import logging
import os
import re

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Report, ReportVersion, Task, Upload, User
from ..schemas.common import ApiResponse, err, ok
from ..schemas.task import SectionNoteRequest
from ..services.pdf_generator import generate_report_pdf
from .deps import get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _report_to_out(report: Report) -> dict:
    return {
        "id": report.id,
        "task_id": report.task_id,
        "claim_id": report.claim_id,
        "version": report.version,
        "content": json.loads(report.content) if report.content else None,
        "pdf_path": report.pdf_path,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/{task_id}", response_model=ApiResponse)
def get_task_reports(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise err("任务不存在", http_status=404)
    reports = db.query(Report).filter(Report.task_id == task_id).all()
    return ok({"reports": [_report_to_out(r) for r in reports]})


@router.post("/{report_id}/pdf", response_model=ApiResponse)
def generate_pdf(report_id: int, background: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if report is None:
        raise err("报告不存在", http_status=404)
    task = db.get(Task, report.task_id)
    if task is None or task.user_id != user.id:
        raise err("无权访问", http_status=403)

    background.add_task(_pdf_job, report.id)
    return ok(None, "PDF 生成中，稍后刷新获取下载链接")


def _pdf_job(report_id: int):
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        report = db.get(Report, report_id)
        if report is None or not report.content:
            return
        content = json.loads(report.content)
        path = generate_report_pdf(report_id, content)
        report.pdf_path = path
        db.commit()
    finally:
        db.close()


@router.get("/{report_id}/pdf/download")
def download_pdf(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if report is None or not report.pdf_path or not os.path.exists(report.pdf_path):
        raise err("PDF 尚未生成", http_status=404)
    task = db.get(Task, report.task_id)
    if task is None or task.user_id != user.id:
        raise err("无权访问", http_status=403)
    return FileResponse(report.pdf_path, filename=os.path.basename(report.pdf_path), media_type="application/pdf")


@router.post("/{report_id}/supplements", response_model=ApiResponse)
async def upload_supplements(
    report_id: int,
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """补充材料上传（P1 完善 AI 分发与重新生成）"""
    report = db.get(Report, report_id)
    if report is None:
        raise err("报告不存在", http_status=404)
    task = db.get(Task, report.task_id)
    if task is None or task.user_id != user.id:
        raise err("无权访问", http_status=403)

    os.makedirs(settings.upload_dir, exist_ok=True)
    saved = []
    parsed = []
    for f in files:
        data = await f.read()
        # 文件名消毒，防路径穿越
        safe_name = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", f.filename or "file")
        path = os.path.join(settings.upload_dir, f"{report_id}_{safe_name}")
        with open(path, "wb") as fp:
            fp.write(data)
        upload = Upload(
            user_id=user.id, report_id=report_id, filename=safe_name,
            stored_path=path, file_type=safe_name.split(".")[-1].lower(), size=len(data),
            status="uploaded",
        )
        db.add(upload)
        db.flush()

        # AI 解析分发（尽力而为，失败不阻塞上传）
        try:
            from ..services.supplement_parser import classify_content, extract_text_from_file

            text = extract_text_from_file(path, upload.file_type)
            result = classify_content(text, safe_name)
            upload.status = "parsed" if text else "unreadable"
            upload.parsed_summary = result["summary"]
            parsed.append(result)
        except Exception as e:  # noqa: BLE001
            logger.exception("supplement parse failed: %s", safe_name)
            upload.status = "failed"

        saved.append(safe_name)

    # 记录到报告的 supplements（JSON），供重新生成引用
    existing = json.loads(report.supplements) if report.supplements else []
    existing.extend(parsed)
    report.supplements = json.dumps(existing, ensure_ascii=False)
    db.commit()

    # 触发后台重新生成报告（version+1）
    if parsed:
        from ..services.due_diligence import regenerate_report

        background.add_task(regenerate_report, report.id)

    return ok({"uploaded": saved, "parsed": parsed, "regenerating": bool(parsed)}, f"上传并解析完成（{len(parsed)} 份已识别分发），报告重新生成中…")


@router.get("/{report_id}/versions", response_model=ApiResponse)
def list_report_versions(report_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """报告历史版本列表（元信息，不含全文）"""
    report = db.get(Report, report_id)
    if report is None:
        raise err("报告不存在", http_status=404)
    task = db.get(Task, report.task_id)
    if task is None or task.user_id != user.id:
        raise err("无权访问", http_status=403)
    versions = db.query(ReportVersion).filter(ReportVersion.report_id == report_id).order_by(ReportVersion.version.desc()).all()
    return ok({
        "current_version": report.version,
        "versions": [
            {
                "version": v.version,
                "source": v.source,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ],
    })


@router.get("/{report_id}/versions/{version}", response_model=ApiResponse)
def get_report_version(report_id: int, version: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """查看指定历史报告版本全文（可回退参考）"""
    report = db.get(Report, report_id)
    if report is None:
        raise err("报告不存在", http_status=404)
    task = db.get(Task, report.task_id)
    if task is None or task.user_id != user.id:
        raise err("无权访问", http_status=403)
    v = db.query(ReportVersion).filter(ReportVersion.report_id == report_id, ReportVersion.version == version).first()
    if v is None:
        raise err("版本不存在", http_status=404)
    return ok({
        "version": v.version,
        "source": v.source,
        "content": json.loads(v.content) if v.content else None,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    })


@router.post("/{report_id}/versions/{version}/restore", response_model=ApiResponse)
def restore_report_version(report_id: int, version: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """回退到指定历史版本：当前内容先存档为新版本，再以目标版本内容覆盖当前报告"""
    report = db.get(Report, report_id)
    if report is None:
        raise err("报告不存在", http_status=404)
    task = db.get(Task, report.task_id)
    if task is None or task.user_id != user.id:
        raise err("无权访问", http_status=403)
    target = db.query(ReportVersion).filter(ReportVersion.report_id == report_id, ReportVersion.version == version).first()
    if target is None:
        raise err("版本不存在", http_status=404)

    # 当前内容存档（避免回退丢失最新版）
    if report.content and report.content != target.content:
        db.add(ReportVersion(
            report_id=report.id, version=report.version or 1,
            content=report.content, source="manual",
        ))
    report.content = target.content
    report.version = (report.version or 1) + 1
    report.pdf_path = None  # 旧 PDF 失效
    db.commit()
    return ok({"version": report.version}, f"已回退到 v{version}（当前为 v{report.version}）")


@router.put("/{report_id}/section-note", response_model=ApiResponse)
def add_section_note(report_id: int, req: SectionNoteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    report = db.get(Report, report_id)
    if report is None:
        raise err("报告不存在", http_status=404)
    task = db.get(Task, report.task_id)
    if task is None or task.user_id != user.id:
        raise err("无权访问", http_status=403)

    content = json.loads(report.content or "{}")
    notes = content.setdefault("section_notes", {})
    notes[req.section] = req.note
    report.content = json.dumps(content, ensure_ascii=False)
    db.commit()
    return ok(None, "备注已保存")
