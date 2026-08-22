"""对比分析路由（P2）：选择多个已完成报告横向对比"""
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Report, Task, User
from ..schemas.common import ApiResponse, err, ok
from ..services.comparison import build_comparison, summarize_comparison
from .deps import get_current_user

router = APIRouter(prefix="/compare", tags=["compare"])


class CompareRequest(BaseModel):
    report_ids: list[int] = Field(min_length=2, max_length=10)


@router.post("", response_model=ApiResponse)
async def compare(
    req: CompareRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 校验报告归属
    reports = []
    for rid in req.report_ids:
        report = db.get(Report, rid)
        if report is None:
            raise err(f"报告 {rid} 不存在", http_status=404)
        task = db.get(Task, report.task_id)
        if task is None or task.user_id != user.id:
            raise err(f"无权访问报告 {rid}", http_status=403)
        if not report.content:
            raise err(f"报告 {rid} 内容未生成")
        reports.append(report)

    comparison = build_comparison(reports)
    return ok(comparison, "对比数据已生成")


@router.post("/summary", response_model=ApiResponse)
async def compare_summary(
    req: CompareRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """LLM 生成对比总结（耗时，前端可单独触发）"""
    reports = []
    for rid in req.report_ids:
        report = db.get(Report, rid)
        if report is None:
            raise err(f"报告 {rid} 不存在", http_status=404)
        task = db.get(Task, report.task_id)
        if task is None or task.user_id != user.id:
            raise err(f"无权访问报告 {rid}", http_status=403)
        if report.content:
            reports.append(report)

    comparison = build_comparison(reports)
    summary = await summarize_comparison(comparison)
    return ok(summary, "对比总结已生成")
