"""反馈路由：用户提交 + 管理后台处理"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Feedback, User
from ..schemas.common import ApiResponse, err, ok
from .deps import get_current_user, require_admin

router = APIRouter(tags=["feedback"])


class FeedbackCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    contact: str | None = Field(default=None, max_length=100)


class FeedbackStatusUpdate(BaseModel):
    status: str = Field(pattern="^(pending|done|ignored)$")


def _fb_to_dict(f: Feedback) -> dict:
    return {
        "id": f.id,
        "user_id": f.user_id,
        "content": f.content,
        "contact": f.contact,
        "status": f.status,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


@router.post("/feedback", response_model=ApiResponse)
def submit_feedback(req: FeedbackCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fb = Feedback(user_id=user.id, content=req.content, contact=req.contact, status="pending")
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return ok(_fb_to_dict(fb), "反馈已提交，感谢您的建议")


@router.get("/admin/feedbacks", response_model=ApiResponse)
def list_feedbacks(status: str | None = None, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(Feedback).order_by(Feedback.id.desc())
    if status:
        if status not in ("pending", "done", "ignored"):
            raise err("未知状态")
        q = q.where(Feedback.status == status)
    items = db.scalars(q.limit(200)).all()
    return ok({"feedbacks": [_fb_to_dict(f) for f in items]})


@router.put("/admin/feedbacks/{feedback_id}", response_model=ApiResponse)
def update_feedback_status(feedback_id: int, req: FeedbackStatusUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise err("反馈不存在", http_status=404)
    fb.status = req.status
    db.commit()
    return ok(_fb_to_dict(fb), "状态已更新")
